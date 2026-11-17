"""Button-only Brain role qualification: subprocess contract, progress mirror, fail-closed status."""
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import role_qualification
from web_models import WebModels


class FakeProc:
    def __init__(self, lines):
        self.stdout = iter(lines)

    def wait(self):
        return 0


class RoleQualificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = patch.object(role_qualification.config, 'DATA_DIR', Path(self.tmp.name))
        self.data.start()
        self.addCleanup(self.data.stop)
        for key, value in (('running', False), ('done', 0), ('total', 0), ('error', ''), ('last_state', '')):
            role_qualification._state[key] = value
        self.targets = []
        self.thread = patch.object(role_qualification.threading, 'Thread',
                                   side_effect=lambda **kw: self.targets.append(kw['target']) or Mock())
        self.thread.start()
        self.addCleanup(self.thread.stop)

    def candidate(self):
        return SimpleNamespace(provider='gemini', model='gemini-3.5-flash-lite',
                               connection_id=None, binding='b-1', connection_revision=3)

    def gate(self, qualified=True):
        return patch('modules.router_quota.role_qualified', return_value=qualified)

    def test_qualified_uses_the_same_identity_the_runtime_gate_checks(self):
        with patch('modules.llm.current_user', return_value='hamdi'), \
                patch('modules.smart_router.qualification_candidate', return_value=self.candidate()) as cand, \
                patch('modules.smart_router._role_fingerprint', return_value='fp-9') as fp, self.gate() as q:
            self.assertTrue(role_qualification.status()['qualified'])
            cand.assert_called_once_with('hamdi')
            fp.assert_called_once_with()
        args, kwargs = q.call_args
        self.assertEqual(args, ('hamdi', 'gemini', 'gemini-3.5-flash-lite', None))
        self.assertEqual(kwargs['fingerprint'], 'fp-9')
        self.assertEqual(kwargs['binding'], 'b-1')

    def test_status_check_failure_is_not_qualified(self):
        with patch('modules.llm.current_user', side_effect=RuntimeError('no profile')):
            self.assertFalse(role_qualification.status()['qualified'])

    def test_no_active_user_is_not_qualified_without_touching_the_row_store(self):
        with patch('modules.llm.current_user', return_value=''), self.gate() as q:
            self.assertFalse(role_qualification.status()['qualified'])
            q.assert_not_called()

    def test_prepare_runs_only_the_standard_free_holdout_command(self):
        argv = {}

        def popen(cmd, **kwargs):
            argv['cmd'] = cmd
            argv['kwargs'] = kwargs
            return FakeProc([])

        with patch.object(role_qualification.subprocess, 'Popen', side_effect=popen):
            self.assertTrue(role_qualification.prepare()['started'])
            self.targets[0]()
        cmd = argv['cmd']
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn('--run', cmd)
        self.assertEqual(cmd[-2:], ['--json', str(role_qualification.report_path())])
        for forbidden in ('--accept-paid', '--qualify-connection', '--qualify-local'):
            self.assertNotIn(forbidden, cmd)
        script = Path(cmd[-4])
        self.assertEqual((script.parent.name, script.name), ('scripts', 'brain_output_diagnose_holdout.py'))
        self.assertEqual(argv['kwargs']['cwd'], str(Path(role_qualification.__file__).resolve().parents[1]))

    def test_progress_mirrors_the_script_and_report_verdict_is_shown(self):
        report = {'state': 'unmeasured', 'cases': 11, 'stop_reason': 'provider_no_response'}
        path = role_qualification.report_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        def popen(cmd, **kwargs):
            path.write_text(json.dumps(report), encoding='utf-8')
            return FakeProc([f'Semantic case {i}/20\n' for i in range(1, 13)])

        with patch.object(role_qualification.subprocess, 'Popen', side_effect=popen):
            role_qualification.prepare()
            self.assertTrue(role_qualification.status()['running'])
            self.targets[0]()
        st = role_qualification.status()
        self.assertFalse(st['running'])
        self.assertEqual(st['last_state'], 'unmeasured')
        self.assertEqual(st['done'], 11)
        self.assertIn('provider_no_response', st['error'])

    def test_passed_report_shows_no_error_and_keeps_progress_full(self):
        path = role_qualification.report_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        def popen(cmd, **kwargs):
            path.write_text(json.dumps({'state': 'passed', 'cases': 20, 'planned_cases': 20}), encoding='utf-8')
            return FakeProc([f'Semantic case {i}/20\n' for i in range(1, 21)])

        with patch.object(role_qualification.subprocess, 'Popen', side_effect=popen):
            role_qualification.prepare()
            self.targets[0]()
        st = role_qualification.status()
        self.assertEqual(st['last_state'], 'passed')
        self.assertEqual(st['error'], '')
        self.assertEqual(st['done'], 19)

    def test_missing_report_is_unmeasured_never_a_silent_pass(self):
        with patch.object(role_qualification.subprocess, 'Popen', return_value=FakeProc([])):
            role_qualification.prepare()
            self.targets[0]()
        st = role_qualification.status()
        self.assertEqual(st['last_state'], 'unmeasured')
        self.assertIn('okunamadı', st['error'])

    def test_launch_failure_reports_only_the_exception_type(self):
        with patch.object(role_qualification.subprocess, 'Popen', side_effect=OSError('secret path text')):
            role_qualification.prepare()
            self.targets[0]()
        st = role_qualification.status()
        self.assertIn('OSError', st['error'])
        self.assertNotIn('secret', st['error'])
        self.assertFalse(st['running'])

    def test_second_prepare_is_ignored_while_running(self):
        with patch.object(role_qualification.subprocess, 'Popen', return_value=FakeProc([])) as popen:
            self.assertTrue(role_qualification.prepare()['started'])
            self.assertFalse(role_qualification.prepare()['started'])
            self.assertFalse(role_qualification.prepare()['started'])
            self.assertEqual(len(self.targets), 1)
            popen.assert_not_called()

    def test_prepare_allows_a_new_run_after_the_previous_one_finished(self):
        with patch.object(role_qualification.subprocess, 'Popen', return_value=FakeProc([])):
            role_qualification.prepare()
            self.targets[0]()                      # no report file: run ends as unmeasured
            self.assertTrue(role_qualification.prepare()['started'])
            self.assertEqual(len(self.targets), 2)

    def test_bridge_only_delegates(self):
        bridge = WebModels()
        bridge._runtime = SimpleNamespace()
        with patch.object(role_qualification, 'status', return_value={'qualified': True}) as status, \
                patch.object(role_qualification, 'prepare', return_value={'started': True}) as prepare:
            self.assertEqual(bridge.role_qualification_status(), {'qualified': True})
            self.assertEqual(bridge.role_qualification_prepare(), {'started': True})
            status.assert_called_once_with()
            prepare.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
