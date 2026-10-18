"""Google kurulum sihirbazı (18 Ekim 2026, B yolu: her kullanıcı kendi Google projesini açar).

Tarayıcı, Google ve dosya yazımı taklit/geçici dizindir; gerçek Google Cloud'da denenmedi.
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

from modules import google_setup
from web_integrations import WebIntegrations


class StepsTests(unittest.TestCase):
    def test_steps_are_ordered_and_urls_stay_on_google_cloud(self):
        steps = google_setup.steps()
        self.assertEqual([s['id'] for s in steps][-2:], ['json', 'baglan'])
        self.assertEqual(len({s['id'] for s in steps}), len(steps))
        for s in steps:
            self.assertTrue(s['title'] and s['text'])
            if s.get('url'):
                u = urlparse(s['url'])
                self.assertEqual((u.scheme, u.hostname), ('https', 'console.cloud.google.com'))

    def test_optional_and_calendar_write_steps(self):
        by = {s['id']: s for s in google_setup.steps()}
        self.assertTrue(by['gorevler']['optional'])
        self.assertFalse(any('calendar.events' in s['text'] for s in by.values()))   # Takvime yazma sonra
        self.assertIn('Masaüstü', by['istemci']['text'])
        self.assertIn('In production', by['yayin']['text'])


class ClientFileTests(unittest.TestCase):
    def test_problem_messages(self):
        self.assertIsNone(google_setup.client_problem({'installed': {'client_id': 'a', 'client_secret': 'b'}}))
        self.assertIn('Masaüstü', google_setup.client_problem({'web': {'client_id': 'a', 'client_secret': 'b'}}))
        self.assertIn('client_id', google_setup.client_problem({'installed': {'client_secret': 'b'}}))
        self.assertIn('client_secret', google_setup.client_problem({'installed': {'client_id': 'a'}}))
        self.assertIn('OAuth', google_setup.client_problem({'type': 'service_account'}))


class StatusTests(unittest.TestCase):
    def _status(self, cred, token=False, packages=True, production=False):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'google_credentials.json'
            if cred is not None:
                path.write_text(json.dumps(cred), encoding='utf-8')
            api = SimpleNamespace(CRED=path, connected=lambda: token)
            with patch.object(google_setup, '_packages_ok', return_value=packages):
                return google_setup.status(api, production)

    def test_next_step_follows_what_can_be_checked(self):
        good = {'installed': {'client_id': 'a', 'client_secret': 'b'}}
        self.assertEqual(self._status(None)['next'], 'json')
        self.assertEqual(self._status({'web': {'client_id': 'a', 'client_secret': 'b'}})['next'], 'json')
        self.assertEqual(self._status(good, packages=False)['next'], 'paketler')
        self.assertEqual(self._status(good)['next'], 'baglan')
        done = self._status(good, token=True)
        self.assertEqual(done['next'], 'bitti')
        self.assertTrue(done['token'])

    def test_status_never_returns_secrets(self):
        s = self._status({'installed': {'client_id': 'CID-123', 'client_secret': 'SECRET-xyz'}})
        self.assertNotIn('SECRET-xyz', json.dumps(s))
        self.assertNotIn('CID-123', json.dumps(s))

    def test_unreadable_credentials_file_is_a_clear_problem(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'c.json'
            path.write_text('{bozuk', encoding='utf-8')
            api = SimpleNamespace(CRED=path, connected=lambda: False)
            with patch.object(google_setup, '_packages_ok', return_value=True):
                s = google_setup.status(api, False)
        self.assertEqual(s['next'], 'json')
        self.assertIn('okunamadı', s['cred_msg'])

    def test_connected_check_without_selected_user_is_false(self):
        def boom():
            raise PermissionError('kullanıcı yok')
        with tempfile.TemporaryDirectory() as td:
            api = SimpleNamespace(CRED=Path(td) / 'x.json', connected=boom)
            with patch.object(google_setup, '_packages_ok', return_value=True):
                self.assertFalse(google_setup.status(api, False)['token'])


class BridgeTests(unittest.TestCase):
    def _bridge(self, path):
        b = WebIntegrations()
        b._runtime = SimpleNamespace(json=json, google_api=SimpleNamespace(CRED=path, connected=lambda: False),
                                     config=SimpleNamespace(load_settings=lambda: {'google_oauth_production': True}))
        return b

    def test_open_only_allowlisted_steps(self):
        with tempfile.TemporaryDirectory() as td:
            b = self._bridge(Path(td) / 'c.json')
            with patch('webbrowser.open') as opened:
                r = b.google_setup_open('gmail')
                self.assertTrue(r['ok'])
                self.assertEqual(opened.call_args[0][0], 'https://console.cloud.google.com/apis/library/gmail.googleapis.com')
                for bad in ('json', 'https://evil.example', '', 'baglan'):
                    with self.assertRaises(ValueError):
                        b.google_setup_open(bad)
                self.assertEqual(opened.call_count, 1)

    def test_status_and_steps_through_bridge(self):
        with tempfile.TemporaryDirectory() as td:
            b = self._bridge(Path(td) / 'c.json')
            with patch.object(google_setup, '_packages_ok', return_value=True):
                r = b.google_setup_status()
            self.assertEqual(r['next'], 'json')
            self.assertTrue(r['production'])
            self.assertEqual(r['steps'][0]['id'], google_setup.steps()[0]['id'])

    def test_upload_rejects_web_client_keeps_existing_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'c.json'
            path.write_text('existing', encoding='utf-8')
            b = self._bridge(path)
            with self.assertRaises(ValueError) as ctx:
                b.google_upload(json.dumps({'web': {'client_id': 'a', 'client_secret': 'b'}}))
            self.assertIn('Masaüstü', str(ctx.exception))
            self.assertEqual(path.read_text(encoding='utf-8'), 'existing')
            msg = b.google_upload(json.dumps({'installed': {'client_id': 'a'}}))
            self.assertIn('client_secret', msg)             # uyarı verir ama mevcut davranış kırılmaz
            self.assertTrue(json.loads(path.read_text(encoding='utf-8'))['installed'])


if __name__ == '__main__':
    unittest.main()
