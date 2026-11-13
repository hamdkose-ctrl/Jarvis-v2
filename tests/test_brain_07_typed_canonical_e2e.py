"""BRAIN-07: real typed Brain → Core publication → existing Scheduler → delivery.

No real model/provider/device is called. The Brain transport and provider
worker are the only mocked external boundaries; journals, Core CAS, Scheduler,
domain evidence, and first-party completion code remain live.
"""
from __future__ import annotations

import json
import release_guard
import subprocess
import sys
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_brain_pr3_raw_text_authority import _CanonicalAuthorityHarness
from modules import (
    account_tools, brain_entry, canonical_goal_flow, canonical_plan_evidence,
    canonical_scheduler_dispatch, execution_record, goal_executor,
    goal_state_compat, goal_state_store, model_wait, requests_state, service_store,
    smart_router, task_agents, task_queue, task_results, untrusted_flow,
    scheduler_resource_gate,
)
from modules import brain_model_understanding as envelope


def research_tasks(*names):
    return {'tasks': [
        {'id': name, 'agent': 'research', 'depends': [],
         'input': {'url': 'https://example.test/article', 'question': 'compare'}}
        for name in names
    ]}


class RapidStop:
    def __init__(self):
        self.event = threading.Event()
    def wait(self, _timeout):
        return self.event.wait(.015)
    def is_set(self):
        return self.event.is_set()
    def set(self):
        self.event.set()


