import importlib.util
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'pc_test_watcher.py'
SPEC = importlib.util.spec_from_file_location('pc_test_watcher', MODULE_PATH)
watcher = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(watcher)


class PcTestWatcherTests(unittest.TestCase):
    def test_choose_candidate_skips_resolved_sha(self):
        candidates = [
            {'ref': 'refs/remotes/origin/gpt/new', 'sha': 'bbb', 'time': 2},
            {'ref': 'refs/remotes/origin/gpt/old', 'sha': 'aaa', 'time': 1},
        ]
        seen = {
            'refs/remotes/origin/gpt/new': {
                'sha': 'bbb', 'status': 'passed', 'last_attempt': 100.0
            }
        }
        self.assertEqual(watcher.choose_candidate(candidates, seen, now=200.0), candidates[1])

    def test_legacy_seen_sha_is_rechecked_once(self):
        candidate = {'ref': 'refs/remotes/origin/gpt/task', 'sha': 'abc', 'time': 1}
        seen = {candidate['ref']: candidate['sha']}
        self.assertEqual(watcher.choose_candidate([candidate], seen, now=1000.0), candidate)

    def test_unresolved_same_sha_waits_then_retries(self):
        candidate = {'ref': 'refs/remotes/origin/gpt/task', 'sha': 'abc', 'time': 1}
        seen = {
            candidate['ref']: {
                'sha': 'abc', 'status': 'pending_retry', 'last_attempt': 100.0
            }
        }
        self.assertIsNone(watcher.choose_candidate([candidate], seen, now=500.0, retry_seconds=900))
        self.assertEqual(watcher.choose_candidate([candidate], seen, now=1000.0, retry_seconds=900), candidate)

    def test_new_sha_runs_even_if_previous_sha_passed(self):
        candidate = {'ref': 'refs/remotes/origin/gpt/task', 'sha': 'new', 'time': 2}
        seen = {
            candidate['ref']: {
                'sha': 'old', 'status': 'passed', 'last_attempt': 100.0
            }
        }
        self.assertEqual(watcher.choose_candidate([candidate], seen, now=101.0), candidate)

    def test_suite_reports_missing_venv_without_running_another_python(self):
        with mock.patch.object(watcher, 'python_exe', return_value=None), \
                mock.patch.object(watcher, 'run') as run:
            result = watcher.run_suite(Path('repo'), Path('worktree'), 'ref', 'a'*40, desktop=True, news=False)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['validation']['exit_code'], 2)
        self.assertIn('.venv\\Scripts\\python.exe', result['validation']['tail'])
        run.assert_not_called()

    def test_normal_suite_does_not_run_news(self):
        validation = mock.Mock(returncode=0, stdout='OK')
        desktop = {'exit_code': 0, 'tail': '', 'checks': [{'check': 'calculator', 'state': 'passed'}]}
        with mock.patch.object(watcher, 'python_exe', return_value=Path('python.exe')), \
                mock.patch.object(watcher, 'run', return_value=validation), \
                mock.patch.object(watcher, 'run_acceptance', return_value=desktop) as acceptance:
            result = watcher.run_suite(Path('repo'), Path('worktree'), 'ref', 'a'*40, desktop=True, news=False)
        self.assertEqual(result['status'], 'passed')
        acceptance.assert_called_once_with(Path('python.exe'), Path('worktree'), '--desktop')
        self.assertNotIn('news_acceptance', result)

    def test_news_is_separate_final_gate(self):
        validation = mock.Mock(returncode=0, stdout='OK')
        desktop = {'exit_code': 0, 'tail': '', 'checks': [{'check': 'calculator', 'state': 'passed'}]}
        news = {'exit_code': 1, 'tail': 'news failed', 'checks': [{'check': 'news_chat_resume', 'state': 'failed'}]}
        with mock.patch.object(watcher, 'python_exe', return_value=Path('python.exe')), \
                mock.patch.object(watcher, 'run', return_value=validation), \
                mock.patch.object(watcher, 'run_acceptance', side_effect=[desktop, news]):
            result = watcher.run_suite(Path('repo'), Path('worktree'), 'ref', 'a'*40, desktop=True, news=True)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['news_acceptance']['exit_code'], 1)

    def test_validation_failure_never_starts_desktop_or_news_acceptance(self):
        validation = mock.Mock(returncode=1, stdout='validation failed')
        with mock.patch.object(watcher, 'python_exe', return_value=Path('python.exe')), \
                mock.patch.object(watcher, 'run', return_value=validation), \
                mock.patch.object(watcher, 'run_acceptance') as acceptance:
            result = watcher.run_suite(Path('repo'), Path('worktree'), 'ref', 'a'*40, desktop=True, news=True)
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('desktop_acceptance', result)
        self.assertNotIn('news_acceptance', result)
        acceptance.assert_not_called()

    def test_desktop_exit_zero_without_calculator_evidence_fails_suite(self):
        validation = mock.Mock(returncode=0, stdout='OK')
        desktop = {'exit_code': 0, 'tail': 'incomplete', 'checks': []}
        with mock.patch.object(watcher, 'python_exe', return_value=Path('python.exe')), \
                mock.patch.object(watcher, 'run', return_value=validation), \
                mock.patch.object(watcher, 'run_acceptance', return_value=desktop):
            result = watcher.run_suite(Path('repo'), Path('worktree'), 'ref', 'a'*40, desktop=True, news=False)
        self.assertEqual(result['status'], 'failed')

    def test_news_exit_zero_without_required_evidence_fails_suite_and_comment(self):
        validation = mock.Mock(returncode=0, stdout='OK')
        desktop = {'exit_code': 0, 'tail': '', 'checks': [{'check':'calculator', 'state':'passed'}]}
        news = {'exit_code': 0, 'tail': 'incomplete', 'checks': []}
        with mock.patch.object(watcher, 'python_exe', return_value=Path('python.exe')), \
                mock.patch.object(watcher, 'run', return_value=validation), \
                mock.patch.object(watcher, 'run_acceptance', side_effect=[desktop, news]):
            result = watcher.run_suite(Path('repo'), Path('worktree'), 'ref', 'a'*40, desktop=True, news=True)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('Haber: **failed**', watcher.pr_comment_body(result))


    def test_pr_comment_reports_only_blocks_that_ran(self):
        report = {
            'sha': 'b' * 40,
            'status': 'failed',
            'validation': {'exit_code': 1, 'tail': 'traceback'},
            'desktop_acceptance': {'exit_code': 0, 'tail': 'ok', 'checks': [{'check':'calculator','state':'passed'}]},
        }
        body = watcher.pr_comment_body(report)
        self.assertIn('Validation: **failed**', body)
        self.assertIn('Desktop: **passed**', body)
        self.assertNotIn('Haber', body)
        self.assertNotIn('traceback', body)

    def test_pr_comment_does_not_call_desktop_passed_without_calculator_evidence(self):
        report = {
            'sha': 'c' * 40,
            'status': 'failed',
            'validation': {'exit_code': 0, 'tail': 'ok'},
            'desktop_acceptance': {'exit_code': 0, 'tail': 'ok', 'checks': []},
        }
        self.assertIn('Desktop: **failed**', watcher.pr_comment_body(report))


if __name__ == '__main__':
    unittest.main()
