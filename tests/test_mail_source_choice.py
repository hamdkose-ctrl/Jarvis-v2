""""Önemli maillerim" kaynak seçimi (18 Ekim 2026): Gmail mi Outlook mu, ikisi de yoksa ne denir.

Gmail ve Outlook taklittir; gerçek hesapta/PC'de denenmedi.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from modules import engine_tools, google_api, outlook, worktrack


def route(text, *, outlook_on, google_on):
    rt = SimpleNamespace(google_api=google_api)
    ready = None if google_on else google_api.SETUP_HELP
    with patch.object(google_api, 'important', return_value=[{'who': 'Ayşe', 'subject': 'Not', 'starred': True}]), \
            patch.object(google_api, '_ready', return_value=ready), \
            patch.object(google_api, 'connected', return_value=google_on), \
            patch.object(outlook, 'installed', return_value=outlook_on), \
            patch.object(outlook, 'unread_mail', side_effect=lambda *a, **k: k.get('prefix', '') + 'OUTLOOK-LISTE'), \
            patch.object(worktrack, 'report', return_value='ISTAKIP'):
        return worktrack.handle(text) or engine_tools._mail_handle(rt, text)


class SourceChoiceTests(unittest.TestCase):
    def test_both_available_gmail_answers_and_names_the_work_mail_way(self):
        r = route('önemli maillerim', outlook_on=True, google_on=True)
        self.assertIn('Gmail', r)
        self.assertIn('Ayşe', r)
        self.assertIn('iş maillerimi kontrol et', r)

    def test_only_gmail_has_no_outlook_hint(self):
        r = route('önemli maillerim', outlook_on=False, google_on=True)
        self.assertIn('Ayşe', r)
        self.assertNotIn('Outlook', r)

    def test_outlook_only_says_it_cannot_rank_and_lists_unread(self):
        r = route('önemli maillerim', outlook_on=True, google_on=False)
        self.assertIn('OUTLOOK-LISTE', r)
        self.assertIn('Gmail bağlı değil', r)
        self.assertIn('önem', r)

    def test_neither_says_so_clearly(self):
        r = route('önemli maillerim', outlook_on=False, google_on=False)
        self.assertIn('Google bağlantısı kurulu değil', r)
        self.assertIn('Outlook', r)

    def test_work_word_between_goes_to_outlook(self):
        for text in ('iş önemli maillerim', 'iş mailimde önemli olan var mı', 'outlook önemli mailler'):
            with self.subTest(text=text):
                r = route(text, outlook_on=True, google_on=True)
                self.assertIn('OUTLOOK-LISTE', r)
                self.assertIn('önem', r)

    def test_priority_wording_is_mail_not_work_report(self):
        for outlook_on, google_on in ((True, True), (True, False), (False, False)):
            with self.subTest(outlook=outlook_on, google=google_on):
                r = route('öncelikli maillerim neler', outlook_on=outlook_on, google_on=google_on)
                self.assertNotEqual(r, 'ISTAKIP')

    def test_work_priority_without_mail_word_stays_work_report(self):
        self.assertEqual(route('önceliklerim neler', outlook_on=True, google_on=True), 'ISTAKIP')


if __name__ == '__main__':
    unittest.main()
