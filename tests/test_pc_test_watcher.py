import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'pc_test_watcher.py'
SPEC = importlib.util.spec_from_file_location('pc_test_watcher', MODULE_PATH)
watcher = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(watcher)


class PcTestWatcherTests(unittest.TestCase):
    def test_choose_candidate_skips_already_seen_head(self):
        candidates = [
            {'ref': 'refs/remotes/origin/gpt/new', 'sha': 'bbb', 'time': 2},
            {'ref': 'refs/remotes/origin/gpt/old', 'sha': 'aaa', 'time': 1},
        ]
        seen = {'refs/remotes/origin/gpt/new': 'bbb'}
        self.assertEqual(watcher.choose_candidate(candidates, seen), candidates[1])

    def test_choose_candidate_returns_none_when_all_heads_seen(self):
        candidates = [{'ref': 'refs/remotes/origin/gpt/a', 'sha': 'aaa', 'time': 1}]
        self.assertIsNone(watcher.choose_candidate(candidates, {'refs/remotes/origin/gpt/a': 'aaa'}))

    def test_load_state_tolerates_missing_or_invalid_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'state.json'
            self.assertEqual(watcher.load_state(path), {})
            path.write_text('{bozuk', encoding='utf-8')
            self.assertEqual(watcher.load_state(path), {})

    def test_save_json_is_readable_utf8(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'state.json'
            watcher.save_json(path, {'durum': 'başarılı'})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['durum'], 'başarılı')

    def test_safe_name_does_not_create_nested_path(self):
        self.assertEqual(watcher.safe_name('refs/remotes/origin/gpt/haber-test'), 'gpt_haber-test')

    def test_branch_from_remote_ref(self):
        self.assertEqual(
            watcher.branch_from_ref('refs/remotes/origin/gpt/windows-pc-watcher'),
            'gpt/windows-pc-watcher',
        )

    def test_gh_exe_falls_back_to_program_files(self):
        with tempfile.TemporaryDirectory() as td:
            candidate = Path(td) / 'GitHub CLI' / 'gh.exe'
            candidate.parent.mkdir(parents=True)
            candidate.write_text('', encoding='utf-8')
            with mock.patch.object(watcher.shutil, 'which', return_value=None), mock.patch.dict(
                os.environ, {'ProgramFiles': td}, clear=False
            ):
                self.assertEqual(watcher.gh_exe(), str(candidate))

    def test_real_acceptance_includes_live_news(self):
        command = watcher.acceptance_command(Path('python.exe'))
        self.assertIn('--desktop', command)
        self.assertIn('--news', command)
        self.assertIn('--skip-suite', command)

    def test_pr_comment_only_exposes_selected_acceptance_details(self):
        report = {
            'sha': '1234567890abcdef',
            'status': 'failed',
            'validation': {'exit_code': 0},
            'desktop_acceptance': {
                'checks': [
                    {'check': 'calculator', 'state': 'passed', 'detail': 'Calculator 19'},
                    {'check': 'news_chat_resume', 'state': 'failed', 'detail': '3 geçersiz karar'},
                    {'check': 'local_configuration', 'state': 'informational', 'detail': 'GİZLİ AYAR DETAYI'},
                ]
            },
        }
        body = watcher.pr_comment_body(report)
        self.assertIn('calculator', body)
        self.assertIn('news_chat_resume', body)
        self.assertIn('3 geçersiz karar', body)
        self.assertNotIn('GİZLİ AYAR DETAYI', body)
        self.assertNotIn('Calculator 19', body)


if __name__ == '__main__':
    unittest.main()
