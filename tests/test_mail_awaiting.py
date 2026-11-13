"""Gmail cevap takibi (17 Ekim 2026): yalnız zarf bilgisiyle, model çağrılmadan.

- "cevap vermediğim mailler": son 7 günde doğrudan bana yazılmış, kişi gönderen, son mesajı benden olmayan konuşmalar.
- "cevap gelmeyen maillerim": benim gönderip en az 2 gündür cevap gelmeyen konuşmalar.
- Outlook'suz bilgisayarda "cevap bekleyen maillerim" eskiden yalnız "Outlook kurulu değil" diyordu.
Gmail servisi taklittir; mail gövdesi hiç istenmez (format=metadata denetlenir).
"""
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from modules import google_api, worktrack

ME = 'hamdi@example.com'
DAY = 86400 * 1000


def _msg(frm, to, subject, days_ago, sent=False):
    return {'labelIds': ['SENT'] if sent else ['INBOX'], 'internalDate': str(int(time.time() * 1000 - days_ago * DAY)),
            'payload': {'headers': [{'name': 'From', 'value': frm}, {'name': 'To', 'value': to},
                                    {'name': 'Subject', 'value': subject}]}}


class FakeGmail:
    def __init__(self, threads):
        self.threads_data, self.queries, self.formats = threads, [], []

    def users(self):
        return self

    def getProfile(self, userId):
        return SimpleNamespace(execute=lambda: {'emailAddress': ME})

    def threads(self):
        return self

    def list(self, userId, q, maxResults):
        self.queries.append(q)
        return SimpleNamespace(execute=lambda: {'threads': [{'id': k} for k in self.threads_data]})

    def get(self, userId, id, format, metadataHeaders):
        self.formats.append(format)
        return SimpleNamespace(execute=lambda: {'messages': self.threads_data[id]})


THREADS = {
    't1': [_msg('Ahmet Yılmaz <ahmet@firma.com>', ME, 'Teklif', 2)],                         # cevap vermedim
    't2': [_msg('Ayşe <ayse@x.com>', ME, 'Toplantı', 3), _msg(ME, 'ayse@x.com', 'Re: Toplantı', 1, sent=True)],
    't3': [_msg('Bildirim <no-reply@banka.com>', ME, 'Hesap özeti', 1)],                      # robot
    't4': [_msg('Liste <liste@grup.com>', 'grup@grup.com', 'Duyuru', 1)],                     # bana doğrudan değil
    't5': [_msg(ME, 'Mehmet <mehmet@y.com>', 'Fatura', 5, sent=True)],                        # cevap gelmedi
}


class AwaitingTests(unittest.TestCase):
    def run_kind(self, kind):
        svc = FakeGmail(THREADS)
        with patch.object(google_api, '_service', return_value=svc):
            return google_api.awaiting(kind), svc

    def test_mine_lists_only_direct_people_without_my_reply(self):
        items, svc = self.run_kind('mine')
        self.assertEqual([(x['who'], x['subject'], x['days']) for x in items], [('Ahmet Yılmaz', 'Teklif', 2)])
        self.assertIn('in:inbox newer_than:7d', svc.queries[0])
        self.assertEqual(set(svc.formats), {'metadata'})          # gövde okunmaz

    def test_theirs_lists_my_unanswered_sent_threads(self):
        items, svc = self.run_kind('theirs')
        self.assertIn(('Mehmet', 'Fatura', 5), [(x['who'], x['subject'], x['days']) for x in items])
        self.assertNotIn('Toplantı', [x['subject'] for x in items])
        self.assertIn('in:sent', svc.queries[0])

    def test_theirs_rechecks_age_of_last_message(self):
        # Gmail sorgusu konuşma düzeyindedir: "older_than:2d" konuşmada herhangi bir eski mesaj varsa eşleşir.
        # Dün benim yazdığım takip mesajı son mesajsa 2 gündür bekleyen bir konu değildir.
        threads = {
            'eski': [_msg(ME, 'Mehmet <mehmet@y.com>', 'Fatura', 5, sent=True)],
            'takip': [_msg(ME, 'Ali <ali@y.com>', 'Teklif', 6, sent=True),
                      _msg(ME, 'ali@y.com', 'Re: Teklif', 0.5, sent=True)],
            'sinir': [_msg(ME, 'Veli <veli@y.com>', 'Rapor', 1.5, sent=True)],
        }
        with patch.object(google_api, '_service', return_value=FakeGmail(threads)):
            items = google_api.awaiting('theirs')
        self.assertEqual([x['subject'] for x in items], ['Fatura'])
        self.assertTrue(all(x['days'] >= 2 for x in items))

    def test_text_and_errors(self):
        with patch.object(google_api, '_ready', return_value=None), \
                patch.object(google_api, 'awaiting', return_value=[{'who': 'Ahmet', 'subject': 'Teklif', 'days': 0}]):
            self.assertEqual(google_api.awaiting_text('mine'),
                             'Cevap vermediğin 1 mail var (Gmail, son 7 gün): Ahmet (bugün): Teklif.')
        with patch.object(google_api, '_ready', return_value=None), patch.object(google_api, 'awaiting', return_value=[]):
            self.assertIn('cevap bekleyen mailin yok', google_api.awaiting_text('theirs'))
        with patch.object(google_api, '_ready', return_value=None), \
                patch.object(google_api, 'awaiting', side_effect=OSError('ağ yok')):
            self.assertIn('Cevap bekleyen maillere bakamadım', google_api.awaiting_text('mine'))


