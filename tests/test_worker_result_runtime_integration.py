import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace


class WorkerResultRuntimeIntegrationTests(unittest.TestCase):
    def setUp(self):
        from modules import goal_state, goal_state_store, runtime_worker_result, worker_result_hook
        self.goal_state = goal_state
        self.store = goal_state_store
        self.runtime = runtime_worker_result
        self.hook = worker_result_hook

    def identity(self):
        return {
            'owner': 'alice', 'job_id': '0123456789abcdef', 'task_id': 's1',
            'attempt': 1, 'request': 'örnek',
        }

    def durable_identity(self):
        return {
            **self.identity(), 'version': 1, 'capability': 'research',
            'risk': 'network_read', 'replay_safe': True, 'outcome': 'pending',
        }

    def test_worker_boundary_emits_real_fence_and_accepts_exact_match_without_output_pollution(self):
        identity, expected = self.runtime.prepare(
            self.identity(), 'research', {'url': 'https://example.test', 'question': 'x'}, expected_job_version=3,
        )
        output = {'state': 'done', 'verification': {'version': 1, 'agent': 'research', 'scope': 'execution_evidence', 'outcome': 'x'}}
        wrapped = self.hook.wrap_output(output, identity)
        self.assertEqual(wrapped['_worker_result']['expected_job_version'], 3)
        self.assertEqual(wrapped['_worker_result']['capability_id'], 'task.research')
        accepted = self.runtime.accept_output(wrapped, expected)
        self.assertEqual(accepted, output)
        self.assertNotIn('_worker_result', accepted)

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
            self.assertEqual(self.runtime.accept_output(wrapped, expected), fake)
        self.assertIs(goal_tools.execute, original)

    def test_canonical_version_reads_active_goal_executor_store(self):
        from modules import goal_executor
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / 'goals'
            path = store / 'alice' / '0123456789abcdef.goalstate.json'
            state = self.goal_state.new(owner='alice', job_id='0123456789abcdef', goal='hedef', execution_mode='agent')
            self.store.create(path, state)
            with patch.object(goal_executor, 'STORE', store):
                self.assertEqual(self.runtime.canonical_version(self.identity()), 0)

    def test_only_versioned_runtime_identity_enters_durable_fence_slice(self):
        self.assertFalse(self.runtime.durable_identity(self.identity()))
        self.assertTrue(self.runtime.durable_identity(self.durable_identity()))

    def test_goal_step_attempt_changes_worker_command_identity(self):
        from modules import goal_executor
        job = {'owner':'alice','id':'0123456789abcdef','request':'örnek','outputs':{}}
        step = {'id':'s1','tool':'research','input':{'url':'https://example.test','question':'x'},'attempts':2}
        identity = goal_executor._identity(job, step)
        _enriched, expected = self.runtime.prepare(identity, 'research', step['input'], expected_job_version=0)
        self.assertEqual(expected['attempt'], 2)
        self.assertEqual(expected['command_id'], 's1:2')

    def test_record_persists_incremented_attempt_before_each_worker_call(self):
        from modules import goal_executor
        runtime = SimpleNamespace(profile=SimpleNamespace(slug='alice'), emit=lambda *args: None)
        job = {'owner':'alice','id':'0123456789abcdef','request':'örnek','outputs':{},
               'goals':[{'text':'örnek'}], 'state':'running'}
        step = {'id':'s1','goal':0,'tool':'research',
                'input':{'url':'https://example.test','question':'x'},'depends':[]}
        saved=[]; identities=[]
        def execute(_runtime, _job, _step, identity, **_kwargs):
            self.assertIn(identity['attempt'], saved)
            identities.append(identity)
            return {'state':'done'}
        with patch('modules.goal_executor._save',side_effect=lambda value:saved.append(value['steps'][0].get('attempts'))), \
             patch('modules.brain_delegate.assign',return_value='research'), \
             patch('modules.goal_tools.checkpoint',return_value=None), \
             patch('modules.goal_tools.verify',return_value=True), \
             patch('modules.specialist_orchestrator.execute_step',side_effect=execute):
            job['steps']=[step]
            goal_executor._record(runtime,job,step)
            goal_executor._record(runtime,job,step)
        self.assertEqual([row['attempt'] for row in identities],[1,2])
        self.assertIn(1,saved)
        self.assertIn(2,saved)


if __name__ == '__main__':
    unittest.main()
