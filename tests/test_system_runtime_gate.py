import ast
import engine_source
import re
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class SystemRuntimeGateTests(unittest.TestCase):
    """Verified system-state changes use the existing durable worker boundary.

    Volume, mute and brightness participate only when their real readback
    contract confirms the requested system state. Media keys remain excluded.
    """

    def setUp(self):
        sys.modules.setdefault('pyautogui', SimpleNamespace())

    def runtime(self):
        return SimpleNamespace(profile=SimpleNamespace(slug='alice'), _cur_source='',
                               pc_profile=lambda: SimpleNamespace(slug='alice'))

    def job(self):
        return {'owner': 'alice', 'id': 'job-1', 'request': 'Sesi yüzde 40 yap',
                'outputs': {}, 'state': 'running'}

    def identity(self):
        return {'version': 1, 'owner': 'alice', 'job_id': 'job-1', 'task_id': 's1',
                'capability': 'system', 'risk': 'local_destructive',
                'replay_safe': False, 'attempt': 1, 'outcome': 'pending',
                'request': 'Sesi yüzde 40 yap'}

    def step(self):
        return {'id': 's1', 'tool': 'system',
                'input': {'operation': 'volume', 'level': 40}, 'depends': [],
                'state': 'running'}

    def test_unapproved_volume_does_not_call_system_adapter(self):
        from modules import specialist_orchestrator
        artifact = {'state': 'approval', 'approval_schema': 'runtime_prepare_approval.v1'}
        with patch('modules.runtime_execution_gate.plan_task', return_value={'phase': 'prepare'}), \
             patch('modules.runtime_prepare_approval.prepare', return_value=artifact) as prepare, \
             patch('modules.runtime_execution_gate.accept_prepare_result', side_effect=lambda _plan, output: output), \
             patch('modules.goal_tools.execute') as execute:
            output = specialist_orchestrator.execute_step(
                self.runtime(), self.job(), self.step(), self.identity())
        self.assertEqual(output, artifact)
        prepare.assert_called_once_with(self.identity(), 'system', self.step()['input'])
        execute.assert_not_called()

    def test_approved_volume_records_intent_receipt_and_commits_fenced_result(self):
        from modules import specialist_orchestrator
        approval = {'state': 'approval', 'approval_schema': 'runtime_prepare_approval.v1'}
        clean = {'state': 'done', 'text': 'Ses seviyesi: 40',
                 'receipt': {'service': 'system_control', 'remote_id': 'volume:40'}}
        fenced = {**clean, '_worker_result': {'schema': 'worker_result.v1'}}
        enriched = {**self.identity(), 'command_id': 's1:1'}
        expected = {'owner': 'alice', 'job_id': 'job-1', 'step_id': 's1', 'command_id': 's1:1'}
        step = self.step()
        with patch('modules.runtime_prepare_approval.accept', return_value=True) as accept, \
             patch('modules.runtime_execution_gate.plan_task', return_value={'phase': 'execute'}), \
             patch('modules.runtime_worker_result.durable_identity', return_value=True), \
             patch('modules.runtime_worker_result.prepare', return_value=(enriched, expected)), \
             patch('modules.effect_recovery_runtime.required', return_value=True), \
             patch('modules.effect_recovery_runtime.record_intent') as record_intent, \
             patch('modules.worker_result_hook.execute', return_value=fenced) as execute, \
             patch('modules.effect_recovery_runtime.record_receipt') as record_receipt, \
             patch('modules.runtime_worker_result.accept_and_commit', return_value=clean) as commit:
            output = specialist_orchestrator.execute_step(
                self.runtime(), self.job(), step, self.identity(), approval=approval)
        accept.assert_called_once_with(approval, self.identity(), 'system', self.step()['input'])
        self.assertIsNone(execute.call_args.kwargs['approval'])
        record_intent.assert_called_once_with(expected)
        record_receipt.assert_called_once_with(expected, fenced)
        commit.assert_called_once_with(fenced, expected)
        self.assertEqual(output, clean)

    def test_receipt_required_done_without_receipt_is_not_committed(self):
        from modules import effect_journal, specialist_orchestrator
        approval = {'state': 'approval', 'approval_schema': 'runtime_prepare_approval.v1'}
        fenced = {'state': 'done', 'text': 'Ses seviyesi değişti',
                  '_worker_result': {'schema': 'worker_result.v1'}}
        enriched = {**self.identity(), 'command_id': 's1:1'}
        expected = {'owner': 'alice', 'job_id': 'job-1', 'step_id': 's1', 'command_id': 's1:1'}
        with patch('modules.runtime_prepare_approval.accept', return_value=True), \
             patch('modules.runtime_execution_gate.plan_task', return_value={'phase': 'execute'}), \
             patch('modules.runtime_worker_result.durable_identity', return_value=True), \
             patch('modules.runtime_worker_result.prepare', return_value=(enriched, expected)), \
             patch('modules.effect_recovery_runtime.required', return_value=True), \
             patch('modules.effect_recovery_runtime.record_intent'), \
             patch('modules.worker_result_hook.execute', return_value=fenced), \
             patch('modules.effect_recovery_runtime.record_receipt') as record_receipt, \
             patch('modules.runtime_worker_result.accept_and_commit') as commit:
            with self.assertRaisesRegex(effect_journal.ContractViolation, 'receipt'):
                specialist_orchestrator.execute_step(
                    self.runtime(), self.job(), self.step(), self.identity(), approval=approval)
        record_receipt.assert_not_called()
        commit.assert_not_called()

    def test_volume_and_mute_return_only_verified_state_receipts(self):
        from modules import goal_tools, system_control
        identity = {'owner': 'alice', 'job_id': 'job-1', 'task_id': 's1'}
        with patch.object(system_control, 'set_volume', return_value=True), \
             patch.object(system_control, 'current_volume', return_value=40):
            volume = goal_tools.execute(self.runtime(), 'system',
                                        {'operation': 'volume', 'level': 40}, {}, identity)
        self.assertEqual(volume['receipt'], {'service': 'system_control', 'remote_id': 'volume:40'})
        with patch.object(system_control, 'set_mute', return_value=True), \
             patch.object(system_control, 'is_muted', return_value=True):
            mute = goal_tools.execute(self.runtime(), 'system',
                                      {'operation': 'mute', 'on': True}, {}, identity)
        self.assertEqual(mute['receipt'], {'service': 'system_control', 'remote_id': 'mute:1'})

    def test_brightness_receipt_requires_real_driver_readback(self):
        from modules import goal_tools, system_control
        identity = {'owner': 'alice', 'job_id': 'job-1', 'task_id': 's1'}
        with patch.object(system_control, 'set_brightness', return_value=True), \
             patch.object(system_control, 'brightness_matches', return_value=True):
            output = goal_tools.execute(self.runtime(), 'system',
                                        {'operation': 'brightness', 'level': 70}, {}, identity)
        self.assertEqual(output['receipt'], {'service': 'system_control', 'remote_id': 'brightness:70'})
        with patch.object(system_control, 'set_brightness', return_value=True), \
             patch.object(system_control, 'brightness_matches', return_value=False):
            with self.assertRaisesRegex(ValueError, 'doğrulanamadı'):
                goal_tools.execute(self.runtime(), 'system',
                                   {'operation': 'brightness', 'level': 70}, {}, identity)

    def test_reconcile_reads_matching_volume_without_replaying_effect(self):
        from modules import goal_tools, system_control
        identity = self.identity()
        with patch.object(system_control, 'current_volume', return_value=40) as readback, \
             patch.object(system_control, 'set_volume') as set_volume:
            output = goal_tools.reconcile(
                self.runtime(), 'system', {'operation': 'volume', 'level': 40}, identity, None)
        self.assertTrue(output['reconciled'])
        self.assertEqual(output['receipt'], {'service': 'system_control', 'remote_id': 'volume:40'})
        readback.assert_called_once_with()
        set_volume.assert_not_called()

    def test_goal_executor_versions_only_readback_verifiable_system_operations(self):
        from modules import goal_executor
        job = {**self.job(), 'outputs': {}}
        volume = goal_executor._identity(job, self.step())
        brightness = goal_executor._identity(job, {**self.step(), 'input': {'operation': 'brightness', 'level': 70}})
        media = goal_executor._identity(job, {**self.step(), 'input': {'operation': 'media', 'action': 'next'}})
        self.assertEqual(volume['capability'], 'system')
        self.assertEqual(volume['risk'], 'local_destructive')
        self.assertFalse(volume['replay_safe'])
        self.assertEqual(brightness['capability'], 'system')
        self.assertNotIn('version', media)

    def test_brightness_match_requires_every_reported_display_to_match(self):
        from modules import system_control
        fake = SimpleNamespace(get_brightness=lambda: [70, 70])
        with patch.dict(sys.modules, {'screen_brightness_control': fake}):
            self.assertTrue(system_control.brightness_matches(70))
        mismatch = SimpleNamespace(get_brightness=lambda: [70, 69])
        with patch.dict(sys.modules, {'screen_brightness_control': mismatch}):
            self.assertFalse(system_control.brightness_matches(70))

    def test_direct_brightness_intent_does_not_claim_success_without_readback(self):
        from modules import engine_intents
        control = SimpleNamespace(set_brightness_verified=lambda _level: False,
                                  session_state_memory=lambda: None)
        runtime = SimpleNamespace(system_control=control, _session=lambda: SimpleNamespace(pending_level=None))
        output = engine_intents.dispatch(
            runtime, 'level_set', {'property': 'brightness', 'level': 70},
            'Parlaklığı 70 yap', 'parlaklığı 70 yap')
        self.assertEqual(output, 'Ekran parlaklığını doğrulayamadım.')

    def test_close_app_grammar_proposes_confirmation_without_closing(self):
        """The surviving owner asks for approval and never touches a window."""
        for text, proposed in (
                ('Not Defteri kapat', {'action': 'close_app', 'name': 'not defteri'}),
                ('Paint kapatsana', {'action': 'close_app', 'name': 'paint'})):
            with self.subTest(text=text):
                session = SimpleNamespace(pending_confirm=None)
                result = self.branch(text, session)
                self.assertIn('kaydedilmemiş', result)
                self.assertEqual(session.pending_confirm, proposed)

        for text in ('Sesi kapat', 'Müziği kapat', 'Bilgisayarı kapat', 'Ekranı kapat'):
            with self.subTest(text=text):
                session = SimpleNamespace(pending_confirm=None)
                self.assertIsNone(self.branch(text, session))
                self.assertIsNone(session.pending_confirm)

    def test_close_app_proposal_keeps_the_effect_in_the_approval_branch(self):
        """Closing belongs only to the approval branch tested in test_confirmation_safety."""
        _, fn = self.proposal_branch()
        self.assertNotIn('close_application', ast.unparse(fn))

    def proposal_branch(self):
        handle = next(node for node in engine_source.tree().body
                      if isinstance(node, ast.FunctionDef) and node.name == 'handle')
        start = next(i for i, item in enumerate(handle.body) if isinstance(item, ast.Assign)
                     and any(getattr(target, 'id', '') == 'cm' for target in item.targets))
        end = next(i for i, item in enumerate(handle.body[start:], start)
                   if isinstance(item, ast.If) and "'close_app'" in ast.unparse(item))
        body = handle.body[start:end + 1] + [ast.Return(value=ast.Constant(value=None))]
        fn = ast.FunctionDef(name='close_app_proposal', args=ast.arguments(
            posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
            body=body, decorator_list=[])
        return body, ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))

    def branch(self, text, session):
        module = self.proposal_branch()[1]
        namespace = {'re': re, 'cmd_lower': text.lower(), '_session': lambda: session}
        exec(compile(module, 'real-close-app-grammar', 'exec'), namespace)
        return namespace['close_app_proposal']()

    def test_brightness_verified_requires_set_then_exact_readback(self):
        from modules import system_control
        with patch.object(system_control, 'set_brightness', return_value=True) as set_value, \
             patch.object(system_control, 'brightness_matches', return_value=True) as readback:
            self.assertTrue(system_control.set_brightness_verified(70))
        set_value.assert_called_once_with(70)
        readback.assert_called_once_with(70)
        with patch.object(system_control, 'set_brightness', return_value=False), \
             patch.object(system_control, 'brightness_matches') as readback:
            self.assertFalse(system_control.set_brightness_verified(70))
        readback.assert_not_called()


if __name__ == '__main__':
    unittest.main()
