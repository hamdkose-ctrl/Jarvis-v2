import unittest
from types import SimpleNamespace
from unittest.mock import patch


class DesktopRuntimeGateTests(unittest.TestCase):
    """The existing desktop adapter must enter the same durable gate as workers.

    These tests deliberately mock native UIA.  They lock the Core/adapter boundary;
    real Windows acceptance remains the PC watcher's responsibility.
    """

    def runtime(self):
        return SimpleNamespace(profile=SimpleNamespace(slug='alice'))

    def job(self):
        return {'owner': 'alice', 'id': 'job-1', 'request': 'Paint içinde bir çizgi çiz',
                'outputs': {}, 'state': 'running'}

    def identity(self):
        return {'version': 1, 'owner': 'alice', 'job_id': 'job-1', 'task_id': 's1',
                'capability': 'desktop', 'risk': 'physical_effect', 'replay_safe': False,
                'attempt': 1, 'outcome': 'pending', 'request': 'Paint içinde bir çizgi çiz'}

    def step(self):
        return {'id': 's1', 'tool': 'desktop',
                'input': {'target': 'Paint', 'goal': 'bir çizgi çiz'}, 'depends': [],
                'state': 'running'}

    def test_unapproved_desktop_never_starts_native_worker(self):
        from modules import specialist_orchestrator
        artifact = {'state': 'approval', 'approval_schema': 'runtime_prepare_approval.v1'}
        with patch('modules.runtime_execution_gate.plan_task', return_value={'phase': 'prepare'}), \
             patch('modules.runtime_prepare_approval.prepare', return_value=artifact) as prepare, \
             patch('modules.runtime_execution_gate.accept_prepare_result', side_effect=lambda _plan, output: output), \
             patch('modules.goal_tools.execute') as execute:
            output = specialist_orchestrator.execute_step(
                self.runtime(), self.job(), self.step(), self.identity())
        self.assertEqual(output, artifact)
        prepare.assert_called_once_with(self.identity(), 'desktop', self.step()['input'])
        execute.assert_not_called()

    def test_exact_outer_approval_fences_and_commits_desktop_result(self):
        from modules import specialist_orchestrator
        approval = {'state': 'approval', 'approval_schema': 'runtime_prepare_approval.v1'}
        native = {'state': 'done', 'text': 'Çizgi doğrulandı.', 'desktop_id': 'native-1'}
        enriched = {**self.identity(), 'command_id': 's1:1'}
        expected = {'owner': 'alice', 'job_id': 'job-1', 'step_id': 's1', 'command_id': 's1:1'}
        fenced = {**native, '_worker_result': {'schema': 'worker_result.v1'}}
        step = self.step()
        with patch('modules.runtime_prepare_approval.accept', return_value=True) as accept_prepare, \
             patch('modules.runtime_execution_gate.plan_task', return_value={'phase': 'execute'}), \
             patch('modules.runtime_worker_result.durable_identity', return_value=True), \
             patch('modules.runtime_worker_result.prepare', return_value=(enriched, expected)), \
             patch('modules.effect_recovery_runtime.required', return_value=False), \
             patch('modules.worker_result_hook.execute', return_value=fenced) as execute, \
             patch('modules.runtime_worker_result.accept_and_commit', return_value=native) as commit:
            output = specialist_orchestrator.execute_step(
                self.runtime(), self.job(), step, self.identity(), approval=approval)
        accept_prepare.assert_called_once_with(approval, self.identity(), 'desktop', self.step()['input'])
        # The outer approval is not a native desktop click approval.
        self.assertIsNone(execute.call_args.kwargs['approval'])
        commit.assert_called_once_with(fenced, expected)
        self.assertTrue(step['runtime_approved'])
        self.assertEqual(output, native)

    def test_native_follow_up_approval_is_not_committed_as_worker_success(self):
        from modules import specialist_orchestrator
        step = {**self.step(), 'runtime_approved': True}
        native = {'state': 'approval', 'text': 'Paint içi işlem onayı bekliyor.',
                  'desktop_id': 'native-1'}
        enriched = {**self.identity(), 'command_id': 's1:2'}
        expected = {'owner': 'alice', 'job_id': 'job-1', 'step_id': 's1', 'command_id': 's1:2'}
        with patch('modules.runtime_execution_gate.plan_task', return_value={'phase': 'execute'}), \
             patch('modules.runtime_worker_result.durable_identity', return_value=True), \
             patch('modules.runtime_worker_result.prepare', return_value=(enriched, expected)), \
             patch('modules.effect_recovery_runtime.required', return_value=False), \
             patch('modules.worker_result_hook.execute', return_value=native), \
             patch('modules.runtime_worker_result.accept_and_commit') as commit:
            output = specialist_orchestrator.execute_step(
                self.runtime(), self.job(), step, self.identity(), approval=native)
        self.assertEqual(output, native)
        commit.assert_not_called()

    def test_desktop_identity_is_versioned_and_effectful(self):
        from modules import goal_executor, task_tools
        job = {**self.job(), 'outputs': {}}
        identity = goal_executor._identity(job, self.step())
        self.assertEqual(identity['version'], task_tools.VERSION)
        self.assertEqual(identity['capability'], 'desktop')
        self.assertEqual(identity['risk'], 'physical_effect')
        self.assertFalse(identity['replay_safe'])
        self.assertEqual(identity['attempt'], 0)

    def test_reconcile_accepts_only_verified_matching_completed_native_task(self):
        from modules import desktop_agent, goal_tools
        runtime = self.runtime()
        native = {
            'id': 'native-1', 'owner': 'alice', 'target': 'Paint',
            'goal': 'bir çizgi çiz', 'status': 'done',
            'history': [{'verified': True}],
        }
        with patch.object(desktop_agent, '_load', return_value=native), \
             patch.object(desktop_agent, 'render', return_value='Çizgi doğrulandı.'):
            output = goal_tools.reconcile(
                runtime, 'desktop', self.step()['input'], self.identity(), None)
        self.assertEqual(output['state'], 'done')
        self.assertEqual(output['desktop_id'], 'native-1')
        self.assertEqual(output['receipt'], {'service': 'desktop_uia', 'remote_id': 'native-1'})
        self.assertTrue(output['reconciled'])

    def test_reconcile_rejects_stale_or_unverified_native_task_without_replay(self):
        from modules import desktop_agent, goal_tools
        runtime = self.runtime()
        variants = (
            {'id': 'native-1', 'owner': 'mallory', 'target': 'Paint', 'goal': 'bir çizgi çiz',
             'status': 'done', 'history': [{'verified': True}]},
            {'id': 'native-1', 'owner': 'alice', 'target': 'Notepad', 'goal': 'bir çizgi çiz',
             'status': 'done', 'history': [{'verified': True}]},
            {'id': 'native-1', 'owner': 'alice', 'target': 'Paint', 'goal': 'bir çizgi çiz',
             'status': 'approval', 'history': [{'verified': True}]},
            {'id': 'native-1', 'owner': 'alice', 'target': 'Paint', 'goal': 'bir çizgi çiz',
             'status': 'done', 'history': [{'verified': False}]},
        )
        for native in variants:
            with self.subTest(native=native), patch.object(desktop_agent, '_load', return_value=native), \
                 patch.object(desktop_agent, 'handle') as create, \
                 patch.object(desktop_agent, 'run') as replay:
                output = goal_tools.reconcile(
                    runtime, 'desktop', self.step()['input'], self.identity(), None)
            self.assertIsNone(output)
            create.assert_not_called()
            replay.assert_not_called()


if __name__ == '__main__':
    unittest.main()
