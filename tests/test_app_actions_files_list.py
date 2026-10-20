import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from modules import app_actions


class FileListMessageTests(unittest.TestCase):
    def run_files(self, rows):
        result = {'files': rows, 'counts': {'all': len(rows)}, 'dir': 'C:\\fake'}
        before = copy.deepcopy(result)
        bridge = Mock()
        bridge.files_list.return_value = result
        profile = SimpleNamespace(slug='alice', data={})
        response = app_actions.run(bridge, profile, 'files_list', {})
        self.assertIs(response['result'], result)
        self.assertEqual(result, before)
        return response['message']

    def test_three_files_are_readable_and_original_result_is_preserved(self):
        message = self.run_files([{'name': name, 'path': 'C:\\fake\\'+name, 'size': 1024, 'mtime': 1792454400, 'private': 'NOT_DISPLAY'} for name in ('rapor.md','tablo.xlsx','not.txt')])
        self.assertTrue(message.startswith('3 dosya var:'))
        for name in ('rapor.md','tablo.xlsx','not.txt'):
            self.assertIn('- '+name, message)
        self.assertNotIn('{"files"', message)
        self.assertNotIn('[{', message)
        self.assertNotIn('NOT_DISPLAY', message)

    def test_fifteen_files_show_ten_and_remaining_count(self):
        message = self.run_files([{'name': f'rapor{i}.md'} for i in range(15)])
        self.assertEqual(sum(line.startswith('- ') for line in message.splitlines()), 10)
        self.assertIn('ve 5 dosya daha', message)
        self.assertNotIn('rapor10.md', message)

    def test_empty_list(self):
        self.assertEqual(self.run_files([]), 'Henüz listelenecek dosya bulamadım.')

    def test_missing_optional_metadata_and_path_fallback(self):
        message = self.run_files([{'path': 'C:\\fake\\rapor.md'}, {'name': 'not.txt', 'size': None, 'mtime': None}])
        self.assertIn('C:\\fake\\rapor.md', message)
        self.assertIn('- not.txt', message)
        self.assertNotIn('None', message)

    def test_tasks_list_message_unchanged(self):
        tasks = [{'id': 1, 'text': 'Örnek'}]
        result = app_actions.run(Mock(), SimpleNamespace(slug='alice', data={'tasks': tasks}), 'tasks_list', {})
        self.assertEqual(result['message'], json.dumps(tasks, ensure_ascii=False, default=str))


if __name__ == '__main__':
    unittest.main()