class RoutingTests(unittest.TestCase):
    def route(self, text, outlook=False, connected=True):
        with patch.object(google_api, 'awaiting_text', side_effect=lambda k: 'GMAIL:' + k), \
                patch.object(google_api, 'connected', return_value=connected), \
                patch.object(google_api, 'unread_mail', return_value='LISTE'), \
                patch('modules.outlook.installed', return_value=outlook), \
                patch.object(worktrack, 'report', side_effect=lambda kind, *a: 'OUTLOOK:' + kind):
            return worktrack.handle(text) or google_api.handle(text)

    def test_phrases(self):
        cases = {'cevap vermediğim mailler': 'GMAIL:mine', 'cevaplamadığım mailler var mı': 'GMAIL:mine',
                 'cevap bekleyen maillerim': 'GMAIL:mine', 'yanıtlamadığım e-postalar': 'GMAIL:mine',
                 'kime cevap vermedim': 'GMAIL:mine', 'cevap gelmeyen maillerim': 'GMAIL:theirs',
                 'hangi maillerime cevap gelmedi': 'GMAIL:theirs', 'kimden cevap bekliyorum': 'GMAIL:theirs',
                 'maillerimi kontrol et': 'LISTE'}
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.route(text), want)

    def test_outlook_pc_keeps_work_tracking_unless_gmail_named(self):
        self.assertEqual(self.route('cevap bekleyen maillerim', outlook=True), 'OUTLOOK:reply')
        self.assertEqual(self.route('gmailde cevap bekleyen maillerim', outlook=True), 'GMAIL:mine')
        self.assertEqual(self.route('cevap gelmeyen maillerim', outlook=True), 'GMAIL:theirs')
        self.assertEqual(self.route('iş maillerinde cevap bekleyenler', outlook=False), 'OUTLOOK:reply')

    def test_no_outlook_no_google_keeps_old_message_path(self):
        self.assertEqual(self.route('cevap bekleyen maillerim', connected=False), 'OUTLOOK:reply')


if __name__ == '__main__':
    unittest.main()


class EngineOrderTests(unittest.TestCase):
    def test_real_handle_reaches_gmail_without_model(self):
        from datetime import datetime
        from test_mail_calendar_fixes import _runtime
        from brain_turn_fixture import turn
        rt = _runtime(self, SimpleNamespace(slug='deneme', name='Deneme', data={'prefs': {}, 'events': [], 'tasks': [],
                                                                               'items': [], 'rules': []}),
                      datetime(2026, 10, 17, 10, 0))
        rt.google_api = google_api
        with patch.object(google_api, 'awaiting_text', side_effect=lambda k: 'GMAIL:' + k), \
                patch.object(google_api, 'connected', return_value=True), \
                patch('modules.outlook.installed', return_value=False):
            self.assertEqual(turn(rt, 'cevap vermediğim mailler', 'mail.read', {'source': 'awaiting_mine'}), 'GMAIL:mine')
            self.assertEqual(turn(rt, 'cevap gelmeyen maillerim', 'mail.read', {'source': 'awaiting_theirs'}), 'GMAIL:theirs')
