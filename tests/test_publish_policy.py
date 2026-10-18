"""Yayın ve güncelleme aynı dosya politikasını kullanır."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import updater
from modules import git_publish, publish_policy


class PublishPolicyTests(unittest.TestCase):
    def test_both_consumers_share_policy_objects(self):
        self.assertIs(git_publish._PUBLISH_EXT, publish_policy.ALLOWED_EXTENSIONS)
        self.assertIs(git_publish._PUBLISH_SKIP_PARTS, publish_policy.SKIP_PARTS)
        self.assertIs(git_publish._PUBLISH_SKIP_NAMES, publish_policy.SKIP_NAMES)
        self.assertIs(updater._publishable_path, publish_policy.is_publishable_path)

    def test_allowed_extensions_and_special_paths(self):
        for suffix in publish_policy.ALLOWED_EXTENSIONS:
            with self.subTest(suffix=suffix):
                self.assertTrue(updater._publishable_path('src/file' + suffix.upper()))
        for path in ('.gitignore', '.gitattributes', 'modules/desktop_uia.ps1'):
            self.assertTrue(updater._publishable_path(path))
        for path in ('other.ps1', 'other.exe', 'nested/desktop_uia.ps1'):
            self.assertFalse(updater._publishable_path(path))

    def test_private_and_generated_paths_remain_excluded(self):
        for part in publish_policy.SKIP_PARTS | publish_policy.LOCAL_ONLY_PARTS:
            self.assertFalse(updater._publishable_path(f'{part}/file.py'))
        for name in publish_policy.SKIP_NAMES | {'v2_kabul_sonucu.json', 'v2_kabul_sonucu-PC.json', '.env.dev', 'file.py.yeni'}:
            self.assertFalse(updater._publishable_path(f'nested/{name}'))

    def test_real_file_collection_retains_update_filters_and_size_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            included = {'modules/example.py', 'modules/desktop_uia.ps1', '.gitignore', 'webui/icon.webp'}
            excluded = {'models/file.py', 'settings.json', '.env.dev', 'v2_kabul_sonucu-PC.json', '.ruff_cache/file.py', 'other.ps1'}
            for rel in included | excluded:
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'test')
            with (root / 'large.py').open('wb') as stream:
                stream.truncate(20_000_001)
            with patch.object(git_publish, 'ROOT', root):
                self.assertEqual(set(git_publish._publishable_files()), included)
