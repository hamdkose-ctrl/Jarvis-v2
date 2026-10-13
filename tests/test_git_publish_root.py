import unittest
import tempfile
from unittest.mock import patch
from pathlib import Path
from modules import git_publish
import updater


class PublishRootTests(unittest.TestCase):
    def test_sync_excludes_installer_environments_private_files_and_models(self):
        blocked = ['.venv_install/Lib/site-packages/pkg/config.json',
                   '.venv_backup/Lib/pkg.py', '.jarvis/users/hamdi.json',
                   '.claude/settings.json', 'models/stt/small/config.json',
                   '.env.json', 'kurulum.log', 'settings.json']
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in blocked + ['main.py', '.gitignore', '.gitattributes', 'settings.example.json']:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('example', encoding='utf-8')
            with patch.object(git_publish, 'ROOT', root):
                self.assertEqual(set(git_publish._publishable_files()),
                                 {'main.py', '.gitignore', '.gitattributes', 'settings.example.json'})
        for name in blocked:
            self.assertFalse(updater._publishable_path(name), name)
        for name in ['main.py', '.gitignore', '.gitattributes', 'settings.example.json']:
            self.assertTrue(updater._publishable_path(name), name)

    def test_publish_and_update_use_same_project_root(self):
        expected = Path(__file__).resolve().parents[1]
        self.assertEqual(git_publish.ROOT, expected)
        self.assertEqual(git_publish.ROOT, updater.ROOT)
        self.assertTrue((git_publish.ROOT / "modules" / "git_publish.py").is_file())
        self.assertTrue((git_publish.ROOT / "tests").is_dir())
