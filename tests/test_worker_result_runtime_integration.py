import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class WorkerResultRuntimeIntegrationTests(unittest.TestCase):
    def setUp(self):
        from modules import goal_state, goal_state_compat, goal_state_store, runtime_worker_result, worker_result_hook
        self.goal_state = goal_state
        self.compat = goal_state_compat
        self.store = goal_state_store
        self.runtime = runtime_worker_result
        self.hook = worker_result_hook

    def identity(self):
        return {
            'owner': 'alice', 'job_id': '0123456789abcdef', 'task_id': 's1',
            'attempt': 1, 'request': 'örnek',
        }

    def test_worker_boundary_emits_real_fence_and_accepts_exact_match(self):
        identity, expected = self.runtime.prepare(
            self.identity(), 'research', {'url': 'https://example.test', 'question': 'x'}, expected_job_version=3,
        )
        output = {'state': 'done', 'verification': {'version': 1, 'agent': 'research', 'scope': 'execution_evidence', 'outcome': 'x'}}
        wrapped = self.hook.wrap_output(output, identity)
        accepted = self.runtime.accept_output(wrapped, expected)
        self.assertEqual(accepted['_worker_result']['expected_job_version'], 3)
        self.assertEqual(accepted['_worker_result']['capability_id'], 'task.research')

    def test_foreign_or_stale_worker_fence_is_rejected(self):
        identity, expected = self.runtime.prepare(
            self.identity(), 'research', {'url': 'https://example.test', 'question': 'x'}, expected_job_version=3,
        )
        output = self.hook.wrap_output({'state': 'done', 'verification': {'version': 1}}, identity)
        output['_worker_result']['command_id'] = 'foreign'
        with self.assertRaises(ValueError):
            self.runtime.accept_output(output, expected)

    def test_per_call_wrapper_never_replaces_global_goal_tools_execute(self):
        from modules import goal_tools
        original = goal_tools.execute
        identity, expected = self.runtime.prepare(
            self.identity(), 'research', {'url': 'https://example.test', 'question': 'x'}, expected_job_version=3,
        )
        fake = {'state': 'failed', 'text': 'x'}
        with patch.object(goal_tools, 'execute', return_value=fake) as execute:
            wrapped = self.hook.execute(None, 'research', {'url': 'https://example.test', 'question': 'x'}, {}, identity)
            execute.assert_called_once()
            self.runtime.accept_output(wrapped, expected)
        self.assertIs(goal_tools.execute, original)

    def test_canonical_version_reads_owner_scoped_goalstate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'goals' / 'alice' / '0123456789abcdef.goalstate.json'
            state = self.goal_state.new(owner='alice', job_id='0123456789abcdef', goal='hedef', execution_mode='agent')
            self.store.create(path, state)
            with patch.object(self.runtime, 'DATA_DIR', root):
                self.assertEqual(self.runtime.canonical_version(self.identity()), 0)

    def test_accepted_worker_result_becomes_goalstate_reducer_evidence(self):
        identity, expected = self.runtime.prepare(
            self.identity(), 'research', {'url': 'https://example.test', 'question': 'x'}, expected_job_version=1,
        )
        wrapped = self.hook.wrap_output({'state': 'done', 'verification': {'version': 1}}, identity)
        accepted = self.runtime.accept_output(wrapped, expected)
        current = self.goal_state.new(owner='alice', job_id='0123456789abcdef', goal='hedef', execution_mode='agent')
        current['state'] = 'running'; current['version'] = 1
        current['audit'].append({'version': 1, 'op': 'set_state', 'state': 'running', 'reason_code': 'TEST'})
        job = {
            'owner': 'alice', 'id': '0123456789abcdef', 'request': 'hedef', 'state': 'running',
            'outputs': {'s1': accepted}, 'steps': [], 'goals': [],
        }
        next_state = self.compat.advance(current, job)
        evidence = [row for row in next_state['evidence'] if row.get('kind') == 'worker_result']
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]['command_id'], accepted['_worker_result']['command_id'])
        again = self.compat.advance(next_state, job)
        self.assertEqual(again['evidence'], next_state['evidence'])


if __name__ == '__main__':
    unittest.main()
