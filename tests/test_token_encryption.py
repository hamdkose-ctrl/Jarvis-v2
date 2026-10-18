import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from modules import google_api, llm, privacy, publish_services

SECRET = 'PRIVATE_OAUTH_OR_CONNECTOR_SECRET'


class TokenEncryptionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for module in (google_api, publish_services):
            p = patch.object(module, 'DATA_DIR', self.root); p.start(); self.addCleanup(p.stop)
        p = patch.object(google_api, 'TOKEN', self.root / 'google_token.json')
        p.start(); self.addCleanup(p.stop)
        p = patch('config.load_settings', return_value={'google_legacy_owner': 'alice'})
        p.start(); self.addCleanup(p.stop)
        context = llm._key_context.set('alice'); self.addCleanup(llm._key_context.reset, context)
        self.protect = patch.object(privacy, 'protect', side_effect=lambda text: 'dpapi:' + base64.b64encode(text.encode()).decode())
        self.protect_mock = self.protect.start(); self.addCleanup(self.protect.stop)
        self.unprotect = patch.object(privacy, 'unprotect', side_effect=lambda text: base64.b64decode(text[6:]).decode() if text.startswith('dpapi:') else text)
        self.unprotect_mock = self.unprotect.start(); self.addCleanup(self.unprotect.stop)
        self.info = {'token': SECRET, 'refresh_token': SECRET, 'client_id': 'fake', 'client_secret': SECRET,
                     'expiry': '2099-01-01T00:00:00Z', 'scopes': google_api.SCOPES}
        from google.oauth2.credentials import Credentials
        self.credentials_class = Credentials
        self.creds = Mock(valid=True, expired=False, refresh_token=SECRET)
        self.creds.to_json.return_value = json.dumps(self.info)
        for name in ('from_authorized_user_file', 'from_authorized_user_info'):
            p = patch.object(Credentials, name, return_value=self.creds); p.start(); self.addCleanup(p.stop)

    def plain_token(self, legacy=False):
        path = self.root / ('google_token.json' if legacy else 'google_users/alice/google_token.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.info), encoding='utf-8')
        return path

    def connector(self, service='telegram'):
        path = self.root / 'connector_users/alice' / (service + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'bot_token': SECRET, 'access_token': SECRET}), encoding='utf-8')
        return path

    def assert_protected(self, path):
        stored = path.read_text(encoding='utf-8')
        self.assertTrue(stored.startswith('dpapi:'))
        self.assertNotIn(SECRET, stored)
        self.assertIn(SECRET, privacy.unprotect(stored))

    def test_google_plain_is_encrypted_on_first_read_without_losing_login(self):
        path = self.plain_token()
        self.assertIs(google_api._creds(interactive=False), self.creds)
        self.assert_protected(path)

    def test_legacy_google_migrates_to_same_owner_only_after_protected_roundtrip(self):
        old = self.plain_token(legacy=True)
        self.assertIs(google_api._creds(interactive=False), self.creds)
        self.assertFalse(old.exists())
        self.assert_protected(self.root / 'google_users/alice/google_token.json')

    def test_migration_protection_failure_keeps_plain_bytes_and_login_usable(self):
        path = self.plain_token(); before = path.read_bytes()
        self.protect_mock.side_effect = OSError(SECRET)
        self.assertIs(google_api._creds(interactive=False), self.creds)
        self.assertEqual(path.read_bytes(), before)

    def test_legacy_migration_readback_failure_keeps_original_and_no_plain_copy(self):
        old = self.plain_token(legacy=True); before = old.read_bytes()
        self.unprotect_mock.side_effect = OSError(SECRET)
        self.assertIs(google_api._creds(interactive=False), self.creds)
        self.assertEqual(old.read_bytes(), before)
        self.assertFalse((self.root / 'google_users/alice/google_token.json').exists())

    def test_connector_plain_files_for_all_services_migrate_without_new_permissions(self):
        for service in ('telegram', 'whatsapp', 'instagram', 'youtube'):
            with self.subTest(service=service):
                path = self.connector(service)
                self.assertEqual(publish_services.configuration('alice', service)['access_token'], SECRET)
                self.assert_protected(path)

    def test_connector_migration_failure_keeps_original_and_remains_readable(self):
        path = self.connector(); before = path.read_bytes()
        self.protect_mock.side_effect = OSError(SECRET)
        self.assertEqual(publish_services.configuration('alice', 'telegram')['bot_token'], SECRET)
        self.assertEqual(path.read_bytes(), before)

    def test_connector_readback_failure_does_not_replace_plain_file(self):
        path = self.connector(); before = path.read_bytes()
        self.unprotect_mock.return_value = '{}'; self.unprotect_mock.side_effect = None
        self.assertEqual(publish_services.configuration('alice', 'telegram')['bot_token'], SECRET)
        self.assertEqual(path.read_bytes(), before)

    def test_corrupt_protected_google_and_connector_request_login_without_secret(self):
        for path, read in ((self.plain_token(), lambda: google_api._creds(interactive=False)),
                           (self.connector(), lambda: publish_services.configuration('alice', 'telegram'))):
            with self.subTest(path=path.name):
                path.write_text('dpapi:broken', encoding='utf-8')
                self.unprotect_mock.side_effect = ValueError(SECRET)
                with self.assertRaises(PermissionError) as raised:
                    read()
                self.assertIn('yeniden giriş', str(raised.exception).lower())
                self.assertNotIn(SECRET, str(raised.exception))
                self.assertEqual(path.read_text(encoding='utf-8'), 'dpapi:broken')

    def test_refresh_persists_only_protected_new_token(self):
        path = self.plain_token()
        self.creds.valid = False; self.creds.expired = True
        def refresh(request):
            self.creds.to_json.return_value = json.dumps(self.info | {'token': SECRET + '_REFRESHED'})
        self.creds.refresh.side_effect = refresh
        google_api._creds(interactive=False)
        self.creds.refresh.assert_called_once()
        self.assert_protected(path)
        self.assertIn('_REFRESHED', privacy.unprotect(path.read_text(encoding='utf-8')))

    def test_linux_uses_existing_privacy_base64_policy_not_fake_dpapi(self):
        self.protect.stop(); self.unprotect.stop()
        path = self.connector()
        with patch.object(privacy.sys, 'platform', 'linux'):
            self.assertEqual(publish_services.configuration('alice', 'telegram')['bot_token'], SECRET)
            self.assertTrue(path.read_text(encoding='utf-8').startswith('b64:'))
            self.assertNotIn(SECRET, path.read_text(encoding='utf-8'))

    def test_other_owner_cannot_read_connector(self):
        self.connector()
        with self.assertRaises(PermissionError): publish_services.configuration('bob', 'telegram')

    def test_replace_interruption_leaves_plain_connector_and_no_temp_secret(self):
        path = self.connector(); before = path.read_bytes()
        with patch.object(os, 'replace', side_effect=OSError(SECRET)):
            self.assertEqual(publish_services.configuration('alice', 'telegram')['bot_token'], SECRET)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(path.parent.iterdir()), [path])

    def test_refresh_failure_message_and_diagnostics_cannot_contain_token(self):
        self.plain_token()
        self.creds.valid = False; self.creds.expired = True
        self.creds.refresh.side_effect = RuntimeError(SECRET)
        with patch.object(google_api, '_record_failure') as log:
            with self.assertRaises(PermissionError) as raised:
                google_api._creds(interactive=False)
        self.assertNotIn(SECRET, str(raised.exception))
        self.assertNotIn(SECRET, str(log.call_args_list))

    def test_guest_never_migrates_or_reads_legacy_owner_token(self):
        old = self.plain_token(legacy=True); before = old.read_bytes()
        token = llm._key_context.set('bob')
        try:
            with self.assertRaises(PermissionError): google_api._creds(interactive=False)
        finally: llm._key_context.reset(token)
        self.assertEqual(old.read_bytes(), before)
        self.protect_mock.assert_not_called()

    def test_concurrent_new_login_is_not_overwritten_by_stale_refresh(self):
        path = self.plain_token()
        newer = self.info | {'token': SECRET + '_NEW_LOGIN'}
        self.creds.valid = False; self.creds.expired = True
        self.creds.refresh.side_effect = lambda request: path.write_text(json.dumps(newer), encoding='utf-8')
        google_api._creds(interactive=False)
        stored = path.read_text(encoding='utf-8')
        decoded = privacy.unprotect(stored)
        self.assertEqual(json.loads(decoded)['token'], newer['token'])

    def test_plain_copy_stays_until_encrypted_temporary_roundtrip_succeeds(self):
        path = self.connector(); before = path.read_bytes()
        def readback(stored):
            self.assertEqual(path.read_bytes(), before)
            return base64.b64decode(stored[6:]).decode()
        self.unprotect_mock.side_effect = readback
        self.assertEqual(publish_services.configuration('alice', 'telegram')['bot_token'], SECRET)
        self.assertTrue(path.read_text(encoding='utf-8').startswith('dpapi:'))

    def test_legacy_source_changed_during_copy_is_not_deleted(self):
        old = self.plain_token(legacy=True)
        newer = json.dumps(self.info | {'token': SECRET + '_NEW_LOGIN'})
        replace = os.replace
        def changed_source(source, destination):
            replace(source, destination)
            old.write_text(newer, encoding='utf-8')
        with patch.object(os, 'replace', side_effect=changed_source):
            google_api.token_path()
        self.assertTrue(old.exists())
        self.assertEqual(old.read_text(encoding='utf-8'), newer)


if __name__ == '__main__': unittest.main()
