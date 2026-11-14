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

    def test_real_goal_resolver_selects_live_scheduler_without_sync_planner(self):
        from modules import goal_resolver
        from modules.brain_contracts import GoalOperation
        runtime = SimpleNamespace(profile=SimpleNamespace(slug=self.owner))
        entry = SimpleNamespace(
            owner=self.owner, request_id=self.request_id, text=self.text,
            source="ses", active_context=SimpleNamespace(goal_candidates=()),
            understanding=SimpleNamespace(goal_operation=GoalOperation.CREATE),
        )
        with patch.object(task_queue, "scheduler_active", return_value=True), \
             patch.object(canonical_planning_queue, "enqueue",
                          return_value=("0123456789abcdef", "Sıraya alındı.")) as admission, \
             patch.object(canonical_goal_flow, "try_create",
                          side_effect=AssertionError("Synchronous planner must not start")):
            resolved = goal_resolver.resolve(runtime, entry)
        self.assertEqual(resolved.reason_code, "GOAL_CANONICAL_PLANNING_QUEUED")
        self.assertEqual(resolved.job_id, "0123456789abcdef")
        self.assertEqual(resolved.result_status, "handled")
        admission.assert_called_once_with(self.owner, self.request_id, self.text)
        self.ask.assert_not_called()

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

    def test_queued_planner_wakes_only_after_both_durable_records_exist(self):
        calls = []

        def confirm_published():
            job_id, _planner_rid = canonical_planning_queue._identity(
                self.owner, self.request_id)
            state, record = self.persisted(self.owner, job_id)
            self.assertEqual(state['owner'], self.owner)
            self.assertEqual(record['request_id'], self.request_id)
            self.assertEqual(record['state'], 'planning_queued')
            calls.append(job_id)

        with patch.object(task_queue, 'wake_scheduler',
                          side_effect=confirm_published):
            job_id, _message = self.claim()
            self.assertEqual(self.claim()[0], job_id)
        self.assertEqual(calls, [job_id],
                         'duplicate RID must not re-admit or wake a planner')

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

    def test_unsupported_job_requires_exact_one_shot_foreground_reauthorization(self):
        job_id, _ = self.claim()
        self.ask.return_value = '{"tasks":[]}'
        self.assertEqual(canonical_planning_queue.execute(
            SimpleNamespace(slug=self.owner), job_id), "review")
        self.assertIn("hedef ön plan " + job_id,
                      canonical_planning_queue.status(self.owner, job_id))
        self.assertIsNone(canonical_planning_queue.take_foreground(
            self.owner, "normal conversation"))
        identity, text = canonical_planning_queue.take_foreground(
            self.owner, "hedef ön plan " + job_id)
        self.assertEqual((identity, text), (job_id, self.text))
        self.assertIn("tek seferlik", canonical_planning_queue.status(self.owner, job_id))
        with self.assertRaises(ValueError):
            canonical_planning_queue.take_foreground(
                self.owner, "hedef ön plan " + job_id)
        with self.assertRaises(ValueError):
            canonical_planning_queue.take_foreground(
                "other-voice", "hedef ön plan " + job_id)
        self.assertEqual(self.ask.call_count, 1)

    def test_uncertain_timeout_cannot_use_foreground_shortcut(self):
        job_id, _ = self.claim()
        self.ask.side_effect = TimeoutError("simulated")
        self.assertEqual(canonical_planning_queue.execute(
            SimpleNamespace(slug=self.owner), job_id), "review")
        self.assertNotIn("hedef ön plan " + job_id,
                         canonical_planning_queue.status(self.owner, job_id))
        with self.assertRaises(ValueError):
            canonical_planning_queue.take_foreground(
                self.owner, "hedef ön plan " + job_id)

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
        import release_guard
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

    def test_three_first_plans_run_through_same_real_scheduler_pool(self):
        from modules import canonical_scheduler_dispatch, service_store
        import time

        class QuickStop:
            def __init__(self):
                self.signal = threading.Event()
            def wait(self, seconds):
                return self.signal.wait(min(seconds, .03))
            def is_set(self):
                return self.signal.is_set()
            def set(self):
                self.signal.set()

        jobs = [self.claim("real-scheduler-" + str(i))[0] for i in range(3)]
        barrier = threading.Barrier(3, timeout=8)
        seen = []
        def model(*args, **kwargs):
            # Three real Scheduler-owned planner threads reach the provider
            # seam together; there is no owner-global execution mutex here.
            barrier.wait()
            return research_plan()
        self.ask.side_effect = model
        stop = QuickStop()
        workers = {}
        with patch.object(task_queue, "_THREAD", None), \
             patch.object(task_queue, "_CANONICAL_WORKERS", workers), \
             patch.object(task_queue, "_LAST_CANONICAL_ADMITTED", {}), \
             patch.object(task_queue, "_CANONICAL_RESUME_ATTEMPTED", set()), \
             patch.object(service_store, "ROOT", self.root / "missing-service-store"), \
             patch.object(canonical_scheduler_dispatch, "discover", return_value=()):
            try:
                task_queue.start(
                    stop,
                    allowed_owners=lambda: {self.owner},
                    canonical_profile_resolver=lambda owner: SimpleNamespace(slug=owner),
                    canonical_plan_notify=lambda owner, job, result: seen.append(
                        (owner, job, result)),
                )
                deadline = time.monotonic() + 10
                while len(seen) < 3 and time.monotonic() < deadline:
                    time.sleep(.015)
                self.assertEqual(set(seen), {(self.owner, job, "planned") for job in jobs})
                self.assertEqual(self.ask.call_count, 3)
                for job in jobs:
                    state, record = self.persisted(self.owner, job)
                    self.assertEqual(record["state"], "running")
                    self.assertEqual(state["version"], 1)
            finally:
                stop.set()
                if task_queue._THREAD is not None:
                    task_queue._THREAD.join(timeout=1)
                for worker in tuple(workers.values()):
                    worker.join(timeout=2)
