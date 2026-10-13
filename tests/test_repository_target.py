import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import updater
from modules import git_publish


class RepositoryTargetTests(unittest.TestCase):
    def test_repository_state_is_independent_of_old_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=root/'update.json'
            old.write_text(json.dumps({'sha':'old-repository-commit'}))
            with patch.object(updater,'DATA',root),patch.object(updater,'STATE',root/updater.STATE.name):
                self.assertEqual(updater._state(),{})
                updater.mark_current('verified-new-commit','new repository')
                self.assertEqual(updater._state()['sha'],'verified-new-commit')
            self.assertEqual(json.loads(old.read_text())['sha'],'old-repository-commit')

    def test_read_and_write_use_same_new_repository(self):
        self.assertEqual(updater.REPO,'hamdkose-ctrl/Jarvis-v2')
        self.assertEqual(updater.STATE.name,'update-Jarvis-v2.json')
        response=unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value=b'{}'
        with patch.object(updater,'_token',return_value='fake'),patch.object(git_publish.urllib.request,'urlopen',return_value=response) as open_:
            git_publish._api('GET','/git/ref/heads/main')
        self.assertEqual(open_.call_args.args[0].full_url,'https://api.github.com/repos/hamdkose-ctrl/Jarvis-v2/git/ref/heads/main')
