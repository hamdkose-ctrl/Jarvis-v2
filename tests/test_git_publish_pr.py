"""GitHub'a Yükle: değişiklikler main'e değil ayrı jarvis/ dalına gider ve PR açılır.

GitHub API taklittir (gerçek depo/anahtar kullanılmaz); PC'deki gerçek düğme ayrıca denenmelidir.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import git_publish as publish


class FakeGitHub:
    def __init__(self):
        self.calls, self.pulls, self.refs = [], {}, {'main': 'base'}
        self.fail_pr = False

    def __call__(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == 'GET' and path.startswith('/git/ref/heads/'):
            return {'object': {'sha': self.refs[path.rsplit('/heads/', 1)[1]]}}
        if method == 'GET' and path.startswith('/git/commits/'):
            sha = path.rsplit('/', 1)[1]
            return {'tree': {'sha': 'merged-tree' if sha == 'merge1' else 'tree'}, 'message': 'msg'}
        if method == 'GET' and path.startswith('/pulls/'):
            return self.pulls[int(path.rsplit('/', 1)[1])]
        if path == '/git/blobs':
            return {'sha': 'blob'}
        if path == '/git/trees':
            return {'sha': 'newtree'}
        if path == '/git/commits':
            return {'sha': 'c%d' % len(self.calls)}
        if path == '/git/refs':
            self.refs[payload['ref'].removeprefix('refs/heads/')] = payload['sha']
            return {}
        if method == 'PATCH':
            self.refs[path.rsplit('/heads/', 1)[1]] = payload['sha']
            return {}
        if path == '/pulls':
            if self.fail_pr:
                raise RuntimeError('GitHub 403: Resource not accessible')
            self.pulls[7] = {'state': 'open', 'head': {'ref': payload['head']}}
            return {'number': 7, 'html_url': 'https://github.com/o/r/pull/7'}
        raise AssertionError((method, path))


class PublishToPullRequestTests(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGitHub()
        self.files = {'main.py': b'print(1)\n'}
        state = Path(tempfile.mkdtemp())
        for target, name, kwargs in [
            (publish, '_api', {'side_effect': self.gh}), (publish, 'STATE', {'new': state}),
            (publish, 'PR_STATE', {'new': state / 'pr.json'}), (publish, 'LOCAL', {'new': state / 'local.json'}),
            (publish, '_remote_paths', {'return_value': {}}),
            (publish, '_publishable_files', {'side_effect': lambda: self.files}),
            (publish, '_release_tests', {'return_value': None}),
            ('updater.status', None, {'return_value': {'sha': 'base'}}),
            ('modules.dependencies.in_venv', None, {'return_value': False}),
        ]:
            p = patch(target, **kwargs) if name is None else patch.object(target, name, **kwargs)
            p.start(); self.addCleanup(p.stop)
        p = patch('updater.mark_current'); self.mark = p.start(); self.addCleanup(p.stop)

    def writes_to_main(self):
        return [c for c in self.gh.calls if c[0] in ('PATCH', 'POST') and 'heads/main' in str(c[1]) + str(c[2])]

    def test_first_publish_opens_pr_and_never_touches_main(self):
        text = publish.publish_worktree('deneme')
        self.assertEqual(self.writes_to_main(), [])
        self.assertEqual(self.gh.refs['main'], 'base')
        branch = next(k for k in self.gh.refs if k.startswith('jarvis/yukle-'))
        pr = next(c[2] for c in self.gh.calls if c[1] == '/pulls')
        self.assertEqual((pr['head'], pr['base']), (branch, 'main'))
        self.assertIn('`main.py`', pr['body'])
        commit = next(c[2] for c in self.gh.calls if c[1] == '/git/commits')
        self.assertEqual(commit['parents'], ['base'])
        self.mark.assert_not_called()          # taban, PR birleşmeden değişmez
        self.assertIn('PR #7', text)
        self.assertIn('https://github.com/o/r/pull/7', text)
        self.assertIn(branch, text)

    def test_second_publish_updates_the_same_open_pr(self):
        publish.publish_worktree('ilk')
        branch = json.loads(publish.PR_STATE.read_text())['branch']
        first = self.gh.refs[branch]
        self.files = {'main.py': b'print(2)\n', 'web.py': b'x=1\n'}
        text = publish.publish_worktree('ikinci')
        self.assertEqual(sum(c[1] == '/pulls' for c in self.gh.calls), 1)
        patch_call = [c for c in self.gh.calls if c[0] == 'PATCH']
        self.assertEqual(patch_call[-1][1], f'/git/refs/heads/{branch}')
        self.assertFalse(patch_call[-1][2]['force'])
        self.assertEqual([c[2] for c in self.gh.calls if c[1] == '/git/commits'][-1]['parents'], [first])
        self.assertEqual(self.writes_to_main(), [])
        self.assertIn('güncellendi', text)

    def test_closed_pr_gets_a_new_pr(self):
        publish.publish_worktree('ilk')
        self.gh.pulls[7]['state'] = 'closed'
        publish.publish_worktree('yeni')
        self.assertEqual(sum(c[1] == '/pulls' for c in self.gh.calls), 2)
        self.assertEqual(self.writes_to_main(), [])

    def test_pr_failure_reports_branch_and_main_unchanged(self):
        self.gh.fail_pr = True
        with self.assertRaisesRegex(RuntimeError, r"jarvis/yukle-.*PR açılamadı.*main değişmedi"):
            publish.publish_worktree('deneme')
        self.assertEqual(self.gh.refs['main'], 'base')
        self.assertFalse(publish.PR_STATE.exists())

    def test_merged_pr_moves_base_only_when_tree_matches(self):
        publish.PR_STATE.write_text(json.dumps({'number': 7, 'branch': 'jarvis/x', 'tree': 'merged-tree'}))
        self.gh.pulls[7] = {'state': 'closed', 'merged': True, 'merge_commit_sha': 'merge1'}
        self.assertTrue(publish.sync_merged_pr())
        self.mark.assert_called_once_with('merge1', 'msg')
        self.assertFalse(publish.PR_STATE.exists())
        self.mark.reset_mock()
        publish.PR_STATE.write_text(json.dumps({'number': 7, 'branch': 'jarvis/x', 'tree': 'other-tree'}))
        self.assertFalse(publish.sync_merged_pr())     # main arada başka değişiklik aldı: taban değişmez
        self.mark.assert_not_called()

    def test_open_or_unmerged_pr_does_not_move_base(self):
        publish.PR_STATE.write_text(json.dumps({'number': 7, 'branch': 'jarvis/x', 'tree': 'merged-tree'}))
        self.gh.pulls[7] = {'state': 'open'}
        self.assertFalse(publish.sync_merged_pr())
        self.assertTrue(publish.PR_STATE.exists())
        self.gh.pulls[7] = {'state': 'closed', 'merged': False}
        self.assertFalse(publish.sync_merged_pr())
        self.assertFalse(publish.PR_STATE.exists())
        self.mark.assert_not_called()

    def test_verify_sync_adopts_merged_pr_first(self):
        import updater
        with patch.object(publish, 'sync_merged_pr', side_effect=RuntimeError('GitHub bağlantısı kurulamadı')) as sync, \
                patch.object(updater, 'latest', return_value=None), patch.object(updater, '_save_state'):
            self.assertEqual(updater.verify_sync()['sync_state'], 'offline')
        sync.assert_called_once()

    def test_no_code_path_writes_main_ref(self):
        src = Path(publish.__file__).read_text(encoding='utf-8')
        self.assertNotIn('/git/refs/heads/{updater.BRANCH}', src)


if __name__ == '__main__':
    unittest.main()
