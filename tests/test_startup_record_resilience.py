"""Startup failures and corrupt records use isolated files, no hardware/providers."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import config
import launcher
from modules import developer as dev


class StartupRecordTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.owner = 'alice'
        for obj, name, value in ((dev, 'STORE', self.root/'development'),
                                 (dev, '_AUTH', set()), (config, 'KEY_FILE', self.root/'legacy.txt')):
            p = patch.object(obj, name, value); p.start(); self.addCleanup(p.stop)
        dev._folder(self.owner).mkdir(parents=True)

    def test_dependency_timeout_stops_without_repair_or_start(self):
        with patch.object(launcher.guard, 'recover') as recover, patch.object(launcher.guard, 'pending', return_value=None), patch.object(launcher.guard, 'current_python', return_value='python'), patch.object(launcher.subprocess, 'run', side_effect=subprocess.TimeoutExpired('imports', 30)) as run, patch.object(launcher.subprocess, 'call') as call:
            self.assertEqual(launcher.check_installation(self.root), 2)
            self.assertEqual(run.call_args.kwargs['timeout'], launcher.DEPENDENCY_TIMEOUT)
            recover.assert_called_once_with(self.root.resolve()); call.assert_not_called()

    def test_pending_candidate_is_not_repaired(self):
        with patch.object(launcher.guard, 'recover'), patch.object(launcher.guard, 'pending', return_value={'status':'awaiting_start'}), patch.object(launcher.subprocess, 'run') as run:
            self.assertEqual(launcher.check_installation(self.root), 0)
            run.assert_not_called()

    def test_unreadable_legacy_key_and_status_are_safe(self):
        with patch.dict(config.os.environ, {}, clear=True), patch.object(Path, 'read_text', side_effect=PermissionError('denied')):
            self.assertEqual(config.get_api_key(), '')
            self.assertFalse(config.legacy_key_protected())

    def test_bad_utf8_key_is_preserved(self):
        config.KEY_FILE.write_bytes(b'\xff\xfe')
        with patch.dict(config.os.environ, {}, clear=True):
            self.assertEqual(config.get_api_key(), '')
            self.assertFalse(config.legacy_key_protected())
        self.assertEqual(config.KEY_FILE.read_bytes(), b'\xff\xfe')

    def test_failed_legacy_migration_keeps_readable_key_and_file(self):
        config.KEY_FILE.write_text('test-legacy-value', encoding='utf-8')
        with patch.dict(config.os.environ, {}, clear=True), patch.object(config, '_privacy', return_value=Mock(unprotect=lambda value:value)), patch.object(config, 'save_api_key', side_effect=OSError('disk unavailable')):
            self.assertEqual(config.get_api_key(), 'test-legacy-value')
        self.assertEqual(config.KEY_FILE.read_text(), 'test-legacy-value')

    def test_config_import_survives_unreadable_legacy_file(self):
        original = Path.read_text
        def read(path, *args, **kwargs):
            if path.name == 'gemini_key.txt': raise PermissionError('denied')
            return original(path, *args, **kwargs)
        spec = importlib.util.spec_from_file_location('isolated_resilient_config', config.__file__)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(config.os.environ, {'JARVIS_DATA_DIR':str(self.root)}, clear=True), patch.object(Path, 'read_text', read):
            spec.loader.exec_module(module)
        self.assertEqual(module.API_KEY, '')

    def test_corrupt_state_status_is_disabled_and_original_not_replaced(self):
        path = dev._folder(self.owner)/'state.json'
        for payload in ('{broken', '[]', '{"enabled":true,"turns":[],"draft":[]}'):
            with self.subTest(payload=payload):
                path.write_text(payload)
                dev._AUTH.add(self.owner)
                status = dev.status(self.owner)
                self.assertFalse(status['enabled']); self.assertFalse(status['unlocked'])
                self.assertIn('korunuyor', status['error'])
                with self.assertRaisesRegex(ValueError, 'korunuyor'):dev._load(self.owner)
                self.assertEqual(path.read_text(), payload)

    def test_history_skips_bad_lines_and_keeps_matching_valid_rows(self):
        path = dev._folder(self.owner)/'conversation.jsonl'
        payload = '\n'.join([json.dumps({'role':'user','text':'keep old'}), '{broken', '[]', json.dumps({'role':'assistant','text':None}), json.dumps({'role':'assistant','text':'keep new'})])+'\n'
        path.write_text(payload)
        self.assertEqual([r['text'] for r in dev._old_turns(self.owner, 'keep')], ['keep old','keep new'])
        self.assertEqual(path.read_text(), payload)

    def test_corrupt_password_record_never_sets_new_password_or_unlocks(self):
        path = dev._folder(self.owner)/'access.json'
        payloads = ['{broken', '{}', '[]', json.dumps({'salt':'ff','hash':'a'*64}), json.dumps({'salt':'ff'*16,'hash':'a'*64,'fails':-1})]
        for payload in payloads:
            with self.subTest(payload=payload):
                path.write_text(payload); dev._AUTH.add(self.owner)
                self.assertFalse(dev.unlock(self.owner, 'password')['ok'])
                self.assertNotIn(self.owner, dev._AUTH)
                self.assertEqual(path.read_text(), payload)

    def test_valid_password_and_draft_survive_restart(self):
        self.assertTrue(dev.unlock(self.owner, 'password')['ok'])
        state = dev._load(self.owner)
        state['draft']={'example.py':{'content':'print(1)','base':None}}
        dev._save(self.owner, state); dev._AUTH.clear()
        self.assertFalse(dev.unlock(self.owner, 'wrong-password')['ok'])
        self.assertTrue(dev.unlock(self.owner, 'password')['ok'])
        self.assertEqual(dev._load(self.owner)['draft'], state['draft'])
