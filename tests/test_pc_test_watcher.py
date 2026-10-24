import importlib.util
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'pc_test_watcher.py'
WATCHER_BATCH_PATH = MODULE_PATH.with_name('pc_test_watcher.bat')
SPEC = importlib.util.spec_from_file_location('pc_test_watcher', MODULE_PATH)
watcher = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(watcher)


class PcTestWatcherTests(unittest.TestCase):
    def test_continuous_batch_does_not_force_news_acceptance(self):
        batch = WATCHER_BATCH_PATH.read_text(encoding='utf-8').lower()
        self.assertNotIn('pc_test_watcher.py --news', batch)

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

    def test_unresolved_same_sha_is_not_automatically_retried(self):
        candidate = {'ref': 'refs/remotes/origin/gpt/task', 'sha': 'abc', 'time': 1}
        seen = {
            candidate['ref']: {
                'sha': 'abc', 'status': 'pending_retry', 'last_attempt': 100.0
            }
        }
        self.assertIsNone(watcher.choose_candidate([candidate], seen, now=1000.0))

    def test_open_pr_refs_returns_only_open_branch_refs(self):
        listed = mock.Mock(returncode=0, stdout='[{"headRefName":"gpt/current"},{"headRefName":"feature/not-watched"}]')
        with mock.patch.object(watcher, 'gh_exe', return_value='gh'), \
                mock.patch.object(watcher, 'run', return_value=listed) as run:
            refs = watcher.open_pr_refs(Path('repo'))
        self.assertEqual(refs, {
            'refs/remotes/origin/gpt/current',
            'refs/remotes/origin/feature/not-watched',
        })
        self.assertEqual(run.call_args.args[0][:5], ['gh', 'pr', 'list', '--state', 'open'])

    def test_open_pr_refs_fails_closed_without_github_cli(self):
        with mock.patch.object(watcher, 'gh_exe', return_value=None):
            self.assertIsNone(watcher.open_pr_refs(Path('repo')))

    def test_once_considers_only_open_pr_heads(self):
        open_item = {'ref': 'refs/remotes/origin/gpt/open', 'sha': 'open', 'time': 2}
        closed_item = {'ref': 'refs/remotes/origin/gpt/closed', 'sha': 'closed', 'time': 1}
        with mock.patch.object(watcher, 'load_state', return_value={'seen': {}}), \
                mock.patch.object(watcher, 'remote_heads', return_value=[open_item, closed_item]), \
                mock.patch.object(watcher, 'open_pr_refs', return_value={open_item['ref']}), \
                mock.patch.object(watcher, 'choose_candidate', return_value=None) as choose:
            changed = watcher.once(Path('repo'), Path('state.json'), Path('report.json'), 'refs/remotes/origin/gpt/*', desktop=True, news=False)
        self.assertFalse(changed)
        self.assertEqual(choose.call_args.args[0], [open_item])

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

    def test_existing_worktree_is_git_removed_before_filesystem_cleanup(self):
        root = Path('repo'); target = Path('existing-worktree')
        with mock.patch.object(watcher.Path, 'exists', return_value=True), \
                mock.patch.object(watcher, 'remove_worktree') as remove, \
                mock.patch.object(watcher, 'run') as run:
            watcher.add_worktree(root, 'a'*40, target)
        remove.assert_called_once_with(root, target)
        self.assertEqual(run.call_args_list[-1].args[0][:3], ['git', 'worktree', 'add'])

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
