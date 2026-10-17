"""Gmail önemli mailler (17 Ekim 2026): Gmail'in önemli/yıldız işaretiyle, modelsiz, yalnız zarf bilgisi.

Gmail servisi taklittir; gerçek hesapta denenmedi.
"""
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from modules import google_api, worktrack

MSGS = {
    'a': (['UNREAD', 'IMPORTANT'], 'Ahmet Yılmaz <ahmet@firma.com>', 'Teklif'),
    'b': (['UNREAD', 'STARRED'], 'Ayşe <ayse@x.com>', 'Toplantı notu'),
    'c': (['UNREAD', 'IMPORTANT'], 'Banka <no-reply@banka.com>', 'Ekstre'),
}


class FakeGmail:
    def __init__(self):
        self.queries, self.formats = [], []

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, userId, q, maxResults):
        self.queries.append(q)
        return SimpleNamespace(execute=lambda: {'messages': [{'id': k} for k in MSGS]})

    def get(self, userId, id, format, metadataHeaders):
        self.formats.append(format)
        labels, frm, subject = MSGS[id]
        return SimpleNamespace(execute=lambda: {'labelIds': labels, 'payload': {'headers': [
            {'name': 'From', 'value': frm}, {'name': 'Subject', 'value': subject}]}})


class ImportantTests(unittest.TestCase):
    def test_starred_first_robots_dropped_body_never_read(self):
        svc = FakeGmail()
        with patch.object(google_api, '_service', return_value=svc):
            items = google_api.important()
        self.assertEqual([(x['who'], x['starred']) for x in items], [('Ayşe', True), ('Ahmet Yılmaz', False)])
        self.assertIn('is:unread in:inbox', svc.queries[0])
        self.assertEqual(set(svc.formats), {'metadata'})

    def test_text_empty_and_error(self):
        with patch.object(google_api, '_ready', return_value=None):
            with patch.object(google_api, 'important', return_value=[{'who': 'Ayşe', 'subject': 'Not', 'starred': True}]):
                self.assertEqual(google_api.important_text(),
                                 "Okunmamış 1 önemli mailin var (Gmail'in önemli/yıldız işaretine göre): Ayşe ★: Not.")
            with patch.object(google_api, 'important', return_value=[]):
                self.assertIn('önemli mailin görünmüyor', google_api.important_text())
            with patch.object(google_api, 'important', side_effect=OSError('ağ yok')):
                self.assertIn('Önemli maillere bakamadım', google_api.important_text())

    def test_phrases_route_and_send_or_other_mail_do_not(self):
        def route(text):
            with patch.object(google_api, 'important_text', return_value='ONEMLI'), \
                    patch.object(google_api, 'unread_mail', return_value='LISTE'), \
                    patch.object(google_api, 'connected', return_value=True), \
                    patch('modules.outlook.installed', return_value=False):
                return worktrack.handle(text) or google_api.handle(text)
        for text in ('önemli maillerim', 'önemli mailler var mı', 'öncelikli maillerim neler', 'acil mail var mı',
                     'hangi mail önemli', 'önemli e-postalarıma bak', 'gmailde önemli mailler'):
            with self.subTest(text=text):
                self.assertEqual(route(text), 'ONEMLI')
        self.assertEqual(route('maillerimi kontrol et'), 'LISTE')
        self.assertNotEqual(route('önemli bir mail gönder'), 'ONEMLI')

    def test_real_engine_reaches_it_without_model(self):
        from test_mail_calendar_fixes import _runtime, say
        rt = _runtime(self, SimpleNamespace(slug='deneme', name='Deneme', data={'prefs': {}, 'events': [], 'tasks': [],
                                                                               'items': [], 'rules': []}),
                      datetime(2026, 10, 17, 10, 0))
        rt.google_api = google_api
        with patch.object(google_api, 'important_text', return_value='ONEMLI'), \
                patch.object(google_api, 'connected', return_value=True), \
                patch('modules.outlook.installed', return_value=False):
            self.assertEqual(say(rt, 'önemli maillerim'), 'ONEMLI')


if __name__ == '__main__':
    unittest.main()
