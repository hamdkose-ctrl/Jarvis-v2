import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from modules import validation, developer, git_publish

class ValidationTests(unittest.TestCase):
    def test_developer_and_github_use_same_runner_and_fail_closed(self):
        with patch.object(validation, 'run_checks', return_value=(False, 'missing JS')) as run:
            self.assertEqual(developer._test(), (False, 'missing JS'))
            with self.assertRaisesRegex(RuntimeError, 'missing JS'):
                git_publish._release_tests()
            self.assertEqual(run.call_count, 2)

    def test_missing_node_prevents_partial_success(self):
        with patch.object(validation.shutil, 'which', return_value=None), patch.object(validation.Path, 'is_file', return_value=False), patch.object(validation.subprocess, 'run') as run:
            ok, log = validation.run_checks()
        self.assertFalse(ok); self.assertIn('Node.js', log); run.assert_not_called()

    def test_all_groups_use_distinct_temporary_data_and_any_failure_stops(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'tests').mkdir(); (root / 'webui').mkdir()
            for name in validation.JS_GROUPS: (root / 'tests' / (name + '.js')).write_text('')
            for name in validation.SMOKE_GROUPS: (root / 'tests' / (name + '.py')).write_text('')
            environments = []
            def run(cmd, **kwargs):
                environments.append(kwargs['env']['JARVIS_DATA_DIR'])
                is_python_suite = 'unittest' in cmd
                return SimpleNamespace(returncode=0, stdout='Ran 1 test\nOK\n' if is_python_suite else '', stderr='')
            with patch.object(validation.shutil, 'which', return_value='node'), patch.object(validation.subprocess, 'run', side_effect=run):
                ok, log = validation.run_checks(root)
            self.assertTrue(ok)
            self.assertEqual(len(environments), 2 + len(validation.JS_GROUPS) + len(validation.SMOKE_GROUPS))
            self.assertEqual(len(environments), len(set(environments)))
            self.assertTrue(all(not Path(p).exists() for p in environments))
            with patch.object(validation.shutil, 'which', return_value='node'), patch.object(validation.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='', stderr='failure')):
                self.assertFalse(validation.run_checks(root)[0])

    def test_empty_unittest_run_is_not_success(self):
        with patch.object(validation.shutil, 'which', return_value='node'), patch.object(validation.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='Ran 0 tests\nOK', stderr='')):
            ok, log = validation.run_checks()
        self.assertFalse(ok); self.assertIn('çalışmadı', log)

    def test_python_test_timeout_is_generous_and_overridable(self):
        calls = []
        def fake_run(cmd, **kw):
            calls.append(kw.get('timeout'))
            return SimpleNamespace(returncode=0, stdout='Ran 1 test\nOK', stderr='')
        with patch.object(validation.shutil, 'which', return_value='node'), patch.object(validation.subprocess, 'run', side_effect=fake_run):
            validation.run_checks()
        self.assertEqual(calls[0], 90)               # Architecture Guard kısa/statik adımdır
        self.assertGreaterEqual(calls[1], 600)       # Windows runner 180 sn'ye yaklaşıp düşüyordu
        self.assertEqual(set(calls[2:]), {90})
        with patch.dict(validation.os.environ, {'JARVIS_VALIDATION_TIMEOUT': '900'}):
            self.assertEqual(validation.python_timeout(), 900)
        with patch.dict(validation.os.environ, {'JARVIS_VALIDATION_TIMEOUT': 'x'}):
            self.assertEqual(validation.python_timeout(), 600)
