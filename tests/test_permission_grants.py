"""Timed grants use isolated storage and the real permission-gate contract."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class PermissionGrantsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'permission_grants'
        self.enterContext(patch.dict(os.environ, {'JARVIS_DATA_DIR': str(self.root.parent)}))
        from modules import permission_grants, llm, requests_state
        self.store, self.llm = permission_grants, llm
        self.enterContext(patch.object(self.store, 'ROOT', self.root))
        self.enterContext(patch.object(self.store.time, 'time', return_value=100))
        token = llm._key_context.set('alice')
        self.addCleanup(llm._key_context.reset, token)
        token = requests_state._current.set(None)
        self.addCleanup(requests_state._current.reset, token)

    def test_missing_store_is_empty_and_does_not_create_file(self):
        self.assertEqual(self.store.load('alice'), {'message_out': {}, 'apps_never': []})
        self.assertFalse(self.root.exists())

    def test_grant_load_revoke_and_real_gate_compatibility(self):
        from modules.permission_gate import decide
        result = self.store.grant_message('alice', 'Ahmet@Example.Org', 60, now=100)
        self.assertEqual(result['message_out'], {'ahmet@example.org': 160})
        action = {'class': 'message_out', 'target': 'AHMET@example.org', 'via': 'outbox'}
        self.assertEqual(decide(action, self.store.load('alice'), now=159)['decision'], 'allow')
        self.assertEqual(decide(action, self.store.load('alice'), now=160)['decision'], 'ask')
        self.assertTrue(self.store.revoke('alice', 'AHMET@EXAMPLE.ORG'))
        self.assertFalse(self.store.revoke('alice', 'AHMET@EXAMPLE.ORG'))

    def test_expired_at_boundary_is_removed_on_load_and_purge_counts(self):
        self.store.grant_message('alice', 'chat-1', 60, now=100)
        with patch.object(self.store.time, 'time', return_value=160):
            self.assertEqual(self.store.load('alice')['message_out'], {})
        self.assertEqual(json.loads((self.root / 'alice.json').read_text())['message_out'], {})
        self.store.grant_message('alice', 'chat-1', 60, now=100)
        self.assertEqual(self.store.purge('alice', now=160), 1)
        self.assertEqual(self.store.purge('alice', now=160), 0)

    def test_fifty_records_and_renew_existing_at_limit(self):
        for index in range(50):
            self.store.grant_message('alice', f'chat-{index}', 60, now=100)
        before = (self.root / 'alice.json').read_bytes()
        with self.assertRaises(ValueError):
            self.store.grant_message('alice', 'chat-50', 60, now=100)
        self.assertEqual((self.root / 'alice.json').read_bytes(), before)
        self.store.grant_message('alice', 'chat-0', 120, now=100)
        self.assertEqual(len(self.store.load('alice')['message_out']), 50)
        self.assertEqual(self.store.load('alice')['message_out']['chat-0'], 220)

    def test_duration_limit_and_invalid_values_cannot_write(self):
        for seconds in (0, -1, 86401, True, None, '60', float('nan'), float('inf')):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                self.store.grant_message('alice', 'chat', seconds, now=100)
        self.assertFalse(self.root.exists())
        self.assertEqual(self.store.grant_message('alice', 'chat', 86400, now=100)['message_out']['chat'], 86500)

    def test_bad_targets_and_times_do_not_change_existing_file(self):
        self.store.grant_message('alice', 'chat', 60, now=100)
        before = (self.root / 'alice.json').read_bytes()
        for target in ('', ' ', '*', 'chat*', 'a\nb', None, 42, 'x' * 321):
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.store.grant_message('alice', target, 60, now=100)
        for now in (True, '100', -1, float('nan'), float('inf')):
            with self.subTest(now=now), self.assertRaises(ValueError):
                self.store.grant_message('alice', 'chat', 60, now=now)
        self.assertEqual((self.root / 'alice.json').read_bytes(), before)

    def test_two_users_and_request_context_are_isolated(self):
        self.store.grant_message('alice', 'chat', 60, now=100)
        with self.assertRaises(PermissionError):
            self.store.load('bob')
        token = self.llm._key_context.set('bob')
        try:
            self.assertEqual(self.store.load('bob')['message_out'], {})
            self.store.grant_message('bob', 'other-chat', 120, now=100)
        finally:
            self.llm._key_context.reset(token)
        self.assertEqual(self.store.load('alice')['message_out'], {'chat': 160})

    def test_path_traversal_and_device_names_fail_without_writes(self):
        for user in ('../alice', 'a/b', '/tmp/alice', 'con', 'nul', '', None):
            with self.subTest(user=user), self.assertRaises((ValueError, PermissionError)):
                self.store.load(user)
        self.assertFalse(self.root.exists())

    def test_corrupt_schema_json_and_nonfinite_grants_fail_closed(self):
        self.root.mkdir()
        path = self.root / 'alice.json'
        for raw in ('{bad', '[]', 'null', '{"message_out":{"chat":NaN},"apps_never":[]}',
                    '{"message_out":{"chat":Infinity},"apps_never":[]}',
                    '{"message_out":{"chat":true},"apps_never":[]}'):
            with self.subTest(raw=raw):
                path.write_text(raw)
                self.assertEqual(self.store.load('alice')['message_out'], {})

    def test_apps_never_survives_message_updates_and_results_are_detached(self):
        self.root.mkdir()
        (self.root / 'alice.json').write_text(json.dumps({'message_out': {}, 'apps_never': ['terminal']}))
        result = self.store.grant_message('alice', 'chat', 60, now=100)
        before = copy.deepcopy(result)
        result['apps_never'].clear()
        result['message_out'].clear()
        self.assertEqual(self.store.load('alice'), before)

    def test_atomic_replace_failure_preserves_previous_and_cleans_temp(self):
        self.store.grant_message('alice', 'chat', 60, now=100)
        before = (self.root / 'alice.json').read_bytes()
        with patch.object(self.store.os, 'replace', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                self.store.grant_message('alice', 'other', 60, now=100)
        self.assertEqual((self.root / 'alice.json').read_bytes(), before)
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_symlink_or_junction_storage_is_rejected(self):
        for attribute in ('is_symlink', 'is_junction'):
            with self.subTest(attribute=attribute):
                with patch.object(Path, attribute, lambda p: p == self.root, create=True):
                    with self.assertRaises(ValueError):
                        self.store.load('alice')
        self.assertFalse(self.root.exists())

    def test_jarvis_home_override_is_used_in_an_isolated_process(self):
        env = os.environ.copy()
        home = self.root.parent / 'home-override'
        env['JARVIS_HOME'] = str(home)
        env['JARVIS_DATA_DIR'] = str(self.root.parent / 'config')
        code = "from modules import permission_grants as s,llm; llm._key_context.set('alice'); s.grant_message('alice','chat',60); print(s.ROOT)"
        result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code], env=env,
                                capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(home / 'permission_grants'))
        self.assertTrue((home / 'permission_grants' / 'alice.json').is_file())

    def test_expired_records_free_capacity_before_adding(self):
        for index in range(50):
            self.store.grant_message('alice', f'chat-{index}', 60, now=100)
        result = self.store.grant_message('alice', 'new-chat', 60, now=160)
        self.assertEqual(result['message_out'], {'new-chat': 220})

    def test_request_for_another_owner_cannot_read_or_write(self):
        from modules import requests_state
        token = requests_state._current.set(('bob', 'request'))
        try:
            with self.assertRaises(PermissionError):self.store.load('alice')
            with self.assertRaises(PermissionError):self.store.grant_message('alice', 'chat', 60, now=100)
        finally:
            requests_state._current.reset(token)
        self.assertFalse(self.root.exists())

    def test_bad_message_permission_cannot_remove_a_valid_permanent_system_ban(self):
        from modules.permission_gate import decide
        self.root.mkdir()
        path = self.root / 'alice.json'
        action = {'class': 'system_config', 'target': 'terminal', 'via': 'system'}
        for messages in ({'chat': float('nan')}, {'chat': True}, [], {'chat': 'invalid'}):
            with self.subTest(messages=messages):
                path.write_text(json.dumps({'message_out': messages, 'apps_never': ['terminal']}))
                grants = self.store.load('alice')
                self.assertEqual(grants['message_out'], {})
                self.assertEqual(decide(action, grants, now=100)['decision'], 'deny')
                self.store.grant_message('alice', 'good-chat', 60, now=100)
                self.assertEqual(json.loads(path.read_text())['apps_never'], ['terminal'])


if __name__ == '__main__':
    unittest.main()
