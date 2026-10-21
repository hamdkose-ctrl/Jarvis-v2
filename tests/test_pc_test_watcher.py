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
    def test_choose_candidate_skips_seen_sha(self):
        candidates = [
            {'ref': 'refs/remotes/origin/gpt/new', 'sha': 'bbb', 'time': 2},
            {'ref': 'refs/remotes/origin/gpt/old', 'sha': 'aaa', 'time': 1},
        ]
        seen = {'refs/remotes/origin/gpt/new': 'bbb'}
        self.assertEqual(watcher.choose_candidate(candidates, seen), candidates[1])

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


if __name__ == '__main__':
    unittest.main()
