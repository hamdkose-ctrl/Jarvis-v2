import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class WorkerResultReducerCommitTests(unittest.TestCase):
    def setUp(self):
        from modules import goal_state, goal_state_store, runtime_worker_result, worker_result_hook
        self.goal_state = goal_state
        self.store = goal_state_store
        self.runtime = runtime_worker_result
        self.hook = worker_result_hook

    def identity(self):
        return {
            'version': 1,
            'owner': 'alice',
            'job_id': '0123456789abcdef',
            'task_id': 's1',
            'attempt': 1,
            'request': 'örnek',
        }

    def _fixture(self, root: Path):
        from modules import goal_executor
        owner_root = root / 'alice'
        owner_root.mkdir(parents=True, exist_ok=True)
        path = owner_root / '0123456789abcdef.goalstate.json'
        state = self.goal_state.new(
            owner='alice', job_id='0123456789abcdef', goal='hedef', execution_mode='agent'
        )
        self.store.create(path, state)
        return goal_executor, path

    def _wrapped(self, expected_job_version=0):
        identity, expected = self.runtime.prepare(
            self.identity(),
            'research',
            {'url': 'https://example.test', 'question': 'x'},
            expected_job_version=expected_job_version,
        )
        output = self.hook.wrap_output(
            {'state': 'done', 'verification': {'version': 1}}, identity
        )
        return output, expected

    def test_accepted_result_commits_reducer_evidence_before_legacy_state_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            goal_executor, path = self._fixture(root)
            output, expected = self._wrapped(0)
            with patch.object(goal_executor, 'STORE', root):
                clean = self.runtime.accept_and_commit(output, expected)
            state = self.store.load(path)
            self.assertNotIn('_worker_result', clean)
            self.assertEqual(state['version'], 1)
            self.assertEqual(state['state'], 'pending')
            self.assertEqual(len(state['evidence']), 1)
            self.assertEqual(state['evidence'][0]['kind'], 'worker_result')
            self.assertEqual(state['evidence'][0]['command_id'], 's1:1')
            self.assertEqual(state['audit'][-1]['op'], 'append_evidence')
            self.assertEqual(state['audit'][-1]['reason_code'], 'WORKER_RESULT_ACCEPTED')

    def test_same_accepted_command_is_idempotent_without_second_version_bump(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            goal_executor, path = self._fixture(root)
            output, expected = self._wrapped(0)
            with patch.object(goal_executor, 'STORE', root):
                self.runtime.accept_and_commit(output, expected)
                self.runtime.accept_and_commit(output, expected)
            state = self.store.load(path)
            self.assertEqual(state['version'], 1)
            self.assertEqual(len(state['evidence']), 1)

    def test_foreign_or_stale_result_never_mutates_goalstate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            goal_executor, path = self._fixture(root)
            output, expected = self._wrapped(0)
            bad = copy.deepcopy(output)
            bad['_worker_result']['command_id'] = 'foreign'
            with patch.object(goal_executor, 'STORE', root):
                with self.assertRaises(ValueError):
                    self.runtime.accept_and_commit(bad, expected)
            state = self.store.load(path)
            self.assertEqual(state['version'], 0)
            self.assertEqual(state['evidence'], [])


if __name__ == '__main__':
    unittest.main()
