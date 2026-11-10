import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

try:
    from google import genai as _genai_probe  # noqa: F401
except ImportError:
    # Cloud/offline sandboxes without pypi access cannot install google-genai.
    # modules.llm imports it at module load time purely to build a client;
    # nothing in this file's tests touches a real model. Install a minimal
    # stand-in so the import chain (goal_tools -> llm) resolves, without
    # changing any production module or faking execute_step's own behaviour.
    _google_pkg = sys.modules.get('google') or ModuleType('google')
    _genai_mod = ModuleType('google.genai')
    _genai_mod.errors = ModuleType('google.genai.errors')
    _genai_mod.types = ModuleType('google.genai.types')

    class _StubClient:
        def __init__(self, *a, **k): pass

    _genai_mod.Client = _StubClient
    _google_pkg.genai = _genai_mod
    sys.modules.setdefault('google', _google_pkg)
    sys.modules['google.genai'] = _genai_mod
    sys.modules['google.genai.errors'] = _genai_mod.errors
    sys.modules['google.genai.types'] = _genai_mod.types


class EffectCrashRestartE2ETests(unittest.TestCase):
    def setUp(self):
        from modules import effect_recovery_runtime, goal_state, goal_state_store, runtime_worker_result
        self.runtime = effect_recovery_runtime
        self.state = goal_state
        self.store = goal_state_store
        self.worker = runtime_worker_result
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # These tests use deliberately fabricated provider receipts to
        # isolate effect-journal/WorkerResult recovery, not domain proof.
        # BRAIN-06E tests assert unverifiable done now fails before commit.
        verified = patch('modules.goal_tools.verify', return_value=True)
        verified.start()
        self.addCleanup(verified.stop)

    def identity(self):
        return {'version':1, 'owner':'alice', 'job_id':'0123456789abcdef',
                'task_id':'s1', 'attempt':1, 'request':'gönder'}

    def data(self):
        return {'service':'gmail', 'destination':'friend@example.com', 'text':'merhaba'}

    def test_crash_restart_reconcile_fences_and_commits_without_repeating_effect(self):
        from modules import goal_executor
        root = Path(self.tmp.name)
        path = root/'alice'/'0123456789abcdef.goalstate.json'
        self.store.create(path, self.state.new(owner='alice', job_id='0123456789abcdef', goal='gönder', execution_mode='durable'))
        _enriched, expected = self.worker.prepare(self.identity(), 'publish', self.data(), expected_job_version=0)
        sent=[]
        recovered={'state':'done', 'receipt':{'service':'gmail', 'remote_id':'r-1'}}

        with patch.object(goal_executor, 'STORE', root):
            self.runtime.record_intent(expected)
            sent.append('one external effect')  # effect happened; worker response is then lost.
            restarted = self.runtime.reconcile(expected, lambda: recovered)
            duplicate = self.runtime.reconcile(expected, lambda: recovered)
            effect_status = self.runtime.status(expected)

        self.assertEqual(sent, ['one external effect'])
        self.assertEqual(restarted, recovered)
        self.assertIsNone(duplicate)
        state = self.store.load(path)
        self.assertEqual(state['version'], 1)
        self.assertEqual(len(state['evidence']), 1)
        self.assertEqual(state['evidence'][0]['kind'], 'worker_result')
        self.assertEqual(effect_status, 'succeeded')

    def test_no_intent_is_fail_closed_and_never_calls_reconcile(self):
        from modules import goal_executor
        root = Path(self.tmp.name)
        path = root/'alice'/'0123456789abcdef.goalstate.json'
        self.store.create(path, self.state.new(owner='alice', job_id='0123456789abcdef', goal='gönder', execution_mode='durable'))
        _enriched, expected = self.worker.prepare(self.identity(), 'publish', self.data(), expected_job_version=0)
        called=[]
        with patch.object(goal_executor, 'STORE', root):
            self.assertIsNone(self.runtime.reconcile(expected, lambda: called.append(True)))
        self.assertEqual(called, [])

    def _job_and_step(self, tool, data):
        job = {'owner': 'alice', 'id': '0123456789abcdef', 'request': 'gönder', 'outputs': {}, 'state': 'running'}
        step = {'id': 's1', 'tool': tool, 'input': data, 'depends': [], 'attempts': 1, 'state': 'running'}
        return job, step

    def test_normal_execute_records_intent_before_the_worker_is_called(self):
        """Guarantee: for a journal-required capability, record_intent() runs
        strictly before the worker call, never after."""
        from modules import specialist_orchestrator, runtime_execution_gate, worker_result_hook, goal_executor
        from types import SimpleNamespace
        order = []
        job, step = self._job_and_step('publish', self.data())
        identity = goal_executor._identity(job, step)
        runtime = SimpleNamespace(profile=SimpleNamespace(slug='alice'))
        root = Path(self.tmp.name)
        path = root / 'alice' / '0123456789abcdef.goalstate.json'
        self.store.create(path, self.state.new(owner='alice', job_id='0123456789abcdef', goal='gönder', execution_mode='durable'))

        def fake_record_intent(expected):
            order.append('record_intent')
            return 'effect:fake'

        def fake_execute(_runtime, _tool, _data, _deps, _identity, approval=None):
            order.append('worker_execute')
            output = {'state': 'done', 'receipt': {'service': 'gmail', 'remote_id': 'r-1'}}
            return worker_result_hook.wrap_output(output, _identity)

        with patch.object(goal_executor, 'STORE', root), \
             patch.object(runtime_execution_gate, 'plan_task', return_value={'phase': 'execute'}), \
             patch.object(self.runtime, 'record_intent', side_effect=fake_record_intent), \
             patch.object(self.runtime, 'record_receipt') as record_receipt, \
             patch.object(worker_result_hook, 'execute', side_effect=fake_execute):
            output = specialist_orchestrator.execute_step(runtime, job, step, identity)

        self.assertEqual(order, ['record_intent', 'worker_execute'])
        self.assertEqual(output, {'state': 'done', 'receipt': {'service': 'gmail', 'remote_id': 'r-1'}})
        record_receipt.assert_called_once()

    def test_read_only_capability_never_enters_the_journal_path(self):
        """Guarantee: a manifest read-only capability (research) must never call
        record_intent/record_receipt, even though it flows through the same
        gated execute_step branch as journal-required capabilities."""
        from modules import specialist_orchestrator, runtime_execution_gate, worker_result_hook, goal_executor
        from types import SimpleNamespace
        job, step = self._job_and_step('research', {'url': 'https://example.test', 'question': 'x'})
        identity = goal_executor._identity(job, step)
        runtime = SimpleNamespace(profile=SimpleNamespace(slug='alice'))
        root = Path(self.tmp.name)
        path = root / 'alice' / '0123456789abcdef.goalstate.json'
        self.store.create(path, self.state.new(owner='alice', job_id='0123456789abcdef', goal='gönder', execution_mode='durable'))

        def fake_execute(_runtime, _tool, _data, _deps, _identity, approval=None):
            output = {'state': 'done', 'verification': {'version': 1, 'agent': 'research', 'scope': 'execution_evidence', 'outcome': 'x'}}
            return worker_result_hook.wrap_output(output, _identity)

        with patch.object(goal_executor, 'STORE', root), \
             patch.object(runtime_execution_gate, 'plan_task', return_value={'phase': 'execute'}), \
             patch.object(self.runtime, 'record_intent') as record_intent, \
             patch.object(self.runtime, 'record_receipt') as record_receipt, \
             patch.object(worker_result_hook, 'execute', side_effect=fake_execute):
            specialist_orchestrator.execute_step(runtime, job, step, identity)

        record_intent.assert_not_called()
        record_receipt.assert_not_called()

    def test_verified_receipt_never_reconciles_or_bumps_evidence_again(self):
        from modules import goal_executor
        root = Path(self.tmp.name)
        path = root/'alice'/'0123456789abcdef.goalstate.json'
        self.store.create(path, self.state.new(owner='alice', job_id='0123456789abcdef', goal='gönder', execution_mode='durable'))
        _enriched, expected = self.worker.prepare(self.identity(), 'publish', self.data(), expected_job_version=0)
        called=[]
        with patch.object(goal_executor, 'STORE', root):
            self.runtime.record_intent(expected)
            self.runtime.record_receipt(expected, {'receipt': {'service':'gmail', 'remote_id':'r-1'}})
            self.assertIsNone(self.runtime.reconcile(expected, lambda: called.append(True)))
            self.assertEqual(self.runtime.status(expected), 'succeeded')
        self.assertEqual(called, [])
        self.assertEqual(self.store.load(path)['version'], 0)

    def test_unknown_intent_without_receipt_is_read_only_reconcile_never_a_retry(self):
        """Guarantee: intent present, no receipt -> reconcile reads once and
        commits through the normal fence/CAS path; it never re-invokes the
        provider effect itself (the lambda given here is a pure read)."""
        from modules import goal_executor
        root = Path(self.tmp.name)
        path = root/'alice'/'0123456789abcdef.goalstate.json'
        self.store.create(path, self.state.new(owner='alice', job_id='0123456789abcdef', goal='gönder', execution_mode='durable'))
        _enriched, expected = self.worker.prepare(self.identity(), 'publish', self.data(), expected_job_version=0)
        reads = []

        def read_only_reconcile():
            reads.append('read')
            return {'state': 'done', 'receipt': {'service': 'gmail', 'remote_id': 'r-1'}}

        with patch.object(goal_executor, 'STORE', root):
            self.runtime.record_intent(expected)
            self.assertEqual(self.runtime.status(expected), 'unknown')
            output = self.runtime.reconcile(expected, read_only_reconcile)
            self.assertEqual(self.runtime.status(expected), 'succeeded')
        self.assertEqual(reads, ['read'])  # exactly one read, never a provider effect call
        self.assertEqual(output['state'], 'done')
        state = self.store.load(path)
        self.assertEqual(state['version'], 1)
        self.assertEqual(len(state['evidence']), 1)

    def test_reconcile_rejects_a_foreign_or_stale_worker_result_fence(self):
        """Guarantee 7: reconcile's recovered output still goes through the
        real WorkerResult fence/Reducer-CAS acceptance path; a fence that does
        not match the expected identity must be rejected, not silently
        accepted as the recovered effect."""
        from modules import goal_executor, worker_result_hook
        root = Path(self.tmp.name)
        path = root/'alice'/'0123456789abcdef.goalstate.json'
        self.store.create(path, self.state.new(owner='alice', job_id='0123456789abcdef', goal='gönder', execution_mode='durable'))
        _enriched, expected = self.worker.prepare(self.identity(), 'publish', self.data(), expected_job_version=0)

        def tampered_reconcile():
            output = {'state': 'done', 'receipt': {'service': 'gmail', 'remote_id': 'r-1'}}
            return output

        with patch.object(goal_executor, 'STORE', root), \
             patch.object(worker_result_hook, 'wrap_output', side_effect=lambda output, _expected: {
                 **output, '_worker_result': {**expected, 'command_id': 'foreign-command'}}):
            self.runtime.record_intent(expected)
            with self.assertRaises(ValueError):
                self.runtime.reconcile(expected, tampered_reconcile)
        # The rejected fence must not have been accepted as a completed effect.
        self.assertEqual(self.store.load(path)['version'], 0)

    def test_worker_done_alone_is_not_global_job_completion(self):
        """Guarantee 8: an accepted worker_result with state=done only advances
        this GoalState's version/evidence; it never flips GoalState.state to a
        terminal value by itself. Global completion stays the reducer's job."""
        from modules import goal_executor
        root = Path(self.tmp.name)
        path = root/'alice'/'0123456789abcdef.goalstate.json'
        self.store.create(path, self.state.new(owner='alice', job_id='0123456789abcdef', goal='gönder', execution_mode='durable'))
        _enriched, expected = self.worker.prepare(self.identity(), 'publish', self.data(), expected_job_version=0)
        recovered = {'state': 'done', 'receipt': {'service': 'gmail', 'remote_id': 'r-1'}}
        with patch.object(goal_executor, 'STORE', root):
            self.runtime.record_intent(expected)
            self.runtime.reconcile(expected, lambda: recovered)
        state = self.store.load(path)
        self.assertEqual(state['version'], 1)
        self.assertEqual(state['state'], 'pending')  # unchanged: worker-done is not job-done


if __name__ == '__main__':
    unittest.main()