class TypedCanonicalFlowTests(_CanonicalAuthorityHarness):
    """Use real Brain prepare/handoff with mocked semantic provider payload."""

    def setUp(self):
        super().setUp()
        self.mocks = ExitStack()
        self.addCleanup(self.mocks.close)
        # Shared provider claim namespace must be real but isolated from
        # another test's OS-user or a currently running Jarvis instance.
        self.mocks.enter_context(patch.object(
            scheduler_resource_gate, '_ACCOUNT_CLAIM_ROOT',
            goal_executor.STORE / '_test_provider_claims',
        ))
        for target, value in (
            ('modules.llm.current_user', lambda: self.owner),
            ('modules.llm.provider', lambda: 'groq'),
            ('modules.llm.privacy.mode', lambda: 'normal'),
            ('modules.smart_router.selection', lambda *args, **kwargs: {'candidates': ['groq']}),
        ):
            self.mocks.enter_context(patch(target, value))
        # Install ONE router stub per test, not a nested monkeypatch per
        # request. Two concurrent typed_turn() calls must not restore each
        # other's previous patched value into the global router module.
        self.router_stub = self.mocks.enter_context(patch(
            'modules.smart_router.run', return_value=self.envelope(),
        ))

    def envelope(self):
        return json.dumps({
            'schema_version': envelope.SCHEMA_VERSION,
            'operation': 'create_goal', 'conversation_relation': 'NEW_REQUEST',
            'temporal_need': 'STATIC', 'target_goal_ids': [],
            'goal': {'kind': 'goal', 'title': 'Kaynakları karşılaştır'},
            'actions': [],
            'clarification': {'required': False, 'question': None, 'reason_code': None},
            'confidence': 'HIGH',
        })

    def typed_turn(self, request='İki kaynağı araştır ve karşılaştır.', rid=None, *, source='yazı'):
        rid = rid or ('brain07-' + uuid.uuid4().hex[:12])
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            entry = brain_entry.prepare(
                self.ctx, owner=self.owner, request_id=rid,
                text=request, source=source, model_understanding=True,
            )
            result, feedback, job_id = brain_entry.handoff(
                self.ctx, entry, Mock(return_value='LEGACY_HANDLER'), request,
            )
        return rid, result, feedback, job_id

    def persisted(self, job_id):
        root = goal_executor._owner_root(self.owner)
        return (
            goal_state_store.load(root / (job_id + '.goalstate.json')),
            execution_record.load(root, self.owner, job_id),
        )

    def test_parallel_typed_turns_share_one_router_stub_without_global_leak(self):
        """Regression: nested monkeypatches in parallel left a fake router
        installed for unrelated test modules after their cleanup."""
        self.assertIs(smart_router.run, self.router_stub)
        reached = threading.Barrier(2, timeout=10)

        def semantic_reply(*args, **kwargs):
            # Both threads must be inside the router call concurrently. A
            # per-turn patch would bypass this fixture stub entirely.
            reached.wait()
            return self.envelope()

        self.router_stub.side_effect = semantic_reply
        with patch.object(model_wait, 'ask',
                          return_value=json.dumps(research_tasks('first'))):
            with ThreadPoolExecutor(max_workers=2) as executor:
                left = executor.submit(self.typed_turn, rid='router-identity-left')
                right = executor.submit(self.typed_turn, rid='router-identity-right')
                left_result = left.result(timeout=20)
                right_result = right.result(timeout=20)

        self.assertEqual(self.router_stub.call_count, 2)
        self.assertIs(smart_router.run, self.router_stub)
        self.assertNotEqual(left_result[3], right_result[3])
        self.assertEqual(left_result[2].reason_code,
                         'GOAL_CANONICAL_BACKGROUND_QUEUED')
        self.assertEqual(right_result[2].reason_code,
                         'GOAL_CANONICAL_BACKGROUND_QUEUED')
        self.run_goal.assert_not_called()

    def test_typed_user_request_publishes_matching_core_plan_and_queued_record(self):
        with patch.object(model_wait, 'ask', return_value=json.dumps(research_tasks('first', 'second'))):
            rid, reply, fb, job_id = self.typed_turn()
        self.assertEqual(fb.reason_code, 'GOAL_CANONICAL_BACKGROUND_QUEUED')
        self.assertIn('arka plana', reply)
        self.assertEqual(len(job_id), 16)
        state, journal = self.persisted(job_id)
        self.assertEqual(state['authority'], 'canonical')
        self.assertEqual(state['version'], 1)
        self.assertEqual(state['audit'][-1]['reason_code'], 'CORE_GOAL_PLAN_ACCEPTED')
        self.assertEqual(state['goal_plan']['plan_version'], 1)
        self.assertEqual([row['id'] for row in state['goal_plan']['nodes']], ['first', 'second'])
        self.assertEqual([row['state'] for row in journal['steps']], ['queued', 'queued'])
        self.assertEqual(journal['request_id'], rid)
        self.assertEqual(canonical_scheduler_dispatch.discover(self.owner)[0].selection.job_id, job_id)
        self.run_goal.assert_not_called()

    def test_voice_goal_uses_same_canonical_background_lane_as_text(self):
        # The transport source must not silently select the foreground legacy
        # executor when Brain proposed the same read-only typed goal.
        with patch.object(model_wait, 'ask',
                          return_value=json.dumps(research_tasks('first'))):
            _, reply, feedback, job_id = self.typed_turn(source='ses')
        self.assertEqual(feedback.reason_code, 'GOAL_CANONICAL_BACKGROUND_QUEUED')
        self.assertIn('arka plana', reply)
        state, record = self.persisted(job_id)
        self.assertEqual(state['authority'], 'canonical')
        self.assertEqual(record['steps'][0]['state'], 'queued')
        self.run_goal.assert_not_called()

    def test_canonical_goal_continue_does_not_reenter_legacy_planner(self):
        from modules import goal_resolver
        from modules.brain_contracts import GoalOperation
        with patch.object(model_wait, 'ask',
                          return_value=json.dumps(research_tasks('first'))):
            _, _, _, job_id = self.typed_turn()
        before = self.persisted(job_id)
        with patch.object(goal_executor, 'run',
                          side_effect=AssertionError('legacy executor must not resume DAG')):
            reply = goal_resolver._dispatch(
                self.ctx, goal_executor, self.owner,
                GoalOperation.CONTINUE, job_id, 'hedef devam', {},
            )
        self.assertIn('ikinci bir çalışma başlatmadı', reply)
        self.assertEqual(self.persisted(job_id), before)

    def test_direct_bounded_legacy_resume_cannot_reenter_canonical_goal(self):
        with patch.object(model_wait, 'ask',
                          return_value=json.dumps(research_tasks('first'))):
            _, _, _, job_id = self.typed_turn()
        before = self.persisted(job_id)
        control = goal_executor.control_key(
            goal_executor.read_job(self.owner, job_id),
        )
        # This harness mocks goal_executor.run globally as GOAL_RUN. Exercise
        # the actual direct executor seam instead of asserting against that
        # unrelated fixture sentinel.
        with patch.object(goal_executor, 'run', wraps=goal_executor._run), \
             patch.object(goal_executor, '_loop',
                          side_effect=AssertionError('legacy model worker replay')):
            reply = goal_executor.handle(
                self.ctx, f'hedef devam {job_id} {control}',
            )
        self.assertIn('ikinci bir yürütme başlatılmadı', reply)
        self.assertEqual(self.persisted(job_id), before)

    def test_direct_executor_approval_cannot_start_canonical_worker(self):
        with patch.object(model_wait, 'ask',
                          return_value=json.dumps(research_tasks('first'))):
            _, _, _, job_id = self.typed_turn()
        before = self.persisted(job_id)
        with patch.object(goal_executor, 'run', wraps=goal_executor._run), \
             patch.object(goal_executor, '_loop',
                          side_effect=AssertionError('legacy approve replay')):
            reply = goal_executor.run(
                self.ctx, 'hedef onayla', approve=True, job_id=job_id,
            )
        self.assertIn('Scheduler yürütür', reply)
        self.assertEqual(self.persisted(job_id), before)

    def test_legacy_save_cannot_mark_canonical_plan_done_without_worker_proof(self):
        with patch.object(model_wait, 'ask',
                          return_value=json.dumps(research_tasks('first'))):
            _, _, _, job_id = self.typed_turn()
        before = self.persisted(job_id)
        unsound = goal_executor.read_job(self.owner, job_id)
        unsound['state'] = 'done'
        unsound['goals'][0]['state'] = 'done'
        # The actual production save hook must reject this forged legacy
        # completion before either the Core state or ExecutionRecord changes.
        with self.assertRaises(goal_state_compat.ReconcilePolicyError):
            goal_executor._save(unsound, move_pointer=False)
        self.assertEqual(self.persisted(job_id), before)

    def test_targeted_cancel_of_canonical_plan_is_a_core_terminal_fence(self):
        with patch.object(model_wait, 'ask',
                          return_value=json.dumps(research_tasks('first'))):
            _, _, _, job_id = self.typed_turn()
        before_state, before_record = self.persisted(job_id)
        self.assertEqual(before_record['state'], 'running')
        with patch('modules.service_store.identity', return_value=self.owner):
            reply = goal_executor.cancel_job(self.owner, job_id)
        self.assertIn('İptal kaydedildi', reply)
        state, record = self.persisted(job_id)
        self.assertEqual(state['state'], 'cancelled')
        self.assertGreater(state['version'], before_state['version'])
        self.assertEqual(record['state'], 'cancelled')
        self.assertEqual(canonical_scheduler_dispatch.discover(self.owner), ())
        self.run_goal.assert_not_called()

    def test_duplicate_typed_request_cannot_publish_second_attempt(self):
        with patch.object(model_wait, 'ask',
                          return_value=json.dumps(research_tasks('first'))) as planner:
            rid, _, _, job_id = self.typed_turn()
            state_before, journal_before = self.persisted(job_id)
            _, answer, fb, duplicate = self.typed_turn(rid=rid)
        planner.assert_called_once()
        self.assertEqual(job_id, duplicate)
        self.assertEqual(fb.reason_code, 'GOAL_CANONICAL_BACKGROUND_QUEUED')
        self.assertIn('ikinci kez başlatılmadı', answer)
        self.assertEqual(self.persisted(job_id), (state_before, journal_before))

    def test_duplicate_with_unsupported_second_model_plan_never_enters_legacy(self):
        """A duplicate must win before a different, effectful planner reply.

        Regression for the old order: model validation returned None before
        checking the existing request, then goal_resolver fell back to
        goal_executor._run and allocated a second unrelated goal ID.
        """
        effectful = {'tasks': [{
            'id': 'write', 'agent': 'writer', 'depends': [],
            'input': {'instruction': 'Save report', 'filename': 'report.md'},
        }]}
        with patch.object(model_wait, 'ask', side_effect=[
            json.dumps(research_tasks('first')), json.dumps(effectful),
        ]) as planner:
            rid, _, first_fb, job_id = self.typed_turn()
            before = self.persisted(job_id)
            _, reply, second_fb, same_job = self.typed_turn(rid=rid)
        self.assertEqual(first_fb.reason_code, 'GOAL_CANONICAL_BACKGROUND_QUEUED')
        planner.assert_called_once()
        self.assertEqual(same_job, job_id)
        self.assertEqual(second_fb.reason_code, 'GOAL_CANONICAL_BACKGROUND_QUEUED')
        self.assertIn('ikinci kez başlatılmadı', reply)
        self.assertEqual(before, self.persisted(job_id))
        self.run_goal.assert_not_called()
        root = goal_executor._owner_root(self.owner)
        self.assertEqual(len(tuple(root.glob('*.execution.json'))), 1)

    def test_concurrent_missing_request_cannot_escape_to_legacy_with_unsupported_second_plan(self):
        """Two real parallel typed turns enter before either record is created.

        A valid canonical planner call is blocked on an event. The other caller
        enters the same request before publication; under the old two-check
        design it could receive an unsupported model plan and fall back to
        goal_executor.run with an unrelated UUID. The new admission gate
        forces it to observe the first published journal without a model call.
        """
        entered_model = threading.Event()
        entered_second_turn = threading.Event()
        release_first = threading.Event()
        guard = threading.Lock()
        calls = []
        arrivals = 0
        rid = 'concurrent-first-admission'
        original = canonical_goal_flow.try_create
        effectful = {'tasks': [{
            'id': 'write', 'agent': 'writer', 'depends': [],
            'input': {'instruction': 'Write a duplicate', 'filename': 'duplicate.md'},
        }]}

        def observed_try(*args, **kwargs):
            nonlocal arrivals
            with guard:
                arrivals += 1
                if arrivals == 2:
                    entered_second_turn.set()
            return original(*args, **kwargs)

        def held_model(*args, **kwargs):
            with guard:
                calls.append(1)
                which = len(calls)
            if which == 1:
                entered_model.set()
                if not release_first.wait(15):
                    raise AssertionError('First planner was never released')
                return json.dumps(research_tasks('first'))
            return json.dumps(effectful)

        with patch.object(canonical_goal_flow, 'try_create', side_effect=observed_try), \
                patch.object(model_wait, 'ask', side_effect=held_model):
            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(self.typed_turn, rid=rid)
                try:
                    self.assertTrue(entered_model.wait(10), 'First model did not start')
                    second = executor.submit(self.typed_turn, rid=rid)
                    self.assertTrue(entered_second_turn.wait(10),
                                    'Second typed turn never entered admission')
                    # Both callers entered admission before any first
                    # publication. The first model remains blocked here.
                    root = goal_executor._owner_root(self.owner)
                    self.assertEqual(tuple(root.glob('*.execution.json')), ())
                finally:
                    release_first.set()
                first_result = first.result(timeout=20)
                second_result = second.result(timeout=20)
        self.assertEqual(len(calls), 1, 'Same request called the DAG planner twice')
        self.assertEqual(first_result[3], second_result[3])
        self.assertEqual(first_result[2].reason_code, 'GOAL_CANONICAL_BACKGROUND_QUEUED')
        self.assertEqual(second_result[2].reason_code, 'GOAL_CANONICAL_BACKGROUND_QUEUED')
        self.assertIn('ikinci kez başlatılmadı', second_result[1])
        self.assertEqual(len(tuple(root.glob('*.execution.json'))), 1)
        self.run_goal.assert_not_called()

    def test_unrelated_request_planning_is_not_blocked_by_first_provider(self):
        """The new gate is keyed by request identity, never by owner alone."""
        first_waiting = threading.Event()
        first_release = threading.Event()

        def planned(prompt, **kwargs):
            if 'One source' in prompt:
                first_waiting.set()
                if not first_release.wait(15):
                    raise AssertionError('Independent planner did not release')
                return json.dumps(research_tasks('first'))
            return json.dumps(research_tasks('second'))

        with patch.object(model_wait, 'ask', side_effect=planned):
            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(canonical_goal_flow.try_create,
                                        self.owner, 'independent-one', 'One source')
                try:
                    self.assertTrue(first_waiting.wait(10), 'First request did not plan')
                    second = executor.submit(canonical_goal_flow.try_create,
                                             self.owner, 'independent-two', 'Other source')
                    second_job, _ = second.result(timeout=8)
                finally:
                    first_release.set()
                first_job, _ = first.result(timeout=20)
        self.assertNotEqual(first_job, second_job)
        self.assertEqual(len(tuple((goal_executor.STORE / self.owner).glob(
            '*.execution.json',
        ))), 2)
        self.run_goal.assert_not_called()

    def test_concurrent_valid_plans_admit_only_one_model_decision(self):
        first_entered = threading.Event()
        release = threading.Event()
        started_second = threading.Event()
        calls = []
        original = canonical_goal_flow.try_create
        guard = threading.Lock()

        def observe(*args):
            with guard:
                if first_entered.is_set():
                    started_second.set()
            return original(*args)

        def planned(*args, **kwargs):
            with guard:
                calls.append(1)
                count = len(calls)
            if count == 1:
                first_entered.set()
                self.assertTrue(release.wait(12), 'First planning never released')
                return json.dumps(research_tasks('first'))
            return json.dumps(research_tasks('different'))

        with patch.object(model_wait, 'ask', side_effect=planned), \
                patch.object(canonical_goal_flow, 'try_create', side_effect=observe):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(self.typed_turn, rid='parallel-valid-valid')
                try:
                    self.assertTrue(first_entered.wait(10))
                    second = pool.submit(self.typed_turn, rid='parallel-valid-valid')
                    self.assertTrue(started_second.wait(10))
                finally:
                    release.set()
                one = first.result(timeout=20)
                two = second.result(timeout=20)
        self.assertEqual(len(calls), 1)
        self.assertEqual(one[3], two[3])
        self.assertEqual(self.persisted(one[3])[1]['steps'][0]['id'], 'first')
        self.run_goal.assert_not_called()

    def test_invalid_first_plan_has_durable_one_shot_legacy_fallback(self):
        """Invalid-first/valid-second must not create a second canonical Goal."""
        entered = threading.Event()
        release = threading.Event()
        second_entered = threading.Event()
        calls = []
        original_try = canonical_goal_flow.try_create
        effectful = {'tasks': [{
            'id': 'write', 'agent': 'writer', 'depends': [],
            'input': {'instruction': 'Save report', 'filename': 'report.md'},
        }]}

        def planned(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                entered.set()
                self.assertTrue(release.wait(12))
                return json.dumps(effectful)
            return json.dumps(research_tasks('first'))

        def observed(*args, **kwargs):
            if entered.is_set():
                second_entered.set()
            return original_try(*args, **kwargs)

        with patch.object(model_wait, 'ask', side_effect=planned), \
                patch.object(canonical_goal_flow, 'try_create', side_effect=observed):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(self.typed_turn, rid='parallel-invalid-first')
                try:
                    self.assertTrue(entered.wait(10))
                    second = pool.submit(self.typed_turn, rid='parallel-invalid-first')
                    self.assertTrue(second_entered.wait(10),
                                    'Second typed request did not reach admission')
                    self.assertFalse(first.done())
                finally:
                    release.set()
                first_result = first.result(timeout=20)
                second_result = second.result(timeout=20)
        self.assertEqual(len(calls), 1)
        self.assertEqual(first_result[2].reason_code, 'GOAL_CREATE')
        self.assertEqual(second_result[2].reason_code,
                         'GOAL_LEGACY_DUPLICATE_NOT_RESTARTED')
        self.assertIsNone(second_result[3])
        self.assertIn('ikinci kez çalıştırılmadı', second_result[1])
        self.run_goal.assert_called_once()
        root = goal_executor._owner_root(self.owner)
        self.assertEqual(tuple(root.glob('*.goalstate.json')), ())
        self.assertEqual(tuple(root.glob('*.execution.json')), ())
        # Even a process restart sees a durable refusal, not a new plan.
        with patch.object(model_wait, 'ask',
                          side_effect=AssertionError('no model for legacy duplicate')):
            _, _, again, _ = self.typed_turn(rid='parallel-invalid-first')
        self.assertEqual(again.reason_code, 'GOAL_LEGACY_DUPLICATE_NOT_RESTARTED')
        self.run_goal.assert_called_once()

    def test_legacy_receipt_survives_a_separate_process_restart(self):
        effectful = {'tasks': [{
            'id': 'write', 'agent': 'writer', 'depends': [],
            'input': {'instruction': 'Write report', 'filename': 'report.md'},
        }]}
        rid, text = 'cross-process-legacy-receipt', 'Write report'
        with patch.object(model_wait, 'ask', return_value=json.dumps(effectful)):
            self.assertIsNone(canonical_goal_flow.try_create(self.owner, rid, text))
        # A fresh interpreter has no in-process mutex, test mocks or request
        # context. It still must observe the same durable fallback receipt.
        script = (
            "import sys\nfrom pathlib import Path\n"
            "from modules import canonical_goal_flow as c, goal_executor, model_wait\n"
            "goal_executor.STORE=Path(sys.argv[1])\n"
            "model_wait.ask=lambda *a,**k: (_ for _ in ()).throw("
            "AssertionError('duplicate called model'))\n"
            "result=c.try_create(sys.argv[2],sys.argv[3],sys.argv[4])\n"
            "assert result[0] is None and 'ikinci kez' in result[1]\n"
            "print('legacy_duplicate_blocked')\n"
        )
        p = subprocess.run(
            [sys.executable, '-c', script, str(goal_executor.STORE),
             self.owner, rid, text],
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('legacy_duplicate_blocked', p.stdout)
        self.run_goal.assert_not_called()

    def test_legacy_handoff_receipt_rejects_new_text_and_corruption(self):
        invalid = {'tasks': [{
            'id': 'write', 'agent': 'writer', 'depends': [],
            'input': {'instruction': 'Write report', 'filename': 'report.md'},
        }]}
        rid = 'legacy-one-shot-collision'
        with patch.object(model_wait, 'ask', return_value=json.dumps(invalid)):
            canonical_goal_flow.try_create(self.owner, rid, 'Write report')
        with patch.object(model_wait, 'ask',
                          side_effect=AssertionError('should not replan')):
            with self.assertRaises(ValueError):
                canonical_goal_flow.try_create(
                    self.owner, rid, 'Different work with same request ID',
                )
        job_id = canonical_goal_flow.hashlib.sha256(
            (self.owner + '\x00' + rid).encode('utf-8')
        ).hexdigest()[:16]
        marker = goal_executor._owner_root(self.owner) / (job_id + '.planning')
        marker.write_text('corrupt receipt', encoding='utf-8')
        with patch.object(model_wait, 'ask',
                          side_effect=AssertionError('must fail closed')):
            with self.assertRaises(ValueError):
                canonical_goal_flow.try_create(self.owner, rid, 'Write report')

    def test_timeout_first_attempt_never_claims_legacy_or_stale_completion(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []

        def planned(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                entered.set()
                self.assertTrue(release.wait(12))
                raise model_wait.ModelWaitTimeout('mock first provider timed out')
            return json.dumps(research_tasks('first'))

        with patch.object(model_wait, 'ask', side_effect=planned):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(canonical_goal_flow.try_create,
                                    self.owner, 'timeout-first', 'Read sources')
                try:
                    self.assertTrue(entered.wait(10))
                    second = pool.submit(canonical_goal_flow.try_create,
                                         self.owner, 'timeout-first', 'Read sources')
                finally:
                    release.set()
                with self.assertRaises(model_wait.ModelWaitTimeout):
                    first.result(timeout=20)
                job_id, _ = second.result(timeout=20)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.persisted(job_id)[0]['state'], 'pending')
        self.run_goal.assert_not_called()

    def test_cancelled_model_cannot_publish_after_its_provider_returns(self):
        entered = threading.Event()
        release = threading.Event()
        rid = 'cancel-during-planning'
        requests_state.register(self.owner, rid)

        def planned(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(12))
            return json.dumps(research_tasks('first'))

        with patch.object(model_wait, 'ask', side_effect=planned):
            with ThreadPoolExecutor(max_workers=1) as pool:
                def task():
                    with requests_state.activate(self.owner, rid):
                        return canonical_goal_flow.try_create(
                            self.owner, rid, 'Read a source',
                        )
                future = pool.submit(task)
                try:
                    self.assertTrue(entered.wait(10))
                    requests_state.cancel(self.owner, rid)
                finally:
                    release.set()
                with self.assertRaises(requests_state.Cancelled):
                    future.result(timeout=20)
        self.assertEqual(tuple((goal_executor.STORE / self.owner).glob(
            '*.goalstate.json',
        )), ())
        self.run_goal.assert_not_called()

    def test_cross_process_same_id_planning_guard_excludes_second_process(self):
        """Directly verify the OS lock with a separately imported Python process."""
        base = Path(self.temp.name)
        root = base / 'process-lock-owner'
        root.mkdir()
        ready, acquired = base / 'spawn-ready', base / 'spawn-acquired'
        job_id = '0123456789abcdef'
        script = ("import sys\nfrom pathlib import Path\n"
                  "from modules import canonical_goal_flow as m\n"
                  "root=Path(sys.argv[1])\n"
                  "Path(sys.argv[3]).write_text('ready')\n"
                  "with m._planning_once(root,sys.argv[2]):\n"
                  "    Path(sys.argv[4]).write_text('acquired')\n")
        proc = None
        with canonical_goal_flow._planning_once(root, job_id):
            try:
                proc = subprocess.Popen(
                    [sys.executable, '-c', script, str(root), job_id,
                     str(ready), str(acquired)],
                    cwd=str(Path(__file__).resolve().parents[1]),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True,
                )
                deadline = time.monotonic() + 10
                while not ready.exists() and time.monotonic() < deadline:
                    self.assertIsNone(proc.poll(), 'Child process exited before lock attempt')
                    time.sleep(.02)
                self.assertTrue(ready.exists(), 'Child process failed to start')
                time.sleep(.2)
                self.assertFalse(acquired.exists(),
                                 'Second process entered same-ID critical section')
            finally:
                if proc is not None and proc.poll() is not None:
                    out, err = proc.communicate()
                    self.assertEqual(proc.returncode, 0, out + err)
        if proc is not None:
            try:
                stdout, stderr = proc.communicate(timeout=15)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()
            self.assertEqual(proc.returncode, 0, stderr + stdout)
        self.assertTrue(acquired.exists())

    def test_concurrent_half_published_goal_does_not_fall_back_to_legacy(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []
        original_atomic = canonical_goal_flow.release_guard.atomic

        def held_model(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                entered.set()
                self.assertTrue(release.wait(12))
            return json.dumps(research_tasks('first'))

        def partial_write(path, content):
            if str(path).endswith('.execution.json'):
                raise OSError('simulated power loss before journal publication')
            return original_atomic(path, content)

        with patch.object(model_wait, 'ask', side_effect=held_model), \
                patch.object(canonical_goal_flow.release_guard, 'atomic',
                             side_effect=partial_write):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(self.typed_turn, rid='concurrent-partial-publication')
                try:
                    self.assertTrue(entered.wait(10))
                    second = pool.submit(self.typed_turn,
                                         rid='concurrent-partial-publication')
                finally:
                    release.set()
                with self.assertRaises(OSError):
                    first.result(timeout=20)
                with self.assertRaises(ValueError):
                    second.result(timeout=20)
        self.assertEqual(len(calls), 1)
        self.run_goal.assert_not_called()
        root = goal_executor._owner_root(self.owner)
        self.assertEqual(len(tuple(root.glob('*.goalstate.json'))), 1)
        self.assertEqual(tuple(root.glob('*.execution.json')), ())

    def test_concurrent_same_request_id_different_text_is_rejected(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []

        def planned(*args, **kwargs):
            calls.append(1)
            entered.set()
            self.assertTrue(release.wait(12))
            return json.dumps(research_tasks('first'))

        with patch.object(model_wait, 'ask', side_effect=planned):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(canonical_goal_flow.try_create,
                                    self.owner, 'same-id-conflicting-text', 'First question')
                try:
                    self.assertTrue(entered.wait(10))
                    second = pool.submit(canonical_goal_flow.try_create,
                                         self.owner, 'same-id-conflicting-text',
                                         'Different question')
                finally:
                    release.set()
                job_id, _ = first.result(timeout=20)
                with self.assertRaises(ValueError):
                    second.result(timeout=20)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.persisted(job_id)[1]['request'], 'First question')
        self.run_goal.assert_not_called()

    def test_failed_legacy_receipt_write_prevents_any_legacy_effect(self):
        legacy = {'tasks': [{
            'id': 'write', 'agent': 'writer', 'depends': [],
            'input': {'instruction': 'Write file', 'filename': 'unsafe.md'},
        }]}
        actual_atomic = canonical_goal_flow.release_guard.atomic

        def fail_receipt(path, content):
            if str(path).endswith('.planning'):
                raise OSError('simulated admission receipt fsync error')
            return actual_atomic(path, content)

        with patch.object(model_wait, 'ask', return_value=json.dumps(legacy)), \
                patch.object(canonical_goal_flow.release_guard, 'atomic',
                             side_effect=fail_receipt):
            with self.assertRaises(OSError):
                self.typed_turn(rid='legacy-receipt-write-fails')
        self.run_goal.assert_not_called()
        self.assertEqual(tuple((goal_executor.STORE / self.owner).glob(
            '*.execution.json',
        )), ())

    def test_cancelled_duplicate_waiter_does_not_resume_and_unrelated_id_progresses(self):
        """Two copies of a cancelled ID fail, while an independent ID completes."""
        rid = 'cancel-both-concurrent-copies'
        requests_state.register(self.owner, rid)
        first_entered = threading.Event()
        second_entered = threading.Event()
        release_first = threading.Event()
        calls = []
        original_try = canonical_goal_flow.try_create

        def observed(owner, request_id, text):
            if request_id == rid and first_entered.is_set():
                second_entered.set()
            return original_try(owner, request_id, text)

        def planned(prompt, **kwargs):
            calls.append(prompt)
            if prompt == 'Slow cancelled read':
                first_entered.set()
                self.assertTrue(release_first.wait(12))
                return json.dumps(research_tasks('cancelled'))
            return json.dumps(research_tasks('independent'))

        def cancelled_turn():
            with requests_state.activate(self.owner, rid):
                return canonical_goal_flow.try_create(self.owner, rid,
                                                      'Slow cancelled read')

        with patch.object(model_wait, 'ask', side_effect=planned), \
                patch.object(canonical_goal_flow, 'try_create', side_effect=observed):
            with ThreadPoolExecutor(max_workers=3) as pool:
                first = pool.submit(cancelled_turn)
                try:
                    self.assertTrue(first_entered.wait(10))
                    second = pool.submit(cancelled_turn)
                    self.assertTrue(second_entered.wait(10))
                    # The same-ID planner is still waiting. A distinct ID
                    # must be able to publish without acquiring its gate.
                    independent = pool.submit(canonical_goal_flow.try_create,
                                              self.owner, 'unrelated-during-cancel',
                                              'Independent read')
                    independent_job, _ = independent.result(timeout=8)
                    requests_state.cancel(self.owner, rid)
                finally:
                    release_first.set()
                for task in (first, second):
                    with self.assertRaises(requests_state.Cancelled):
                        task.result(timeout=20)
        self.assertEqual(self.persisted(independent_job)[1]['request'],
                         'Independent read')
        self.assertEqual(len(tuple((goal_executor.STORE / self.owner).glob(
            '*.goalstate.json',
        ))), 1)
        self.run_goal.assert_not_called()

    def test_missing_request_identity_never_starts_legacy(self):
        with patch.object(model_wait, 'ask') as planner:
            with self.assertRaises(ValueError):
                canonical_goal_flow.try_create(self.owner, '', 'Read a source')
        planner.assert_not_called()
        self.run_goal.assert_not_called()

    def test_request_id_collision_rejects_before_any_planner_call(self):
        with patch.object(model_wait, 'ask', return_value=json.dumps(research_tasks('first'))):
            rid, _, _, job_id = self.typed_turn()
        with patch.object(model_wait, 'ask',
                          side_effect=AssertionError('model called for an existing request')):
            with self.assertRaises(ValueError):
                canonical_goal_flow.try_create(
                    self.owner, rid, 'Different request under an existing ID',
                )
        self.assertEqual(self.persisted(job_id)[1]['request_id'], rid)

    def test_partial_publication_retry_fails_before_any_planner_call(self):
        rid = 'partial-publication-id'
        actual_atomic = canonical_goal_flow.release_guard.atomic

        def crash_before_record(path, content):
            if str(path).endswith('.execution.json'):
                raise OSError('simulated half-published journal')
            return actual_atomic(path, content)

        with patch.object(model_wait, 'ask', return_value=json.dumps(research_tasks('first'))), \
                patch.object(canonical_goal_flow.release_guard, 'atomic',
                             side_effect=crash_before_record):
            with self.assertRaises(OSError):
                canonical_goal_flow.try_create(self.owner, rid, 'Read two sources')
        with patch.object(model_wait, 'ask',
                          side_effect=AssertionError('model called after partial publication')):
            with self.assertRaises(ValueError):
                canonical_goal_flow.try_create(self.owner, rid, 'Read two sources')

    def _completed_with_unknown_delivery(self):
        with patch.object(model_wait, 'ask', return_value=json.dumps(research_tasks('first'))):
            _, _, _, job_id = self.typed_turn()
        offer = canonical_scheduler_dispatch.discover(self.owner)[0]

        def research_worker(owner, task, dependencies):
            return task_results.seal('research', {
                'state': 'done', 'text': 'Source-backed comparison',
                'source': 'https://example.test/article', 'source_chars': 200,
            })

        with patch.object(task_agents, 'worker', research_worker), \
                patch.object(untrusted_flow, 'observe', lambda *_: None):
            self.assertTrue(canonical_scheduler_dispatch.execute_offer(
                SimpleNamespace(slug=self.owner), offer,
            ))

        def uncertain_sink(owner, ident, content):
            state, record = self.persisted(ident)
            self.assertEqual(state['state'], 'done')
            self.assertEqual(record['_canonical_delivery'], 'reserved')
            self.assertEqual(record['_canonical_result_text'], content)
            self.assertEqual(record['_canonical_result_event_id'], 'canonical:' + ident)
            raise ConnectionError('UI status unknown after fanout')

        notified = Mock(side_effect=uncertain_sink)
        with patch.object(canonical_goal_flow, '_semantic_proposal',
                          return_value={'action': 'complete', 'goal': 0, 'evidence': ['first']}):
            self.assertFalse(canonical_goal_flow.complete_and_deliver(
                self.owner, job_id, notified,
            ))
        notified.assert_called_once()
        return job_id

    def test_reserved_result_stays_readable_without_model_worker_or_notification(self):
        job_id = self._completed_with_unknown_delivery()
        before = self.persisted(job_id)
        with patch.object(model_wait, 'ask',
                          side_effect=AssertionError('read must not call a model')):
            result = canonical_goal_flow.read_result_command(
                self.owner, 'hedef sonucu ' + job_id,
            )
        self.assertIn('Source-backed comparison', result)
        self.assertIn(job_id, result)
        self.assertEqual(before, self.persisted(job_id))
        notify = Mock()
        self.assertFalse(canonical_goal_flow.complete_and_deliver(self.owner, job_id, notify))
        notify.assert_not_called()

    def _accepted_canonical_research_for_crash_test(self):
        with patch.object(model_wait, 'ask',
                          return_value=json.dumps(research_tasks('first'))):
            _, _, _, job_id = self.typed_turn()
        offer = canonical_scheduler_dispatch.discover(self.owner)[0]

        def research_worker(owner, task, dependencies):
            return task_results.seal('research', {
                'state': 'done', 'text': 'Verified crash-safe source',
                'source': 'https://example.test/article', 'source_chars': 200,
            })

        with patch.object(task_agents, 'worker', research_worker), \
             patch.object(untrusted_flow, 'observe', lambda *_: None):
            self.assertTrue(canonical_scheduler_dispatch.execute_offer(
                SimpleNamespace(slug=self.owner), offer,
            ))
        return job_id

    def test_core_done_before_record_crash_preserves_owner_readable_result(self):
        """RED: final CAS succeeded; second-file crash must not erase result."""
        job_id = self._accepted_canonical_research_for_crash_test()
        root = goal_executor._owner_root(self.owner)
        state_path = root / (job_id + '.goalstate.json')
        original = canonical_goal_flow.release_guard.atomic

        def crash_on_final_journal(path, data):
            if (str(path).endswith('.execution.json')
                    and goal_state_store.load(state_path)['state'] == 'done'):
                raise OSError('simulated process death after Core terminal CAS')
            return original(path, data)

        sink = Mock(return_value={'ui': 'delivered'})
        with patch.object(canonical_goal_flow, '_semantic_proposal',
                          return_value={
                              'action': 'complete', 'goal': 0,
                              'evidence': ['first'],
                          }), patch.object(canonical_goal_flow.release_guard,
                                           'atomic', side_effect=crash_on_final_journal):
            with self.assertRaises(OSError):
                canonical_goal_flow.complete_and_deliver(self.owner, job_id, sink)
        sink.assert_not_called()
        state, journal = self.persisted(job_id)
        self.assertEqual(state['state'], 'done')
        self.assertEqual(journal['state'], 'running')
        # No model, worker, Core mutation or resend may occur during owner
        # result read; the pre-CAS frozen reply must be verifiable on disk.
        before = self.persisted(job_id)
        with patch.object(model_wait, 'ask',
                          side_effect=AssertionError('read triggered model')):
            result = canonical_goal_flow.read_completed_result(
                self.owner, job_id,
            )
        self.assertIn('Verified crash-safe source', result)
        self.assertEqual(self.persisted(job_id), before)
        self.assertFalse(canonical_goal_flow.complete_and_deliver(
            self.owner, job_id, sink,
        ))
        sink.assert_not_called()
        foreign = canonical_goal_flow.read_result_command(
            'not-this-owner', 'hedef sonucu ' + job_id,
        )
        self.assertNotIn('Verified crash-safe source', foreign)

        # A local modified frozen result must never pass just because the
        # terminal Core CAS and accepted predecessor outputs are genuine.
        forged = execution_record.load(root, self.owner, job_id)
        forged['_canonical_result_text'] = 'FORGED SECRET RESULT'
        original(execution_record.path_for(root, job_id),
                 execution_record.encode(forged))
        with self.assertRaises(ValueError):
            canonical_goal_flow.read_completed_result(self.owner, job_id)

    def test_pre_core_cas_crash_cannot_expose_uncompleted_result(self):
        """RED: pre-CAS prepared record is durable but never a completion."""
        job_id = self._accepted_canonical_research_for_crash_test()
        sink = Mock(return_value={'ui': 'delivered'})
        with patch.object(canonical_goal_flow, '_semantic_proposal',
                          return_value={
                              'action': 'complete', 'goal': 0,
                              'evidence': ['first'],
                          }), patch.object(
                              goal_state_compat, 'commit_verified_goal_completion',
                              side_effect=OSError('simulated pre-CAS crash')):
            with self.assertRaises(OSError):
                canonical_goal_flow.complete_and_deliver(self.owner, job_id, sink)
        state, journal = self.persisted(job_id)
        self.assertEqual(state['state'], 'pending')
        self.assertEqual(journal['state'], 'running')
        self.assertEqual(
            journal['_canonical_result_event_id'], 'canonical:' + job_id,
        )
        self.assertIn('Verified crash-safe source',
                      journal['_canonical_result_text'])
        with self.assertRaises(ValueError):
            canonical_goal_flow.read_completed_result(self.owner, job_id)
        sink.assert_not_called()

        # Re-evaluate completion with accepted outputs, never start or replay
        # any external worker. Only the semantic proposal runs again.
        with patch.object(canonical_goal_flow, '_semantic_proposal',
                          return_value={
                              'action': 'complete', 'goal': 0,
                              'evidence': ['first'],
                          }), patch.object(task_agents, 'worker',
                                           side_effect=AssertionError('worker replay')):
            self.assertTrue(canonical_goal_flow.complete_and_deliver(
                self.owner, job_id, sink,
            ))
        sink.assert_called_once()
        state, journal = self.persisted(job_id)
        self.assertEqual(state['state'], 'done')
        self.assertEqual(journal['_canonical_delivery'], 'delivered')

    def test_reserved_result_read_rejects_foreign_owner_and_tampered_output(self):
        job_id = self._completed_with_unknown_delivery()
        foreign = canonical_goal_flow.read_result_command(
            'another-owner', 'hedef sonucu ' + job_id,
        )
        self.assertNotIn('Source-backed comparison', foreign)
        self.assertIsNone(canonical_goal_flow.read_result_command(
            self.owner, 'araştırmanın sonucu nedir',
        ))
        root = goal_executor._owner_root(self.owner)
        altered = execution_record.load(root, self.owner, job_id)
        altered['outputs']['first']['text'] = 'Forged result should never be shown'
        canonical_goal_flow.release_guard.atomic(
            execution_record.path_for(root, job_id), execution_record.encode(altered),
        )
        with self.assertRaises(ValueError):
            canonical_goal_flow.read_completed_result(self.owner, job_id)
        response = canonical_goal_flow.read_result_command(
            self.owner, 'hedef sonucu ' + job_id,
        )
        self.assertNotIn('Forged result', response)

    def test_queued_result_query_never_claims_done_or_starts_model(self):
        with patch.object(model_wait, 'ask', return_value=json.dumps(research_tasks('first'))):
            _, _, _, job_id = self.typed_turn()
        with patch.object(model_wait, 'ask',
                          side_effect=AssertionError('pending query must not call model')):
            message = canonical_goal_flow.read_result_command(
                self.owner, 'hedef sonucu ' + job_id,
            )
        self.assertIn('henüz', message)
        self.assertEqual(self.persisted(job_id)[0]['state'], 'pending')

    def test_effectful_plan_keeps_existing_legacy_permission_path(self):
        writer = {'tasks': [{
            'id': 'write', 'agent': 'writer', 'depends': [],
            'input': {'instruction': 'Save report', 'filename': 'report.md'},
        }]}
        with patch.object(model_wait, 'ask', return_value=json.dumps(writer)):
            _, _, fb, job_id = self.typed_turn('Bir raporu dosyaya kaydet.')
        self.assertEqual(fb.reason_code, 'GOAL_CREATE')
        self.assertIsNone(job_id)
        self.run_goal.assert_called_once()
        self.assertEqual(tuple((goal_executor.STORE / self.owner).glob('*.execution.json')), ())
        self.assertEqual(tuple((goal_executor.STORE / self.owner).glob('*.goalstate.json')), ())

    def test_crashed_partial_publication_is_not_admitted_or_retried(self):
        actual_atomic = canonical_goal_flow.release_guard.atomic
        def fail_record_write(path, data):
            if str(path).endswith('.execution.json'):
                raise OSError('simulated crash between canonical and journal writes')
            return actual_atomic(path, data)
        with patch.object(model_wait, 'ask', return_value=json.dumps(research_tasks('first'))), \
                patch.object(canonical_goal_flow.release_guard, 'atomic',
                             side_effect=fail_record_write):
            with self.assertRaises(OSError):
                self.typed_turn()
        root = goal_executor._owner_root(self.owner)
        self.assertEqual(tuple(root.glob('*.execution.json')), ())
        self.assertEqual(len(tuple(root.glob('*.goalstate.json'))), 1)
        self.assertEqual(tuple(canonical_scheduler_dispatch.discover(self.owner)), ())

    def test_core_completion_adapter_rejects_missing_projected_proof(self):
        with patch.object(model_wait, 'ask', return_value=json.dumps(research_tasks('first'))):
            _, _, _, job_id = self.typed_turn()
        path = goal_executor._owner_root(self.owner) / (job_id + '.goalstate.json')
        with self.assertRaises(goal_state_compat.ReconcilePolicyError):
            goal_state_compat.commit_verified_goal_completion(
                path, owner=self.owner, job_id=job_id, proof=None,
            )
        self.assertEqual(self.persisted(job_id)[0]['state'], 'pending')

    def test_semantic_refusal_never_marks_completed_or_sends_result(self):
        with patch.object(model_wait, 'ask', return_value=json.dumps(research_tasks('first'))):
            _, _, _, job_id = self.typed_turn()
        with patch.object(canonical_plan_evidence, 'certify_projected_plan',
                          side_effect=canonical_plan_evidence.PlanEvidenceError('no complete proof')):
            notified = Mock(return_value={'ui': 'delivered'})
            self.assertFalse(canonical_goal_flow.complete_and_deliver(self.owner, job_id, notified))
        self.assertEqual(self.persisted(job_id)[0]['state'], 'pending')
        notified.assert_not_called()

    def test_real_scheduler_verifies_and_delivers_once_to_pinned_owner(self):
        with patch.object(model_wait, 'ask', return_value=json.dumps(research_tasks('first'))):
            _, _, _, job_id = self.typed_turn()
        stop = RapidStop()
        messages = []
        completed = threading.Event()
        callback_returned = threading.Event()
        callback_results = []
        def research_worker(owner, task, dependencies):
            self.assertEqual(owner, self.owner)
            self.assertEqual(dependencies, {})
            return task_results.seal('research', {
                'state': 'done', 'text': 'Source-backed comparison',
                'source': 'https://example.test/article', 'source_chars': 200,
            })
        def notify(owner, ident, text):
            messages.append((owner, ident, text))
            completed.set()
            return {'ui': 'delivered'}
        def finished(owner, ident):
            try:
                callback_results.append(canonical_goal_flow.complete_and_deliver(
                    owner, ident, notify,
                ))
            finally:
                # The sink's completed event fires BEFORE the durable
                # reserved -> delivered commit. Only the callback return
                # means that second write has finished (or failed).
                callback_returned.set()
        try:
            with ExitStack() as patches:
                for obj, attribute, value in (
                    (service_store, 'ROOT', Path(self.temp.name) / 'missing_sqlite'),
                    (task_queue, '_THREAD', None),
                    (task_queue, '_OWNER_TICKS', {}),
                    (task_queue, '_CANONICAL_WORKERS', {}),
                    (task_queue, '_LAST_ADMITTED', {}),
                    (task_queue, '_LAST_CANONICAL_ADMITTED', {}),
                    (task_queue, '_DAILY_NOTIFY', None),
                    (task_agents, 'worker', research_worker),
                    (untrusted_flow, 'observe', lambda *_: None),
                ):
                    patches.enter_context(patch.object(obj, attribute, value))
                patches.enter_context(patch.object(
                    model_wait, 'ask', return_value=json.dumps({
                        'action': 'complete', 'goal': 0, 'evidence': ['first'],
                    }),
                ))
                task_queue.start(
                    stop, allowed_owners=lambda: {self.owner},
                    canonical_profile_resolver=lambda owner: SimpleNamespace(slug=owner),
                    canonical_result_notify=finished,
                )
                self.assertTrue(completed.wait(25), 'Real Scheduler did not publish verified result')
                self.assertEqual(len(messages), 1)
                self.assertEqual(messages[0][0:2], (self.owner, job_id))
                self.assertIn('Source-backed comparison', messages[0][2])
                # Do not race the post-notify durable delivery write with a
                # fixed five-second disk-polling window. Wait for the actual
                # worker callback to return, then assert BOTH its success
                # and the persisted Core/journal evidence. This is stricter
                # than treating notify() as completion or sleeping longer.
                self.assertTrue(
                    callback_returned.wait(25),
                    'Canonical completion callback did not return after notification',
                )
                self.assertEqual(
                    callback_results, [True],
                    'Canonical completion callback returned without a durable delivery commit',
                )
                state, journal = self.persisted(job_id)
                self.assertEqual(state['state'], 'done')
                self.assertEqual(journal['_canonical_delivery'], 'delivered')
                self.assertEqual(journal['_canonical_result_event_id'], 'canonical:' + job_id)
                self.assertIn('Source-backed comparison', journal['_canonical_result_text'])
                self.assertIn('Source-backed comparison', canonical_goal_flow.read_completed_result(
                    self.owner, job_id,
                ))
                self.assertEqual(journal['goals'][0]['state'], 'done')
                self.assertFalse(canonical_goal_flow.complete_and_deliver(self.owner, job_id, notify))
                self.assertEqual(len(messages), 1)
                self.run_goal.assert_not_called()
        finally:
            stop.set()
            if task_queue._THREAD is not None:
                task_queue._THREAD.join(10)
            for worker in tuple(task_queue._CANONICAL_WORKERS.values()):
                worker.join(10)


    def test_scheduler_restart_resumes_verified_completion_without_worker_replay(self):
        # A process may die after the last accepted output projection but
        # before its one-shot completion callback. No worker may be repeated.
        with patch.object(model_wait, 'ask',
                          return_value=json.dumps(research_tasks('first'))):
            _, _, _, job_id = self.typed_turn()
        offer = canonical_scheduler_dispatch.discover(self.owner)[0]
        def research_worker(owner, task, dependencies):
            return task_results.seal('research', {
                'state': 'done', 'text': 'Durably projected result',
                'source': 'https://example.test/article', 'source_chars': 200,
            })
        with patch.object(task_agents, 'worker', research_worker), \
             patch.object(untrusted_flow, 'observe', lambda *_: None):
            self.assertTrue(canonical_scheduler_dispatch.execute_offer(
                SimpleNamespace(slug=self.owner), offer,
            ))
        before_state, before_journal = self.persisted(job_id)
        self.assertEqual(before_state['state'], 'pending')
        self.assertEqual(before_journal['outputs']['first']['state'], 'done')
        self.assertFalse(before_journal.get('_canonical_delivery'))

        offers = canonical_scheduler_dispatch.recoverable_completions(self.owner)
        self.assertEqual([row.job_id for row in offers], [job_id])
        stop = RapidStop()
        sent = []
        completed = threading.Event()
        def sink(owner, ident, text):
            sent.append((owner, ident, text))
            completed.set()
            return {'ui': 'delivered'}
        def finished(owner, ident):
            canonical_goal_flow.complete_and_deliver(owner, ident, sink)

        try:
            with ExitStack() as patches:
                for obj, attribute, value in (
                    (service_store, 'ROOT', Path(self.temp.name) / 'missing_sqlite'),
                    (task_queue, '_THREAD', None),
                    (task_queue, '_OWNER_TICKS', {}),
                    (task_queue, '_CANONICAL_WORKERS', {}),
                    (task_queue, '_CANONICAL_RESUME_ATTEMPTED', set()),
                    (task_queue, '_LAST_ADMITTED', {}),
                    (task_queue, '_LAST_CANONICAL_ADMITTED', {}),
                    (task_queue, '_DAILY_NOTIFY', None),
                ):
                    patches.enter_context(patch.object(obj, attribute, value))
                patches.enter_context(patch.object(
                    model_wait, 'ask', return_value=json.dumps({
                        'action': 'complete', 'goal': 0, 'evidence': ['first'],
                    }),
                ))
                # Stop and join while all temporary Scheduler registries
                # are STILL patched. Otherwise ExitStack restores _THREAD
                # and _CANONICAL_WORKERS before the outer finally runs,
                # losing the live recovery thread and leaving a Windows
                # .control.lock file open during TemporaryDirectory cleanup.
                def close_patched_scheduler():
                    stop.set()
                    scheduler = task_queue._THREAD
                    if scheduler is not None:
                        scheduler.join(10)
                        self.assertFalse(scheduler.is_alive(),
                                         'Recovery Scheduler thread still alive')
                    for live in tuple(task_queue._CANONICAL_WORKERS.values()):
                        live.join(10)
                        self.assertFalse(live.is_alive(),
                                         'Recovery worker still owns a Windows file lock')
                patches.callback(close_patched_scheduler)
                with patch.object(task_agents, 'worker',
                                  side_effect=AssertionError('worker replay')) as worker:
                    task_queue.start(
                        stop, allowed_owners=lambda: {self.owner},
                        canonical_profile_resolver=lambda owner: SimpleNamespace(slug=owner),
                        canonical_result_notify=finished,
                    )
                    self.assertTrue(completed.wait(25), 'Recovery callback never ran')
                    worker.assert_not_called()
                    # The sink can be called before delivery marker persistence.
                    until = time.monotonic() + 6
                    while time.monotonic() < until:
                        state, record = self.persisted(job_id)
                        if record.get('_canonical_delivery') == 'delivered':
                            break
                        time.sleep(.025)
                    state, record = self.persisted(job_id)
                    self.assertEqual(state['state'], 'done')
                    self.assertEqual(record['_canonical_delivery'], 'delivered')
                    self.assertEqual(len(sent), 1)
                    self.assertEqual(sent[0][:2], (self.owner, job_id))
                    self.assertIn('Durably projected result', sent[0][2])
                    self.assertEqual(canonical_scheduler_dispatch.recoverable_completions(
                        self.owner,
                    ), ())
        finally:
            # Backstop for an exception before installing the ExitStack
            # callback; the callback itself joins under pinned mocks.
            stop.set()

    def test_canonical_gmail_deadline_stops_second_provider_request(self):
        """Real canonical account specialist: one expired remote list read
        must not start the next Gmail metadata request or mint Core success.
        """
        from modules import google_api, llm, runtime_worker_result
        tasks = {'tasks': [
            {'id': 'unread', 'agent': 'account', 'depends': [],
             'input': {'service': 'gmail', 'operation': 'list_unread', 'limit': 5}},
        ]}
        with patch.object(model_wait, 'ask', return_value=json.dumps(tasks)):
            _, _, feedback, job_id = self.typed_turn(
                'Beş okunmamış e-postanın başlığını getir.',
            )
        self.assertEqual(feedback.reason_code, 'GOAL_CANONICAL_BACKGROUND_QUEUED')
        clock = [10.0]
        deadline = runtime_worker_result.CanonicalWorkerDeadline(
            threading.Event(), 2, clock=lambda: clock[0],
        )
        calls = []

        def completed_list():
            calls.append('list')
            # Simulate a provider response that arrived only after the
            # canonical worker deadline; actual Gmail is never contacted.
            clock[0] = 12.0
            return {'messages': [{'id': 'mail001'}]}

        class Messages:
            def list(self, **_kwargs):
                return SimpleNamespace(execute=completed_list)

            def get(self, **_kwargs):
                calls.append('metadata')
                raise AssertionError('Expired worker started second Gmail call')

        messages = Messages()
        fake_service = SimpleNamespace(
            users=lambda: SimpleNamespace(messages=lambda: messages),
        )
        offer = canonical_scheduler_dispatch.discover(self.owner)[0]
        owner_token = llm._key_context.set(self.owner)
        try:
            with patch.object(google_api, '_service', return_value=fake_service), \
                 patch.object(untrusted_flow, 'observe', lambda *_: None):
                with self.assertRaises(
                    runtime_worker_result.CanonicalWorkerDeadlineExceeded,
                ):
                    canonical_scheduler_dispatch.execute_offer(
                        SimpleNamespace(slug=self.owner), offer,
                        stop_event=deadline,
                    )
        finally:
            llm._key_context.reset(owner_token)
        self.assertEqual(calls, ['list'])
        state, journal = self.persisted(job_id)
        self.assertFalse(any(
            row.get('kind') == 'worker_result'
            and row.get('status') == 'succeeded'
            for row in state['evidence']
        ))
        self.assertEqual(journal['steps'][0]['state'], 'failed')
        self.assertEqual(
            journal['outputs']['unread'].get('reason_code'),
            'CANONICAL_WORKER_DEADLINE_UNACCEPTED',
        )
        # Failed first attempt is terminal without user-controlled
        # reconciliation; the live Scheduler may not replay a provider.
        self.assertEqual(canonical_scheduler_dispatch.discover(self.owner), ())

    def test_canonical_gmail_indexed_read_waits_for_accepted_list(self):
        """Typed request -> Core plan -> real specialist/leases/CAS -> delivery.

        Only external account provider is mocked; no actual Gmail request
        or real user's mail data is accessed.
        """
        tasks = {'tasks': [
            {'id': 'unread', 'agent': 'account', 'depends': [],
             'input': {'service': 'gmail', 'operation': 'list_unread', 'limit': 5}},
            {'id': 'read', 'agent': 'account', 'depends': ['unread'],
             'input': {'service': 'gmail', 'operation': 'read_message', 'index': 1}},
        ]}
        with patch.object(model_wait, 'ask', return_value=json.dumps(tasks)):
            _, reply, feedback, job_id = self.typed_turn(
                'Okunmamış e-postalarımı listele ve ilkini oku.',
            )
        self.assertEqual(feedback.reason_code, 'GOAL_CANONICAL_BACKGROUND_QUEUED')
        self.assertIn(job_id, reply)
        self.assertEqual([o.selection.node_id for o in
                          canonical_scheduler_dispatch.discover(self.owner)], ['unread'])
        observed = []
        def account_worker(owner, task, deps):
            self.assertEqual(owner, self.owner)
            observed.append((task['id'], tuple(deps)))
            if task['id'] == 'unread':
                self.assertEqual(deps, {})
                snapshot = {
                    'owner': owner, 'service': 'gmail', 'operation': 'list_unread',
                    'limit': 5, 'items': [{
                        'id': 'msg_123', 'from': 'sender@example.test',
                        'subject': 'Verified mail subject',
                    }],
                    'fetched_at': time.time(), 'query': 'is:unread in:inbox',
                    'has_more': False,
                }
            else:
                self.assertEqual(task['id'], 'read')
                self.assertEqual(task['input']['index'], 1)
                self.assertEqual(set(deps), {'unread'})
                self.assertTrue(task_results.verify(deps['unread'], owner=owner))
                self.assertEqual(deps['unread']['snapshot']['items'][0]['id'],
                                 'msg_123')
                snapshot = {
                    'owner': owner, 'service': 'gmail', 'operation': 'read_message',
                    'fetched_at': time.time(),
                    'message': {
                        'id': 'msg_123', 'from': 'sender@example.test',
                        'subject': 'Verified mail subject', 'body': 'Evidence-backed text',
                        'truncated': False, 'format': 'plain',
                    },
                }
            return task_results.seal('account', {
                'state': 'done',
                'text': account_tools.render_snapshot(snapshot),
                'snapshot': snapshot, 'sha256': account_tools.digest(snapshot),
            })
        with patch.object(task_agents, 'worker', side_effect=account_worker), \
             patch.object(untrusted_flow, 'observe', lambda *_: None):
            first = canonical_scheduler_dispatch.discover(self.owner)
            self.assertEqual([o.selection.node_id for o in first], ['unread'])
            self.assertTrue(canonical_scheduler_dispatch.execute_offer(
                SimpleNamespace(slug=self.owner), first[0],
            ))
            state, journal = self.persisted(job_id)
            self.assertEqual(journal['outputs']['unread']['state'], 'done')
            # A substituted Gmail list is not usable even when the enclosing
            # journal still says "done"; Core committed the previous bytes.
            record_path = execution_record.path_for(
                goal_executor._owner_root(self.owner), job_id,
            )
            original_bytes = record_path.read_bytes()
            forged = execution_record.load(
                goal_executor._owner_root(self.owner), self.owner, job_id,
            )
            forged['outputs']['unread']['snapshot']['items'][0]['id'] = 'forged_mail'
            release_guard.atomic(record_path, execution_record.encode(forged))
            self.assertEqual(canonical_scheduler_dispatch.discover(self.owner), ())
            release_guard.atomic(record_path, original_bytes)
            self.assertEqual([o.selection.node_id for o in
                              canonical_scheduler_dispatch.discover(self.owner)], ['read'])
            child = canonical_scheduler_dispatch.discover(self.owner)[0]
            self.assertTrue(canonical_scheduler_dispatch.execute_offer(
                SimpleNamespace(slug=self.owner), child,
            ))
        self.assertEqual(observed, [('unread', ()), ('read', ('unread',))])
        state, journal = self.persisted(job_id)
        self.assertEqual(set(journal['outputs']), {'unread', 'read'})
        self.assertTrue(all(s['state'] == 'done' for s in journal['steps']))
        accepted = [r['step_id'] for r in state['evidence']
                    if r.get('kind') == 'worker_result' and r.get('status') == 'succeeded']
        self.assertEqual(accepted, ['unread', 'read'])
        notified = Mock(return_value={'ui': 'delivered'})
        with patch.object(canonical_goal_flow, '_semantic_proposal', return_value={
            'action': 'complete', 'goal': 0, 'evidence': ['unread', 'read'],
        }):
            self.assertTrue(canonical_goal_flow.complete_and_deliver(
                self.owner, job_id, notified,
            ))
        notified.assert_called_once()
        self.assertEqual(self.persisted(job_id)[0]['state'], 'done')
        self.run_goal.assert_not_called()

    def test_canonical_gmail_child_survives_unrelated_research_root_cas(self):
        """Real typed Brain→Core→specialist root/child overlap and delivery.

        A Gmail indexed read starts after its accepted list, but before a
        separate research root finishes. That root's verified Core CAS must
        not discard the ongoing child's independent, still-leased read result.
        Provider calls are mocked, not proof of a connected Gmail account.
        """
        tasks = {'tasks': [
            {'id': 'unread', 'agent': 'account', 'depends': [],
             'input': {'service': 'gmail', 'operation': 'list_unread', 'limit': 5}},
            {'id': 'research', 'agent': 'research', 'depends': [],
             'input': {'url': 'https://example.test/article', 'question': 'compare'}},
            {'id': 'read', 'agent': 'account', 'depends': ['unread'],
             'input': {'service': 'gmail', 'operation': 'read_message', 'index': 1}},
        ]}
        with patch.object(model_wait, 'ask', return_value=json.dumps(tasks)):
            _, _, feedback, job_id = self.typed_turn(
                'İlk okunmamış e-postamı oku ve bağımsız kaynağı araştır.',
            )
        self.assertEqual(feedback.reason_code, 'GOAL_CANONICAL_BACKGROUND_QUEUED')
        research_started, research_release = threading.Event(), threading.Event()
        read_started, read_release = threading.Event(), threading.Event()
        errors, finished, threads = [], {}, []

        def safe_worker(owner, task, dependencies):
            self.assertEqual(owner, self.owner)
            node_id = task['id']
            if node_id == 'research':
                research_started.set()
                self.assertTrue(research_release.wait(12), 'Research worker held')
                return task_results.seal('research', {
                    'state': 'done', 'text': 'Independent source verified',
                    'source': 'https://example.test/article',
                    'source_chars': 200,
                })
            if node_id == 'unread':
                self.assertEqual(dependencies, {})
                snapshot = {
                    'owner': owner, 'service': 'gmail', 'operation': 'list_unread',
                    'limit': 5, 'items': [
                        {'id': 'mail_1', 'from': 'sender@example.test',
                         'subject': 'First message'},
                    ],
                    'fetched_at': time.time(), 'query': 'is:unread in:inbox',
                    'has_more': False,
                }
            else:
                self.assertEqual(node_id, 'read')
                self.assertEqual(set(dependencies), {'unread'})
                self.assertTrue(task_results.verify(
                    dependencies['unread'], owner=owner,
                ))
                self.assertEqual(
                    dependencies['unread']['snapshot']['items'][0]['id'],
                    'mail_1',
                )
                read_started.set()
                self.assertTrue(read_release.wait(12), 'Gmail read held')
                snapshot = {
                    'owner': owner, 'service': 'gmail', 'operation': 'read_message',
                    'fetched_at': time.time(), 'message': {
                        'id': 'mail_1', 'from': 'sender@example.test',
                        'subject': 'First message', 'body': 'Verified mail body',
                        'truncated': False, 'format': 'plain',
                    },
                }
            return task_results.seal('account', {
                'state': 'done',
                'text': account_tools.render_snapshot(snapshot),
                'snapshot': snapshot, 'sha256': account_tools.digest(snapshot),
            })

        def dispatch(offer):
            try:
                finished[offer.selection.node_id] = (
                    canonical_scheduler_dispatch.execute_offer(
                        SimpleNamespace(slug=self.owner), offer,
                    )
                )
            except Exception as exc:
                errors.append(exc)

        with patch.object(task_agents, 'worker', side_effect=safe_worker), \
             patch.object(untrusted_flow, 'observe', lambda *_: None):
            try:
                # Start from the real published canonical journal, not a
                # synthetic accepted parent result.
                unread = next(x for x in
                              canonical_scheduler_dispatch.discover(self.owner)
                              if x.selection.node_id == 'unread')
                self.assertTrue(canonical_scheduler_dispatch.execute_offer(
                    SimpleNamespace(slug=self.owner), unread,
                ))
                # Independent research begins and remains in flight.
                research = next(x for x in
                                canonical_scheduler_dispatch.discover(self.owner)
                                if x.selection.node_id == 'research')
                first = threading.Thread(target=dispatch, args=(research,))
                threads.append(first)
                first.start()
                self.assertTrue(research_started.wait(10))
                # Now the Gmail child starts on Core-accepted list proof.
                child = next(x for x in
                             canonical_scheduler_dispatch.discover(self.owner)
                             if x.selection.node_id == 'read')
                second = threading.Thread(target=dispatch, args=(child,))
                threads.append(second)
                second.start()
                self.assertTrue(read_started.wait(10))
                # Research wins a separate Core CAS while Gmail is still
                # reading; the child's expected version is now stale.
                research_release.set()
                first.join(12)
                self.assertFalse(first.is_alive())
                self.assertEqual(finished.get('research'), True, repr(errors))
                state, record = self.persisted(job_id)
                self.assertEqual(record['outputs']['research']['state'], 'done')
                self.assertNotIn('read', record['outputs'])
                read_release.set()
                second.join(12)
                self.assertFalse(second.is_alive())
                self.assertFalse(errors, repr(errors))
                self.assertEqual(finished.get('read'), True, repr(errors))
            finally:
                research_release.set()
                read_release.set()
                for thread in threads:
                    thread.join(12)
                    self.assertFalse(thread.is_alive(),
                                     'A worker still owns its test file lock')

        state, record = self.persisted(job_id)
        self.assertEqual(set(record['outputs']), {'unread', 'research', 'read'})
        self.assertEqual(
            {row['step_id'] for row in state['evidence']
             if row.get('kind') == 'worker_result'
             and row.get('status') == 'succeeded'},
            {'unread', 'research', 'read'},
        )
        self.assertTrue(all(row['state'] == 'done' for row in record['steps']))
        received = Mock(return_value={'ui': 'delivered'})
        with patch.object(canonical_goal_flow, '_semantic_proposal', return_value={
            'action': 'complete', 'goal': 0,
            'evidence': ['unread', 'research', 'read'],
        }):
            self.assertTrue(canonical_goal_flow.complete_and_deliver(
                self.owner, job_id, received,
            ))
        received.assert_called_once()
        self.assertEqual(self.persisted(job_id)[0]['state'], 'done')
        self.run_goal.assert_not_called()

    def test_real_scheduler_gmail_child_completes_before_running_research_root(self):
        """Production Scheduler: root research + Gmail list overlap, Gmail
        child commits first, then late independent research must be accepted.

        This is a real pinned Scheduler thread/lease/Core/delivery integration
        test with synthetic provider/model outputs, not a live Gmail test.
        """
        tasks = {'tasks': [
            {'id': 'research', 'agent': 'research', 'depends': [],
             'input': {'url': 'https://example.test/article',
                       'question': 'compare'}},
            {'id': 'unread', 'agent': 'account', 'depends': [],
             'input': {'service': 'gmail', 'operation': 'list_unread',
                       'limit': 5}},
            {'id': 'read', 'agent': 'account', 'depends': ['unread'],
             'input': {'service': 'gmail', 'operation': 'read_message',
                       'index': 1}},
        ]}
        with patch.object(model_wait, 'ask', return_value=json.dumps(tasks)):
            _, _, feedback, job_id = self.typed_turn(
                'Araştır ve okunmamış ilk Gmail mesajını oku.',
            )
        self.assertEqual(feedback.reason_code, 'GOAL_CANONICAL_BACKGROUND_QUEUED')
        research_entered, research_release = threading.Event(), threading.Event()
        read_entered, delivered = threading.Event(), threading.Event()
        observed = []
        errors = []
        callback_attempts = []
        sink_calls = []
        lock = threading.Lock()
        stop = RapidStop()

        def worker(owner, task, dependencies):
            self.assertEqual(owner, self.owner)
            name = task['id']
            with lock:
                observed.append((name, tuple(sorted(dependencies))))
            if name == 'research':
                research_entered.set()
                self.assertTrue(research_release.wait(45),
                                'Research provider never released')
                return task_results.seal('research', {
                    'state': 'done', 'text': 'Research completed after Gmail child',
                    'source': 'https://example.test/article', 'source_chars': 200,
                })
            if name == 'unread':
                self.assertEqual(dependencies, {})
                snapshot = {
                    'owner': owner, 'service': 'gmail', 'operation': 'list_unread',
                    'limit': 5,
                    'items': [{'id': 'mail-001', 'from': 'source@example.test',
                               'subject': 'Original subject'}],
                    'query': 'is:unread in:inbox', 'fetched_at': time.time(),
                    'has_more': False,
                }
            else:
                self.assertEqual(name, 'read')
                self.assertEqual(set(dependencies), {'unread'})
                self.assertTrue(task_results.verify(dependencies['unread'], owner=owner))
                self.assertEqual(
                    dependencies['unread']['snapshot']['items'][0]['id'],
                    'mail-001',
                )
                read_entered.set()
                snapshot = {
                    'owner': owner, 'service': 'gmail', 'operation': 'read_message',
                    'fetched_at': time.time(),
                    'message': {
                        'id': 'mail-001', 'from': 'source@example.test',
                        'subject': 'Original subject', 'body': 'Verified Gmail contents',
                        'truncated': False, 'format': 'plain',
                    },
                }
            return task_results.seal('account', {
                'state': 'done',
                'text': account_tools.render_snapshot(snapshot),
                'snapshot': snapshot, 'sha256': account_tools.digest(snapshot),
            })

        def sink(owner, ident, text):
            with lock:
                sink_calls.append((owner, ident, text))
            delivered.set()
            return {'ui': 'delivered'}

        def complete(owner, ident):
            try:
                result = canonical_goal_flow.complete_and_deliver(owner, ident, sink)
                with lock:
                    callback_attempts.append((ident, result))
                return result
            except Exception as exc:
                with lock:
                    errors.append(repr(exc))
                raise

        with ExitStack() as patches:
            for obj, attribute, value in (
                (service_store, 'ROOT', Path(self.temp.name) / 'missing_sqlite'),
                (task_queue, '_THREAD', None),
                (task_queue, '_OWNER_TICKS', {}),
                (task_queue, '_CANONICAL_WORKERS', {}),
                (task_queue, '_CANONICAL_RESUME_ATTEMPTED', set()),
                (task_queue, '_LAST_ADMITTED', {}),
                (task_queue, '_LAST_CANONICAL_ADMITTED', {}),
                (task_queue, '_DAILY_NOTIFY', None),
                (task_agents, 'worker', worker),
                (untrusted_flow, 'observe', lambda *_: None),
            ):
                patches.enter_context(patch.object(obj, attribute, value))
            patches.enter_context(patch.object(
                model_wait, 'ask', return_value=json.dumps({
                    'action': 'complete', 'goal': 0,
                    'evidence': ['research', 'unread', 'read'],
                }),
            ))
            # Register cleanup LAST: join live threads while pinned registries
            # and provider mocks are still installed, before Windows temp
            # owner/job *.control.lock files are removed.
            def close_scheduler():
                research_release.set()
                stop.set()
                scheduler = task_queue._THREAD
                if scheduler is not None:
                    scheduler.join(12)
                    self.assertFalse(scheduler.is_alive())
                for active in tuple(task_queue._CANONICAL_WORKERS.values()):
                    active.join(12)
                    self.assertFalse(active.is_alive(),
                                     'Worker leaked a test owner-file lock')
            patches.callback(close_scheduler)
            task_queue.start(
                stop, allowed_owners=lambda: {self.owner},
                canonical_profile_resolver=lambda owner: SimpleNamespace(slug=owner),
                canonical_result_notify=complete,
            )
            self.assertTrue(research_entered.wait(15),
                            'Independent research root never started')
            self.assertTrue(read_entered.wait(20),
                            'Gmail child never started after verified unread list')
            # The Gmail child may only start after its exact accepted list;
            # it must be able to finish independently while research is held.
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                state, journal = self.persisted(job_id)
                if journal['outputs'].get('read', {}).get('state') == 'done':
                    break
                time.sleep(.025)
            self.assertEqual(journal['outputs'].get('read', {}).get('state'), 'done')
            self.assertNotIn('research', journal['outputs'])
            self.assertEqual(state['state'], 'pending')
            self.assertFalse(delivered.is_set(),
                             'Global completion ran before every root was accepted')
            research_release.set()
            if not delivered.wait(25):
                # The real-PC watcher publishes only a bounded unittest tail,
                # not the live Scheduler's swallowed exception details. Keep
                # this diagnostic strictly to synthetic test data and IDs:
                # distinguish worker Core CAS rejection, missing projection,
                # completion-proof rejection, and an uncalled callback. Never
                # call complete_and_deliver() again to mask lost delivery.
                state, journal = self.persisted(job_id)
                try:
                    proof = canonical_plan_evidence.certify_projected_plan(
                        self.owner, job_id,
                    )
                    proof_state = 'projected:' + str(proof.goal_version)
                except Exception as exc:
                    proof_state = type(exc).__name__ + ':' + str(exc)[:220]
                with lock:
                    seen = list(observed)
                    completed_callbacks = list(callback_attempts)
                    callbacks_errors = list(errors)
                self.fail('Late research/delivery stalled: ' + repr({
                    'core_version': state['version'],
                    'core_state': state['state'],
                    'core_evidence': [
                        (x.get('step_id'), x.get('status'), x.get('attempt'))
                        for x in state.get('evidence', [])
                        if isinstance(x, dict) and x.get('kind') == 'worker_result'
                    ],
                    'core_audit': [
                        (x.get('op'), x.get('reason_code'))
                        for x in state.get('audit', [])[-5:]
                    ],
                    'journal_steps': [
                        (x.get('id'), x.get('state'), x.get('reason_code'))
                        for x in journal.get('steps', [])
                    ],
                    'projected_outputs': sorted(journal.get('outputs', {})),
                    'delivery_marker': journal.get('_canonical_delivery'),
                    'completion_proof': proof_state,
                    'observed_workers': seen,
                    'completion_callbacks': completed_callbacks,
                    'completion_exceptions': callbacks_errors,
                    'live_workers': [
                        (key[2], thread.is_alive())
                        for key, thread in tuple(task_queue._CANONICAL_WORKERS.items())
                        if key[1] == job_id
                    ],
                }))
            # Delivery notification may precede the durable delivered marker.
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                state, journal = self.persisted(job_id)
                if journal.get('_canonical_delivery') == 'delivered':
                    break
                time.sleep(.025)
            self.assertEqual(state['state'], 'done')
            self.assertEqual(journal.get('_canonical_delivery'), 'delivered')
            self.assertEqual(set(journal['outputs']), {'research', 'unread', 'read'})
            self.assertTrue(all(step['state'] == 'done' for step in journal['steps']))
            self.assertEqual(
                {row['step_id'] for row in state['evidence']
                 if row.get('kind') == 'worker_result'
                 and row.get('status') == 'succeeded'},
                {'research', 'unread', 'read'},
            )
            self.assertEqual(len(sink_calls), 1)
            self.assertEqual(sink_calls[0][:2], (self.owner, job_id))
            self.assertIn('Verified Gmail contents', sink_calls[0][2])
            self.assertFalse(errors, repr(errors))
            self.assertEqual(set(name for name, _ in observed),
                             {'research', 'unread', 'read'})
            self.assertEqual(next(deps for name, deps in observed if name == 'read'),
                             ('unread',))
            self.run_goal.assert_not_called()

    def test_canonical_gmail_indexed_read_rejects_unverified_or_wrong_parent(self):
        valid = [
            {'id': 'unread', 'agent': 'account', 'depends': [],
             'input': {'service': 'gmail', 'operation': 'list_unread', 'limit': 5}},
            {'id': 'read', 'agent': 'account', 'depends': ['unread'],
             'input': {'service': 'gmail', 'operation': 'read_message', 'index': 1}},
        ]
        # An account chain cannot read by index from a foreign or missing list.
        for changed in (
            [{'id': 'unread', 'agent': 'account', 'depends': [],
              'input': {'service': 'drive', 'operation': 'list_files'}}, valid[1]],
            [valid[0], {**valid[1], 'input': {
                'service': 'gmail', 'operation': 'read_message',
                'message_id': 'invented',
            }}],
            [valid[0], {**valid[1], 'depends': []}],
        ):
            with self.assertRaises(ValueError):
                canonical_goal_flow._canonical_plan(changed)
        self.assertEqual(canonical_goal_flow._canonical_plan(valid)['nodes'][1]['depends_on'],
                         ['unread'])


    def test_foreground_accepts_second_independent_goal_while_worker_is_running(self):
        entered = threading.Event()
        release = threading.Event()
        stop = RapidStop()
        def research_worker(owner, task, dependencies):
            entered.set()
            self.assertTrue(release.wait(20), 'Provider gate never released')
            return task_results.seal('research', {
                'state': 'done', 'text': 'Verified ' + task['id'],
                'source': 'https://example.test/article', 'source_chars': 200,
            })
        with ExitStack() as patches:
            for obj, attribute, value in (
                (service_store, 'ROOT', Path(self.temp.name) / 'missing_sqlite'),
                (task_queue, '_THREAD', None),
                (task_queue, '_OWNER_TICKS', {}),
                (task_queue, '_CANONICAL_WORKERS', {}),
                (task_queue, '_LAST_ADMITTED', {}),
                (task_queue, '_LAST_CANONICAL_ADMITTED', {}),
                (task_queue, '_DAILY_NOTIFY', None),
                (task_agents, 'worker', research_worker),
                (untrusted_flow, 'observe', lambda *_: None),
            ):
                patches.enter_context(patch.object(obj, attribute, value))
            patches.enter_context(patch.object(
                model_wait, 'ask', side_effect=[
                    json.dumps(research_tasks('first')),
                    json.dumps(research_tasks('second')),
                ],
            ))
            _, _, _, first = self.typed_turn('Birinci kaynağı araştır.')
            task_queue.start(
                stop, allowed_owners=lambda: {self.owner},
                canonical_profile_resolver=lambda owner: SimpleNamespace(slug=owner),
            )
            try:
                self.assertTrue(entered.wait(15), 'First canonical provider did not start')
                started = time.monotonic()
                _, _, feedback, second = self.typed_turn('İkinci bağımsız kaynağı araştır.')
                self.assertLess(time.monotonic() - started, 8)
                self.assertNotEqual(first, second)
                self.assertEqual(feedback.reason_code, 'GOAL_CANONICAL_BACKGROUND_QUEUED')
                self.assertEqual(self.persisted(second)[0]['state'], 'pending')
                self.run_goal.assert_not_called()
            finally:
                release.set()
                stop.set()
                if task_queue._THREAD is not None:
                    task_queue._THREAD.join(10)
                for worker in tuple(task_queue._CANONICAL_WORKERS.values()):
                    worker.join(10)

    def test_unrelated_owner_cannot_observe_foreign_result(self):
        with patch.object(model_wait, 'ask', return_value=json.dumps(research_tasks('private'))):
            foreign, _ = canonical_goal_flow.try_create(
                'another-owner', 'other-request', 'Read a private source',
            )
        notify = Mock()
        self.assertFalse(canonical_goal_flow.complete_and_deliver(self.owner, foreign, notify))
        notify.assert_not_called()
        self.assertEqual(
            execution_record.load(goal_executor._owner_root('another-owner'),
                                  'another-owner', foreign)['owner'],
            'another-owner',
        )


    def test_all_workers_done_still_requires_semantic_core_completion(self):
        with patch.object(model_wait, 'ask', return_value=json.dumps(research_tasks('first'))):
            _, _, _, job_id = self.typed_turn()
        offer = canonical_scheduler_dispatch.discover(self.owner)[0]
        def worker(owner, task, dependencies):
            return task_results.seal('research', {
                'state': 'done', 'text': 'An incomplete research answer',
                'source': 'https://example.test/article', 'source_chars': 200,
            })
        with patch.object(task_agents, 'worker', worker), \
                patch.object(untrusted_flow, 'observe', lambda *_: None):
            self.assertTrue(canonical_scheduler_dispatch.execute_offer(
                SimpleNamespace(slug=self.owner), offer,
            ))
        proof = canonical_plan_evidence.certify_projected_plan(self.owner, job_id)
        self.assertEqual(proof.job_id, job_id)
        notified = Mock(return_value={'ui': 'delivered'})
        with patch.object(canonical_goal_flow, '_semantic_proposal',
                          return_value={'action': 'ask', 'question': 'Not enough evidence'}):
            self.assertFalse(canonical_goal_flow.complete_and_deliver(
                self.owner, job_id, notified,
            ))
        state, journal = self.persisted(job_id)
        self.assertEqual(state['state'], 'pending')
        self.assertEqual(journal['state'], 'running')
        notified.assert_not_called()

    def test_owner_question_answer_rechecks_same_dag_without_worker_replay(self):
        job_id = self._accepted_canonical_research_for_crash_test()
        notified = Mock(return_value={'ui': 'delivered'})
        question = 'Hangi karşılaştırmayı istiyorsun?'
        with patch.object(canonical_goal_flow, '_semantic_proposal',
                          return_value={'action': 'ask', 'question': question}):
            self.assertFalse(canonical_goal_flow.complete_and_deliver(
                self.owner, job_id, notified,
            ))
        state, journal = self.persisted(job_id)
        self.assertEqual(state['state'], 'pending')
        self.assertEqual(journal['state'], 'running')
        dialog = journal['_canonical_dialog']
        self.assertEqual(dialog['state'], 'waiting')
        self.assertEqual(dialog['delivery'], 'ui_accepted')
        self.assertEqual(dialog['round'], 1)
        self.assertEqual(notified.call_count, 1)
        self.assertIn('hedef cevap ' + job_id, notified.call_args.args[2])
        self.assertIn(question, goal_executor.status_summary(journal))
        self.assertEqual(canonical_scheduler_dispatch.recoverable_completions(
            self.owner,
        ), ())
        with self.assertRaises(ValueError):
            canonical_goal_flow.delivery_metadata(self.owner, job_id)
        before = self.persisted(job_id)
        self.assertIn('açıklama kabul etmiyor',
                      canonical_goal_flow.read_result_command(
                          'other-owner', 'hedef cevap ' + job_id + ' yanlış',
                      ))
        self.assertEqual(before, self.persisted(job_id))
        answer = canonical_goal_flow.read_result_command(
            self.owner, 'hedef cevap ' + job_id + ' Tarihleri karşılaştır',
        )
        self.assertIn('Yanıt bu hedefe kaydedildi', answer)
        self.assertIn('açıklama kabul etmiyor',
                      canonical_goal_flow.read_result_command(
                          self.owner, 'hedef cevap ' + job_id + ' bir daha',
                      ))
        self.assertEqual([x.job_id for x in
                          canonical_scheduler_dispatch.recoverable_completions(
                              self.owner)], [job_id])

        def semantic_after_answer(owner, job, node_ids):
            self.assertEqual(job['_canonical_dialog']['state'], 'answered')
            self.assertEqual(job['_canonical_dialog']['answer'],
                             'Tarihleri karşılaştır')
            self.assertEqual(node_ids, ('first',))
            return {'action': 'complete', 'goal': 0, 'evidence': ['first']}

        with patch.object(task_agents, 'worker',
                          side_effect=AssertionError('worker replay')) as worker, \
             patch.object(canonical_goal_flow, '_semantic_proposal',
                          side_effect=semantic_after_answer):
            self.assertTrue(canonical_goal_flow.complete_and_deliver(
                self.owner, job_id, notified,
            ))
            worker.assert_not_called()
        state, journal = self.persisted(job_id)
        self.assertEqual(state['state'], 'done')
        self.assertEqual(journal['_canonical_delivery'], 'delivered')
        self.assertEqual(journal['_canonical_ui_receipt']['event_id'],
                         'canonical:' + job_id)
        self.assertEqual(notified.call_count, 2)
        self.assertFalse(canonical_goal_flow.complete_and_deliver(
            self.owner, job_id, notified,
        ))
        self.assertEqual(notified.call_count, 2)

    def test_unknown_ui_delivery_never_claims_delivered_or_resends(self):
        job_id = self._accepted_canonical_research_for_crash_test()
        sink = Mock(return_value=None)
        with patch.object(canonical_goal_flow, '_semantic_proposal',
                          return_value={'action': 'complete', 'goal': 0,
                                        'evidence': ['first']}):
            self.assertFalse(canonical_goal_flow.complete_and_deliver(
                self.owner, job_id, sink,
            ))
        state, journal = self.persisted(job_id)
        self.assertEqual(state['state'], 'done')
        self.assertEqual(journal['_canonical_delivery'], 'reserved')
        self.assertNotIn('_canonical_ui_receipt', journal)
        sink.assert_called_once()
        self.assertIn(job_id, canonical_goal_flow.read_completed_result(
            self.owner, job_id,
        ))
        self.assertFalse(canonical_goal_flow.complete_and_deliver(
            self.owner, job_id, sink,
        ))
        sink.assert_called_once()

    def test_first_legacy_safe_plan_is_forwarded_without_second_model_plan(self):
        """A read-only/replay-safe but non-canonical worker stays permissioned.

        Its first model plan is passed to legacy once. No parallel canonical
        job exists, and a repeated request ID never runs that worker again.
        """
        proposal = {'tasks': [{
            'id': 'report', 'agent': 'writer', 'depends': [],
            'input': {'instruction': 'Produce summary', 'filename': 'report.md'},
        }]}
        rid = 'safe-first-legacy-handoff'
        with patch.object(model_wait, 'ask', return_value=json.dumps(proposal)) as model:
            _, _, feedback, job_id = self.typed_turn(
                'Kaynakları kullanıp rapor oluştur.', rid=rid,
            )
        self.assertIsNone(job_id)
        self.assertEqual(feedback.reason_code, 'GOAL_CREATE')
        model.assert_called_once()
        self.run_goal.assert_called_once()
        forwarded = self.run_goal.call_args.kwargs.get('initial_legacy_call')
        self.assertIsInstance(forwarded, dict)
        self.assertEqual(forwarded.get('action'), 'legacy_plan')
        self.assertEqual(forwarded.get('tasks'), proposal['tasks'])
        # Claim is durable before any legacy worker can run.
        with patch.object(model_wait, 'ask',
                          side_effect=AssertionError('duplicate model decision')):
            _, _, duplicate, _ = self.typed_turn(
                'Kaynakları kullanıp rapor oluştur.', rid=rid,
            )
        self.assertEqual(duplicate.reason_code,
                         'GOAL_LEGACY_DUPLICATE_NOT_RESTARTED')
        self.run_goal.assert_called_once()

