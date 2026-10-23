import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class EffectCrashRestartE2ETests(unittest.TestCase):
    def setUp(self):
        from modules import effect_recovery_runtime, goal_state, goal_state_store, runtime_worker_result
        self.runtime = effect_recovery_runtime
        self.state = goal_state
        self.store = goal_state_store
        self.worker = runtime_worker_result
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

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


if __name__ == '__main__':
    unittest.main()
