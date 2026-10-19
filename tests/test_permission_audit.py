"""İzin kararları yalnız geçici kullanıcı dizininde sınanır; servis/model yoktur."""
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch


class PermissionAuditTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data = Path(temp.name)
        self.enterContext(patch.dict(os.environ, {'JARVIS_DATA_DIR': str(self.data)}))
        from modules import permission_audit
        self.audit = permission_audit
        self.enterContext(patch.object(self.audit, 'DATA_DIR', self.data))
        self.diagnostic = self.enterContext(patch.object(self.audit, '_record_failure'))
        self.root = self.data / 'permission_audit'

    def record(self, owner='alice', target='rapor', **changes):
        args = dict(owner=owner, decision='allow', action_class='read_private', target=target, via='file')
        args.update(changes)
        return self.audit.record(**args)

    def path(self, owner='alice'):
        return self.root / f'{owner}.json'

    def test_record_schema_and_newest_first_limit(self):
        for i, decision in enumerate(('allow', 'ask', 'deny')):
            with patch.object(self.audit.time, 'time', return_value=1000 + i):
                self.record(target=f'hedef-{i}', decision=decision, via='outbox', reason='gerekçe')
        rows = self.audit.recent('alice', 2)
        self.assertEqual([r['target'] for r in rows], ['hedef-2', 'hedef-1'])
        self.assertEqual(rows[0], {'t': 1002, 'decision': 'deny', 'class': 'read_private',
                                   'target': 'hedef-2', 'via': 'outbox', 'reason': 'gerekçe'})
        self.assertEqual(len(self.audit.recent('alice')), 3)
        self.assertEqual(self.audit.recent('alice', 0), [])

    def test_only_last_five_hundred_are_retained(self):
        for i in range(501):
            self.record(target=f'hedef-{i}')
        rows = self.audit.recent('alice', 1000)
        self.assertEqual(len(rows), 500)
        self.assertEqual(rows[0]['target'], 'hedef-500')
        self.assertEqual(rows[-1]['target'], 'hedef-1')
        self.assertEqual(len(json.loads(self.path().read_text(encoding='utf-8'))), 500)

    def test_raw_file_masks_mail_phone_token_and_card_even_if_disabled(self):
        secrets = ['alice@example.org', '0532 123 45 67', 'sk-' + 'a' * 28, '4111 1111 1111 1111']
        text = ' '.join(secrets)
        with patch('modules.privacy.redact_enabled', return_value=False):
            self.record(target=text, reason=text)
        raw = self.path().read_text(encoding='utf-8')
        for secret in secrets:
            self.assertNotIn(secret, raw)
        for row in self.audit.recent('alice'):
            for field in ('target', 'reason'):
                for label in ('e-posta', 'telefon', 'anahtar', 'kart'):
                    self.assertIn(f'[{label} gizlendi]', row[field])

    def test_masking_precedes_two_hundred_character_limit(self):
        secret = 'sk-' + 'a' * 28
        text = 'x ' * 98 + secret + ' uzun' * 500
        self.record(target=text, reason=text)
        row = self.audit.recent('alice')[0]
        for field in ('target', 'reason'):
            self.assertEqual(len(row[field]), 200)
            self.assertNotIn('sk-', row[field])

    def test_invalid_decision_via_and_field_types_do_not_write(self):
        for field, values in {'decision': ['ALLOW', '', 'other', None, []],
                              'via': ['email', '', None, []],
                              'action_class': ['', None], 'target': [None], 'reason': [None]}.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.record(**{field: value})
        self.assertFalse(self.root.exists())

    def test_invalid_input_leaves_existing_file_unchanged(self):
        self.record()
        original = self.path().read_bytes()
        with self.assertRaises(ValueError):
            self.record(decision='unknown')
        self.assertEqual(self.path().read_bytes(), original)

    def test_all_methods_are_valid_and_users_are_isolated(self):
        for via in ('outbox', 'desktop', 'browser', 'file', 'system'):
            self.record(via=via)
        self.record(owner='bob', target='bob kaydı')
        self.assertEqual(len(self.audit.recent('alice')), 5)
        self.assertEqual([r['target'] for r in self.audit.recent('bob')], ['bob kaydı'])
        self.assertEqual(self.audit.clear('alice'), 5)
        self.assertEqual(self.audit.recent('alice'), [])
        self.assertEqual(len(self.audit.recent('bob')), 1)
        self.assertEqual(self.audit.clear('alice'), 0)

    def test_traversal_and_windows_device_names_are_rejected(self):
        for owner in ('../x', '..\\x', 'a..b', '/x', 'C:\\x', '', '.', 'Alice', 'con', 'com1'):
            for call in (lambda: self.record(owner=owner), lambda: self.audit.recent(owner),
                         lambda: self.audit.clear(owner)):
                with self.subTest(owner=owner), self.assertRaises(ValueError):
                    call()
        self.assertFalse(self.root.exists())

    def test_corrupt_files_are_preserved_as_backup_and_recording_continues(self):
        self.root.mkdir()
        for bad in (b'[{', b'{}', b'[{}]', b'\xff'):
            with self.subTest(bad=bad):
                self.path().write_bytes(bad)
                self.assertEqual(self.audit.recent('alice'), [])
                self.record()
                self.assertEqual(len(self.audit.recent('alice')), 1)
        backups = list(self.root.glob('*.bozuk'))
        self.assertEqual(len(backups), 4)
        self.assertEqual({p.read_bytes() for p in backups}, {b'[{', b'{}', b'[{}]', b'\xff'})
        self.assertEqual(self.diagnostic.call_count, 4)

    def test_failed_backup_never_overwrites_corrupt_original(self):
        self.root.mkdir()
        self.path().write_bytes(b'[{')
        with patch.object(self.audit.os, 'replace', side_effect=OSError('disk dolu')):
            self.assertIsNone(self.record())
        self.assertEqual(self.path().read_bytes(), b'[{')
        self.diagnostic.assert_called()

    def test_failed_atomic_write_does_not_raise_or_lose_previous_rows(self):
        self.record(target='eski')
        original = self.path().read_bytes()
        with patch.object(self.audit.os, 'replace', side_effect=OSError('disk dolu')):
            self.assertIsNone(self.record(target='yeni'))
        self.assertEqual(self.path().read_bytes(), original)
        self.assertEqual(list(self.root.glob('*.tmp')), [])
        self.diagnostic.assert_called_once()

    def test_failure_to_create_temporary_file_is_nonfatal(self):
        with patch.object(self.audit.tempfile, 'mkstemp', side_effect=OSError('disk dolu')):
            self.assertIsNone(self.record())
        self.assertFalse(self.path().exists())
        self.diagnostic.assert_called_once()

    def test_missing_log_and_zero_limit_create_nothing(self):
        self.assertEqual(self.audit.recent('alice'), [])
        self.assertEqual(self.audit.recent('alice', 0), [])
        self.assertEqual(self.audit.clear('alice'), 0)
        self.assertFalse(self.root.exists())

    def test_two_threads_do_not_lose_records(self):
        def write(prefix):
            for i in range(20):
                self.record(target=f'{prefix}-{i}')
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(write, ['bir', 'iki']))
        rows = self.audit.recent('alice')
        self.assertEqual(len(rows), 40)
        self.assertEqual({r['target'] for r in rows}, {f'{p}-{i}' for p in ('bir', 'iki') for i in range(20)})


if __name__ == '__main__':
    unittest.main()
