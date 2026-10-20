from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from modules import llm, permission_policy, tool_cad, tool_contract, tool_slicer


class LocalToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        token = llm._key_context.set('alice')
        self.addCleanup(llm._key_context.reset, token)
        p = patch.object(permission_policy, 'ROOT', self.root / 'policy')
        p.start()
        self.addCleanup(p.stop)

    def test_contract_discovery_and_missing_program_is_explicit(self):
        for module in (tool_slicer, tool_cad):
            self.assertEqual(tool_contract.validate(module.CONTRACT), [])
            self.assertIn(module.CONTRACT['id'], tool_contract.load_all())
            with patch.object(tool_slicer.shutil, 'which', return_value=None), patch.object(tool_slicer.subprocess, 'Popen') as spawn:
                self.assertIn('kurulu değil', module.status()['detail'])
                result = module.run('alice', str(self.root / 'input.stl'), str(self.root / 'output.gcode'), approve=True)
                self.assertEqual(result['state'], 'not_connected')
                self.assertIn('kurulu değil', result['detail'])
                spawn.assert_not_called()

    def test_deny_and_unknown_owner_do_not_spawn(self):
        for module in (tool_slicer, tool_cad):
            permission_policy.set('alice', module.CONTRACT['id'], 'local_destructive', 'deny')
            with patch.object(tool_slicer.subprocess, 'Popen') as spawn:
                self.assertEqual(module.run('alice', 'input', 'output', approve=True)['state'], 'blocked')
                self.assertEqual(module.run('bob', 'input', 'output', approve=True)['state'], 'blocked')
                spawn.assert_not_called()

    def test_bounded_argv_no_shell_no_overwrite_and_output_verified(self):
        for module, suffix, out_suffix in ((tool_slicer, '.stl', '.gcode'), (tool_cad, '.scad', '.stl')):
            source = self.root / ('part ; echo SECRET' + suffix)
            source.write_text('fake input')
            destination = self.root / ('result' + out_suffix)
            calls = []

            def spawn(argv, **kwargs):
                calls.append((argv, kwargs))
                self.assertFalse(kwargs['shell'])
                self.assertIn(str(source), argv)
                output = Path(argv[argv.index('--output') + 1] if '--output' in argv else argv[argv.index('-o') + 1])
                process = Mock(returncode=0)
                process.communicate.side_effect = lambda **kw: output.write_text('fake output')
                return process

            with patch.object(tool_slicer.shutil, 'which', return_value='/fake/program'), patch.object(tool_slicer.subprocess, 'Popen', side_effect=spawn):
                self.assertEqual(module.run('alice', str(source), str(destination))['state'], 'approval')
                self.assertEqual(calls, [])
                self.assertEqual(module.run('alice', str(source), str(destination), approve=True)['state'], 'done')
                self.assertEqual(destination.read_text(), 'fake output')
                self.assertEqual(module.run('alice', str(source), str(destination), approve=True)['state'], 'blocked')
                self.assertEqual(len(calls), 1)

    def test_failed_process_never_claims_output_and_policy_errors_close(self):
        source = self.root / 'part.scad'
        source.write_text('cube(1);')
        target = self.root / 'part.stl'
        with patch.object(tool_slicer.shutil, 'which', return_value='/fake/program'), patch.object(tool_slicer.subprocess, 'Popen', return_value=Mock(returncode=1)):
            self.assertEqual(tool_cad.run('alice', str(source), str(target), approve=True)['state'], 'error')
            self.assertFalse(target.exists())
        with patch.object(permission_policy, 'apply', side_effect=OSError('fake')), patch.object(tool_slicer.subprocess, 'Popen') as spawn:
            self.assertEqual(tool_cad.run('alice', str(source), str(target), approve=True)['state'], 'blocked')
            spawn.assert_not_called()

    def test_user_scoped_running_and_cancel_policy(self):
        process = Mock()
        process.poll.return_value = None
        tool_cad._TOOL.jobs['alice'] = process
        self.addCleanup(tool_cad._TOOL.jobs.clear)
        self.assertEqual(tool_cad.status()['state'], 'running')
        permission_policy.set('alice', 'cad', 'local_reversible', 'deny')
        self.assertFalse(tool_cad.cancel()['cancelled'])
        process.terminate.assert_not_called()
        permission_policy.set('alice', 'cad', 'local_reversible', 'ask')
        self.assertTrue(tool_cad.cancel()['cancelled'])
        process.terminate.assert_called_once_with()
        token = llm._key_context.set('bob')
        try:
            self.assertFalse(tool_cad.cancel()['cancelled'])
        finally:
            llm._key_context.reset(token)

    def test_timeout_and_symlink_never_publish_output(self):
        import subprocess
        source, target = self.root / 'part.scad', self.root / 'part.stl'
        source.write_text('cube(1);')
        process = Mock(returncode=-9)
        process.communicate.side_effect = [subprocess.TimeoutExpired('fake', 120), None]
        with patch.object(tool_slicer.shutil, 'which', return_value='/fake/program'), patch.object(tool_slicer.subprocess, 'Popen', return_value=process):
            self.assertEqual(tool_cad.run('alice', str(source), str(target), approve=True)['state'], 'error')
            process.kill.assert_called_once_with()
            self.assertFalse(target.exists())
        alias = self.root / 'alias.scad'
        alias.symlink_to(source)
        with patch.object(tool_slicer.shutil, 'which', return_value='/fake/program'), patch.object(tool_slicer.subprocess, 'Popen') as spawn:
            self.assertEqual(tool_cad.run('alice', str(alias), str(target), approve=True)['state'], 'blocked')
            spawn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
