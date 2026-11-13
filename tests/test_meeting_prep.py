"""Toplantı hazırlığı özeti (18 Ekim 2026): yalnız okur, modele gitmez; gerçek profil JSON'u + gerçek EngineContext.handle."""
import unittest
from datetime import datetime
from unittest.mock import patch

from test_mail_calendar_fixes import ProfileCase, _runtime
from brain_turn_fixture import turn
from modules import google_api, meeting_prep, outlook


class MeetingPrepTests(ProfileCase):
    now = datetime(2026, 10, 17, 10, 0)

    def rt(self):
        return _runtime(self, self.profile, self.now)

    def patches(self, gmail=(), olook=None, g_events=None, g_ready=None, g_fail=False):
        """Gmail/Outlook/Google Takvim taklidi; Outlook kurulu değilse olook=None."""
        calls = {'gmail': [], 'outlook': []}

        def search(words, days=30, limit=5):
            calls['gmail'].append(words)
            if g_fail:
                raise RuntimeError('secret-detail')
            return list(gmail)

        def osearch(words, days=30, limit=5):
            calls['outlook'].append(words)
            return list(olook)

        def events(a, b):
            return list(g_events or [])
        ps = [patch.object(google_api, '_ready', return_value=g_ready), patch.object(google_api, 'search_mail', side_effect=search),
              patch.object(google_api, 'range_events', side_effect=events),
              patch.object(outlook, 'installed', return_value=olook is not None),
              patch.object(outlook, 'search_recent', side_effect=osearch)]
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        return calls

    def test_next_meeting_with_related_mails_from_both_sources(self):
        self.profile.add_event('Ahmet ile teklif toplantısı', '2026-10-18T14:00')
        self.profile.add_event('Dişçi', '2026-10-17T15:00')
        calls = self.patches(gmail=[{'who': 'Ahmet Yılmaz', 'subject': 'Teklif taslağı', 'days': 2}],
                             olook=[{'who': 'Ayşe', 'subject': 'Teklif fiyatları', 'days': 0}])
        reply = turn(self.rt(), 'toplantıma hazırlan', 'calendar.read', {'view': 'meeting_prep', 'period': None})
        self.assertIn('yarın 14:00', reply)
        self.assertIn('Ahmet ile teklif toplantısı (Jarvis kaydı)', reply)
        self.assertIn('Gmail: Ahmet Yılmaz · Teklif taslağı (2 gün önce)', reply)
        self.assertIn('Outlook: Ayşe · Teklif fiyatları (bugün)', reply)
        self.assertIn('hiçbir şey göndermedim', reply)
        self.assertEqual(calls['gmail'], [['ahmet', 'teklif']])
        self.assertEqual(calls['outlook'], [['ahmet', 'teklif']])

    def test_name_hint_picks_that_meeting_and_google_events_count(self):
        self.profile.add_event('Mehmet ile toplantı', '2026-10-17T16:00')
        self.patches(g_events=[(self.now.date(), self.now.replace(hour=12), 'Ayşe Demir sunumu')])
        reply = turn(self.rt(), "Ayşe'yle sunuma hazırlan", 'calendar.read', {'view': 'meeting_prep', 'period': None, 'query': 'Ayşe'})
        self.assertIn('bugün 12:00 · Ayşe Demir sunumu (Google Takvim)', reply)
        self.assertNotIn('Mehmet', reply)

    def test_no_meeting_and_no_keyword_and_no_match(self):
        self.patches()
        self.assertIn('hazırlanacak bir toplantı görünmüyor', turn(self.rt(), 'sıradaki toplantım için hazırlık yap', 'calendar.read', {'view': 'meeting_prep', 'period': None}))
        self.profile.add_event('Haftalık toplantı', '2026-10-17T15:00')
        self.assertIn('ayırt edici sözcük yok', turn(self.rt(), 'toplantıma hazırlan', 'calendar.read', {'view': 'meeting_prep', 'period': None}))
        self.profile.add_event('Bütçe toplantısı', '2026-10-17T11:00')
        self.assertIn('geçen mail bulamadım', turn(self.rt(), 'toplantıma hazırlan', 'calendar.read', {'view': 'meeting_prep', 'period': None}))

    def test_source_failure_is_friendly_and_leaks_nothing(self):
        self.profile.add_event('Bütçe toplantısı', '2026-10-17T11:00')
        self.patches(g_fail=True)
        reply = turn(self.rt(), 'toplantıma hazırlan', 'calendar.read', {'view': 'meeting_prep', 'period': None})
        self.assertIn("Gmail'e bakamadım", reply)
        self.assertNotIn('secret-detail', reply)
        self.assertNotIn('RuntimeError', reply)

    def test_not_hijacking_other_meeting_commands(self):
        self.patches()
        for text in ('yarın 10da toplantı ekle', 'toplantıyı yarına ertele', 'bugün toplantı var mı', 'derse hazırlan'):
            with self.subTest(text=text):
                self.assertFalse(meeting_prep.asked(text))

    def test_source_is_read_only_and_never_calls_a_model(self):
        import inspect
        src = inspect.getsource(meeting_prep)
        for bad in ('runtime.ask', 'llm.', '.Send(', '.Reply(', 'ask('):
            self.assertNotIn(bad, src)
        osrc = inspect.getsource(outlook.search_recent)
        for bad in ('.Send(', '.Save(', '.Delete(', '.Move(', 'UnRead'):
            self.assertNotIn(bad, osrc)


if __name__ == '__main__':
    unittest.main()
