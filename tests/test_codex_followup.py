import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'codex_followup.py'
SPEC = importlib.util.spec_from_file_location('codex_followup', MODULE_PATH)
followup = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(followup)


class CodexFollowupTests(unittest.TestCase):
    def test_codex_exe_falls_back_to_local_appdata(self):
        with tempfile.TemporaryDirectory() as td:
            candidate = Path(td) / 'Programs' / 'OpenAI' / 'Codex' / 'bin' / 'codex.exe'
            candidate.parent.mkdir(parents=True)
            candidate.write_text('', encoding='utf-8')
            with mock.patch.object(followup.shutil, 'which', return_value=None), mock.patch.dict(
                os.environ, {'LOCALAPPDATA': td}, clear=False
            ):
                self.assertEqual(followup.codex_exe(), str(candidate))

    def test_followup_uses_terra_and_windows_git_capable_sandbox(self):
        completed = mock.Mock(returncode=0, stdout='done', stderr='')
        with mock.patch.object(followup, 'codex_exe', return_value='codex.exe'), mock.patch.object(
            followup.subprocess, 'run', return_value=completed
        ) as run_mock:
            result = followup.run_followup(Path('repo'), 'refs/remotes/origin/gpt/task', 'abc123', 'failed')
        self.assertEqual(result['state'], 'completed')
        command = run_mock.call_args.args[0]
        self.assertEqual(command[:8], [
            'codex.exe', '-m', 'gpt-5.6-terra', '-c', "windows.sandbox='unelevated'",
            'exec', '--sandbox', 'danger-full-access'
        ])
        prompt = command[-1]
        self.assertIn('.venv\\Scripts\\python.exe -X utf8 -m modules.validation', prompt)
        self.assertIn('do not write directly to main', prompt.lower())

    def test_followup_classifies_quota_failure_as_pending(self):
        limited = mock.Mock(returncode=1, stdout='', stderr='HTTP 429: rate limit exceeded, try again later')
        with mock.patch.object(followup, 'codex_exe', return_value='codex.exe'), mock.patch.object(
            followup.subprocess, 'run', return_value=limited
        ):
            result = followup.run_followup(Path('repo'), 'refs/remotes/origin/gpt/task', 'abc123', 'failed')
        self.assertEqual(result['state'], 'pending_quota')
        self.assertEqual(result['reason'], 'quota_or_rate_limit')

    def test_non_quota_failure_stays_failed(self):
        failed = mock.Mock(returncode=2, stdout='bad patch', stderr='syntax error')
        with mock.patch.object(followup, 'codex_exe', return_value='codex.exe'), mock.patch.object(
            followup.subprocess, 'run', return_value=failed
        ):
            result = followup.run_followup(Path('repo'), 'refs/remotes/origin/gpt/task', 'abc123', 'failed')
        self.assertEqual(result['state'], 'failed')


if __name__ == '__main__':
    unittest.main()
