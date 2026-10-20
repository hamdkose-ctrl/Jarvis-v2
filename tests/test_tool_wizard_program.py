from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from modules import llm, permission_policy, tool_contract, tool_wizard


class WizardProgramTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        token = llm._key_context.set('alice')
        self.addCleanup(llm._key_context.reset, token)
        for module, directory in ((tool_wizard, 'wizard'), (permission_policy, 'policy')):
            p = patch.object(module, 'ROOT', Path(self.tmp.name) / directory)
            p.start()
            self.addCleanup(p.stop)
        self.program = str(Path(sys.executable).resolve())

    def add(self, **kwargs):
        return tool_wizard.add_program('alice', 'Yerel test', self.program, ['-c', 'import sys; print(sys.argv[1])', '{text}'], **kwargs)

    def test_explicit_approval_conservative_default_and_user_selected_class(self):
        self.assertEqual(self.add()['state'], 'approval')
        self.assertEqual(tool_wizard.contracts('alice'), {})
        ident = self.add(confirmed=True)['id']
        contract = tool_contract.load_all()[ident]
        self.assertEqual(contract['actions'][0]['class'], 'local_destructive')
        with patch('subprocess.Popen') as spawn:
            self.assertEqual(tool_wizard.execute('alice', ident, {'text': 'hello'})['state'], 'approval')
            spawn.assert_not_called()
        selected = self.add(action_class='read', confirmed=True)['id']
        self.assertEqual(tool_contract.load_all()[selected]['actions'][0]['class'], 'read')

    def test_literal_shell_characters_and_actual_local_process(self):
        ident = self.add(confirmed=True)['id']
        text = 'hello; $(touch impossible) `echo hidden` & | >'
        result = tool_wizard.execute('alice', ident, {'text': text}, approve=True)
        self.assertEqual(result['state'], 'done')
        self.assertEqual(result['data']['text'].strip(), text)
        self.assertFalse(result['data']['truncated'])
        with patch.object(tool_wizard.subprocess, 'Popen') as spawn:
            process = Mock(returncode=0)
            spawn.return_value = process
            self.assertEqual(tool_wizard.execute('alice', ident, {'text': text}, approve=True)['state'], 'done')
            self.assertFalse(spawn.call_args.kwargs['shell'])
            self.assertEqual(spawn.call_args.args[0][-1], text)

    def test_locked_classes_bad_templates_and_missing_program_rejected(self):
        for cls in ('money_credential', 'system_config', 'unknown'):
            with self.assertRaises(ValueError):
                self.add(action_class=cls, confirmed=True)
        for args in ('one string', ['{text.__class__}'], ['{text[0]}'], ['{missing'], ['\x00']):
            with self.assertRaises(ValueError):
                tool_wizard.add_program('alice', 'Test', self.program, args, confirmed=True)
        with self.assertRaisesRegex(ValueError, 'kurulu değil'):
            tool_wizard.add_program('alice', 'Test', str(Path(self.tmp.name) / 'missing'), [], confirmed=True)
        self.assertEqual(tool_wizard.contracts('alice'), {})

    def test_policy_owner_and_parameter_failures_never_spawn(self):
        ident = self.add(confirmed=True)['id']
        permission_policy.set('alice', ident, 'local_destructive', 'deny')
        with patch.object(tool_wizard.subprocess, 'Popen') as spawn:
            self.assertEqual(tool_wizard.execute('alice', ident, {'text': 'x'}, approve=True)['state'], 'blocked')
            self.assertEqual(tool_wizard.execute('bob', ident, {'text': 'x'}, approve=True)['state'], 'blocked')
            spawn.assert_not_called()

    def test_running_cancel_timeout_exit_error_and_output_bound(self):
        import subprocess
        ident = self.add(confirmed=True)['id']
        process = Mock(returncode=0)
        process.poll.return_value = None
        tool_wizard._RUNNING[('alice', ident)] = process
        self.addCleanup(tool_wizard._RUNNING.clear)
        contract = tool_contract.load_all()[ident]
        self.assertEqual(contract['status']()['state'], 'running')
        self.assertTrue(contract['cancel']()['cancelled'])
        process.terminate.assert_called_once_with()
        tool_wizard._RUNNING.clear()
        timed = Mock(returncode=-9)
        timed.communicate.side_effect = [subprocess.TimeoutExpired('fake', 120), None]
        timed.poll.return_value = -9
        with patch.object(tool_wizard.subprocess, 'Popen', return_value=timed):
            self.assertEqual(tool_wizard.execute('alice', ident, {'text': 'x'}, approve=True)['state'], 'error')
            timed.kill.assert_called_once_with()
        with patch.object(tool_wizard.subprocess, 'Popen', return_value=Mock(returncode=7)):
            self.assertEqual(tool_wizard.execute('alice', ident, {'text': 'x'}, approve=True)['state'], 'error')
        large = tool_wizard.add_program('alice', 'Large', self.program, ['-c', 'print("x"*25000)'], confirmed=True)['id']
        result = tool_wizard.execute('alice', large, {}, approve=True)
        self.assertTrue(result['data']['truncated'])
        self.assertEqual(len(result['data']['text']), 20000)

    def test_invalid_parameters_never_spawn(self):
        ident = self.add(confirmed=True)['id']
        permission_policy.set('alice', ident, 'local_destructive', 'ask')
        with patch.object(tool_wizard.subprocess, 'Popen') as spawn:
            for parameters in ({}, {'text': 'x', 'extra': 'x'}, {'text': '\x00'}):
                self.assertEqual(tool_wizard.execute('alice', ident, parameters, approve=True)['state'], 'blocked')
            spawn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
