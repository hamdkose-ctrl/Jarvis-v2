import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


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


if __name__ == '__main__':
    unittest.main()
