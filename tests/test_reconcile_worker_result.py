import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ReconcileWorkerResultTests(unittest.TestCase):
    def setUp(self):
        from modules import goal_state, goal_state_store, reconcile_worker_result
        self.goal_state = goal_state
        self.store = goal_state_store
        self.reconcile = reconcile_worker_result
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def identity(self):
        return {
            'version': 1,
            'owner': 'alice',
            'job_id': '0123456789abcdef',
            'task_id': 's1',
            'attempt': 1,
            'request': 'örnek',
        }

    def data(self):
        return {'url': 'https://example.test', 'question': 'x'}

    def fixture(self):
        from modules import goal_executor
        root = Path(self.tmp.name)
        path = root / 'alice' / '0123456789abcdef.goalstate.json'
        self.store.create(path, self.goal_state.new(
            owner='alice', job_id='0123456789abcdef', goal='hedef', execution_mode='agent'
        ))
        return goal_executor, root, path

    def recovered(self):
        return {'state': 'done', 'text': 'etki salt-okunur doğrulama ile bulundu.', 'reconciled': True}

    def test_exact_reconcile_result_is_bound_to_current_execution_and_committed(self):
        goal_executor, root, path = self.fixture()
        with patch.object(goal_executor, 'STORE', root):
            accepted = self.reconcile.accept_and_commit(self.recovered(), self.identity(), 'research', self.data())
        self.assertEqual(accepted, self.recovered())
        self.assertNotIn('_worker_result', accepted)
        self.assertEqual(self.store.load(path)['version'], 1)

    def test_reconcile_result_commits_reducer_cas_evidence_once(self):
        goal_executor, root, path = self.fixture()
        with patch.object(goal_executor, 'STORE', root):
            first = self.reconcile.accept_and_commit(self.recovered(), self.identity(), 'research', self.data())
            second = self.reconcile.accept_and_commit(self.recovered(), self.identity(), 'research', self.data())
        state = self.store.load(path)
        self.assertEqual(first, second)
        self.assertEqual(state['version'], 1)
        self.assertEqual(len(state['evidence']), 1)
        self.assertEqual(state['evidence'][0]['kind'], 'worker_result')
        self.assertEqual(state['audit'][-1]['reason_code'], 'WORKER_RESULT_ACCEPTED')

    def test_foreign_or_stale_reconcile_fences_fail_closed(self):
        goal_executor, root, path = self.fixture()
        fields = {
            'owner': 'mallory',
            'job_id': 'fedcba9876543210',
            'step_id': 'other-step',
            'command_id': 'foreign:9',
            'attempt': 9,
            'expected_job_version': 7,
            'capability_id': 'task.writer',
            'capability_version': '9',
            'input_digest': 'b' * 64,
        }
        for field, value in fields.items():
            with self.subTest(field=field), patch.object(goal_executor, 'STORE', root):
                forged = self.reconcile.envelope(self.recovered(), self.identity(), 'research', self.data())
                forged['_worker_result'][field] = value
                with self.assertRaises(ValueError):
                    self.reconcile.accept_and_commit(forged, self.identity(), 'research', self.data())
                state = self.store.load(path)
                self.assertEqual(state['version'], 0)
                self.assertEqual(state['evidence'], [])

    def test_non_done_or_non_durable_result_is_not_committed_or_retried(self):
        goal_executor, root, path = self.fixture()
        with patch.object(goal_executor, 'STORE', root):
            failed = self.reconcile.accept_and_commit({'state': 'failed', 'text': 'belirsiz'}, self.identity(), 'research', self.data())
            legacy = self.reconcile.accept_and_commit(self.recovered(), {'owner': 'alice', 'job_id': '0123456789abcdef', 'task_id': 's1'}, 'research', self.data())
        self.assertEqual(failed['state'], 'failed')
        self.assertEqual(legacy, self.recovered())
        state = self.store.load(path)
        self.assertEqual(state['version'], 0)
        self.assertEqual(state['evidence'], [])

    def test_goal_executor_routes_only_done_recovery_through_fence_adapter(self):
        from modules import goal_executor
        runtime = object()
        job = {'owner': 'alice', 'id': '0123456789abcdef'}
        step = {'id': 's1', 'tool': 'research', 'input': self.data(), 'checkpoint': {'before': []}}
        identity = self.identity()
        recovered = self.recovered()
        with patch('modules.goal_tools.reconcile', return_value=recovered) as reconcile, \
             patch('modules.goal_executor._identity', return_value=identity), \
             patch('modules.reconcile_worker_result.accept_and_commit', return_value=recovered) as accept:
            self.assertEqual(goal_executor._reconcile(runtime, job, step), recovered)
        reconcile.assert_called_once_with(runtime, 'research', self.data(), identity, {'before': []})
        accept.assert_called_once_with(recovered, identity, 'research', self.data())

    def test_goal_executor_does_not_fence_or_retry_non_done_reconcile_observation(self):
        from modules import goal_executor
        runtime = object()
        job = {'owner': 'alice', 'id': '0123456789abcdef'}
        step = {'id': 's1', 'tool': 'research', 'input': self.data(), 'checkpoint': None}
        with patch('modules.goal_tools.reconcile', return_value={'state': 'failed', 'text': 'belirsiz'}), \
             patch('modules.goal_executor._identity', return_value=self.identity()), \
             patch('modules.reconcile_worker_result.accept_and_commit') as accept:
            result = goal_executor._reconcile(runtime, job, step)
        self.assertEqual(result['state'], 'failed')
        accept.assert_not_called()


if __name__ == '__main__':
    unittest.main()
