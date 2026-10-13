import unittest
from unittest.mock import patch
from modules import git_publish as publish


class PublishBatchTests(unittest.TestCase):
    def test_120_files_publish_in_one_commit_without_force(self):
        files = {f'webui/file{i}.js': b'const value=1;' for i in range(120)}
        def api(method, path, payload=None):
            if path.startswith('/git/ref/'): return {'object': {'sha': 'base'}}
            if method == 'GET': return {'tree': {'sha': 'tree'}, 'message': 'old'}
            return {'sha': 'new'}
        with patch.object(publish, '_api', side_effect=api) as remote, \
             patch('updater.status', return_value={'sha': 'base'}), \
             patch('modules.dependencies.in_venv', return_value=False), \
             patch.object(publish, '_remote_paths', return_value={}), \
             patch.object(publish, '_publishable_files', return_value=files), \
             patch.object(publish, '_release_tests') as tests, \
             patch.object(publish, 'forget_local'), patch('updater.mark_current'):
            result = publish.publish_worktree('test')
        self.assertIn('120 dosya', result)
        tests.assert_called_once()
        self.assertEqual(remote.call_args.args[2]['force'], False)
        self.assertEqual(sum(c.args[1] == '/git/commits' for c in remote.call_args_list), 1)
