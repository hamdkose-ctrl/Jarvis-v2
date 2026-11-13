"""VOICE §5: first-plan execution is owner pinned on the existing Scheduler.

No real network/model/device work is performed. Actual GoalState CAS and
ExecutionRecord writes, duplicate IDs, plan verification and cancellation
are exercised in an isolated owner namespace.
"""
from __future__ import annotations

from contextlib import ExitStack, nullcontext
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch, Mock
import threading

from modules import (
    canonical_planning_queue, canonical_goal_flow, canonical_scheduler_lane,
    execution_record, goal_executor, goal_state_store, model_wait, requests_state,
    task_queue,
)


def research_plan():
    return json.dumps({'tasks': [
        {'id': 'source', 'agent': 'research', 'depends': [],
         'input': {'url': 'https://example.test/article', 'question': 'compare'}}
    ]})


class DeferredPlannerTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.owner = "voice-background-a"
        self.request_id = "initial-user-turn"
        self.text = "İki güvenilir kaynağı araştır."
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(goal_executor, "STORE", self.root))
        self.register = self.stack.enter_context(
            patch.object(requests_state, "register_background", return_value=True))
        self.stack.enter_context(patch.object(requests_state, "check", return_value=None))
        self.stack.enter_context(patch.object(requests_state, "activate",
                                              side_effect=lambda *a, **k: nullcontext()))
        self.stack.enter_context(patch.object(requests_state, "allow_long_operation"))
        self.cancelled = self.stack.enter_context(
            patch.object(requests_state, "is_cancelled", return_value=False))
        self.ask = self.stack.enter_context(
            patch.object(model_wait, "ask", return_value=research_plan()))

    def claim(self, rid=None, owner=None):
        return canonical_planning_queue.enqueue(
            owner or self.owner, rid or self.request_id, self.text)

    def persisted(self, owner, job_id):
        base = goal_executor._owner_root(owner)
        return (goal_state_store.load(base / (job_id + ".goalstate.json")),
                execution_record.load(base, owner, job_id))

    def test_enqueue_creates_exact_owner_bound_durable_pair_without_model(self):
        job_id, message = self.claim()
        self.assertIn("kuyruğuna", message)
        state, record = self.persisted(self.owner, job_id)
        self.assertEqual(state["owner"], self.owner)
        self.assertEqual(state["version"], 0)
        self.assertEqual(state["state"], "pending")
        self.assertNotIn("goal_plan", state)
        self.assertEqual(record["state"], "planning_queued")
        self.assertEqual(record["request_id"], self.request_id)
        self.assertEqual(record["steps"], [])
        self.ask.assert_not_called()
        self.assertEqual(canonical_planning_queue.discover(self.owner), (job_id,))
        self.assertEqual(self.claim()[0], job_id)
        self.register.assert_called_once()
        self.ask.assert_not_called()

    def test_owner_isolation_and_two_jobs_are_independent(self):
        a, _ = self.claim("request-a")
        b, _ = self.claim("request-b")
        foreign, _ = self.claim("request-a", owner="other-voice")
        self.assertEqual(len({a, b, foreign}), 3)
        self.assertEqual(set(canonical_planning_queue.discover(self.owner)), {a, b})
        self.assertEqual(canonical_planning_queue.discover("other-voice"), (foreign,))
        self.assertIsNone(canonical_planning_queue.status(self.owner, foreign))

    def test_one_scheduler_worker_publishes_plan_then_existing_workers_can_offer(self):
        job_id, _ = self.claim()
        outcome = canonical_planning_queue.execute(
            SimpleNamespace(slug=self.owner), job_id, stop_event=threading.Event())
        self.assertEqual(outcome, "planned")
        self.assertEqual(self.ask.call_count, 1)
        state, record = self.persisted(self.owner, job_id)
        self.assertEqual(state["version"], 1)
        self.assertEqual(state["goal_plan"]["nodes"][0]["capability_id"], "task.research")
        self.assertEqual(record["state"], "running")
        self.assertEqual(record["steps"][0]["state"], "queued")
        self.assertEqual(canonical_planning_queue.discover(self.owner), ())
        self.assertIn("Scheduler", canonical_planning_queue.status(self.owner, job_id))
        offers = canonical_scheduler_lane.ready_offers(self.owner, job_id)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].selection.owner, self.owner)
        self.assertFalse(canonical_planning_queue.execute(
            SimpleNamespace(slug=self.owner), job_id))
        self.assertEqual(self.ask.call_count, 1)

    def test_unsupported_planner_never_executes_effects_or_retries(self):
        job_id, _ = self.claim()
        self.ask.return_value = json.dumps({'tasks': [
            {'id': 'unsafe', 'agent': 'writer', 'depends': [],
             'input': {'filename': 'report.txt', 'text': 'hello'}}
        ]})
        self.assertEqual(canonical_planning_queue.execute(
            SimpleNamespace(slug=self.owner), job_id), "review")
        state, record = self.persisted(self.owner, job_id)
        self.assertEqual(state["state"], "paused")
        self.assertNotIn("goal_plan", state)
        self.assertEqual(record["state"], "review")
        self.assertEqual(canonical_planning_queue.discover(self.owner), ())
        self.assertFalse(canonical_planning_queue.execute(
            SimpleNamespace(slug=self.owner), job_id))
        self.assertEqual(self.ask.call_count, 1)

    def test_cancelled_queued_job_parks_without_provider_call(self):
        job_id, _ = self.claim()
        self.cancelled.return_value = True
        self.assertEqual(canonical_planning_queue.execute(
            SimpleNamespace(slug=self.owner), job_id), "review")
        self.ask.assert_not_called()
        self.assertEqual(self.persisted(self.owner, job_id)[0]["state"], "paused")
        self.assertEqual(canonical_planning_queue.discover(self.owner), ())

    def test_started_attempt_after_restart_can_never_be_redispatched(self):
        job_id, _ = self.claim()
        base = goal_executor._owner_root(self.owner)
        from modules import release_guard
        _, record = self.persisted(self.owner, job_id)
        record["state"] = "planning_running"
        release_guard.atomic(base / (job_id + ".execution.json"),
                             execution_record.encode(record))
        self.assertEqual(canonical_planning_queue.discover(self.owner), ())
        self.assertFalse(canonical_planning_queue.execute(
            SimpleNamespace(slug=self.owner), job_id))
        self.ask.assert_not_called()

    def test_fail_closed_identity_mismatch_and_no_user_profile_borrowing(self):
        job_id, _ = self.claim()
        with self.assertRaises((ValueError, FileNotFoundError)):
            canonical_planning_queue.execute(
                SimpleNamespace(slug="other-voice"), job_id)
        self.assertEqual(self.persisted(self.owner, job_id)[1]["state"],
                         "planning_queued")
        self.ask.assert_not_called()

    def test_exact_status_read_is_not_an_effect_and_does_not_reply_as_done(self):
        job_id, _ = self.claim()
        status = canonical_goal_flow.read_result_command(
            self.owner, "hedef sonucu " + job_id)
        self.assertIn("kuyruğunda", status)
        self.assertIsNone(canonical_planning_queue.status("other-voice", job_id))
        self.ask.assert_not_called()

    def test_actual_engine_scheduler_availability_is_not_an_unbounded_thread(self):
        self.assertFalse(task_queue.scheduler_active() and task_queue._THREAD is None)
