"""Modelsiz ileriye dönük haftalık plan (18 Ekim 2026): "bu haftam nasıl", "haftaya ne var".

Gerçek profil JSON'u ve gerçek EngineContext.handle; Google taklit, model çağrılırsa test düşer.
Gerçek Google Takvim ve PC'de denenmedi.
"""
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from modules import main_planner
from test_mail_calendar_fixes import ProfileCase, _runtime, say

TZ = datetime.now().astimezone().tzinfo


def g(day, hhmm, name):
    """Google etkinliği: (gün, başlangıç ya da tüm gün için None, ad)."""
    d = date.fromisoformat(day)
    start = datetime.fromisoformat(f'{day}T{hhmm}').replace(tzinfo=TZ) if hhmm else None
    return d, start, name


class WeekPlanTests(ProfileCase):
    now = datetime(2026, 10, 17, 10, 0)        # cumartesi; bu hafta 17-18, gelecek hafta 19-25 Ekim

    def setUp(self):
        super().setUp()
        p = self.profile
        p.add_event('Dişçi', '2026-10-17T09:00')
        p.add_event('Sunum', '2026-10-18T14:30')
        p.add_event('Ekip toplantısı', '2026-10-19T10:00')
        p.add_event('Yıllık rapor', '2026-10-21')
        p.add_event('İlaç', '2026-10-19T08:00', repeat='daily')
        p.data['tasks'] = [
            {'id': 1, 'text': 'Fatura öde', 'done': False, 'when': '2026-10-15'},
            {'id': 2, 'text': 'Raporu bitir', 'done': False, 'when': '2026-10-20T18:00'},
            {'id': 3, 'text': 'Eski iş', 'done': True, 'when': '2026-10-20'}]
        p.save()
        self.hb = patch('modules.handoff.brief_status', return_value=(None, None))
        self.hb.start()
        self.addCleanup(self.hb.stop)

    def rt(self, events=(), connected=True, fail=False):
        rt = _runtime(self, self.profile, self.now)
        calls = []

        def range_events(offset, days):
            calls.append((offset, days))
            if fail:
                raise OSError('ağ yok')
            return list(events)
        rt.google_api.connected = lambda: connected
        rt.google_api.range_events = range_events
        rt._calls = calls
        return rt

    GOOGLE = [g('2026-10-19', '10:15', 'Müşteri görüşmesi'), g('2026-10-22', None, 'Bayram'),
              g('2026-10-18', '14:30', 'Sunum')]               # sonuncusu Jarvis kaydıyla aynı: tek görünür

    def test_next_week_plan(self):
        rt = self.rt(self.GOOGLE)
        reply = say(rt, 'haftaya ne var')
        self.assertEqual(rt._calls, [(2, 7)])
        self.assertIn('Gelecek hafta planı (19–25 Ekim)', reply)
        self.assertIn('Pazartesi 19 Ekim: 08:00 İlaç; 10:00 Ekip toplantısı; 10:15 Müşteri görüşmesi', reply)
        self.assertIn('Çarşamba 21 Ekim: 08:00 İlaç; tüm gün Yıllık rapor', reply)
        self.assertIn('Perşembe 22 Ekim: 08:00 İlaç; tüm gün Bayram', reply)
        self.assertIn('Çakışabilir', reply)
        self.assertIn('Ekip toplantısı', reply.split('Çakışabilir')[1])
        self.assertIn('Fatura öde', reply)                      # gecikmiş görev
        self.assertIn('Raporu bitir', reply)
        self.assertNotIn('Eski iş', reply)
        self.assertNotIn('Dişçi', reply)

    def test_this_week_runs_from_today_to_sunday(self):
        reply = say(self.rt(self.GOOGLE), 'bu haftam nasıl')
        self.assertIn('Bu hafta planı (17–18 Ekim, bugünden pazara)', reply)
        self.assertIn('Cumartesi 17 Ekim: 09:00 Dişçi (geçti)', reply)
        self.assertIn('Pazar 18 Ekim: 14:30 Sunum', reply)
        self.assertEqual(reply.count('Sunum'), 1)               # Jarvis ve Google aynı kaydı iki kez göstermez
        self.assertNotIn('Ekip toplantısı', reply)

    def test_phrasings_ascii_and_typos(self):
        for text in ('bu haftanın planı', 'bu haftanin plani', 'haftalık planım', 'haftalik planim', 'bu hafta ne var',
                     'bu haftam nasil gecer', 'Bu haftam nasıl?', 'bu haftaki programım', 'haftamı söyle'):
            with self.subTest(text=text):
                self.assertIn('Bu hafta planı', say(self.rt(), text))
        for text in ('haftaya ne var', 'gelecek haftanın planı', 'gelecek hafta ne var', 'önümüzdeki hafta neler var',
                     'onumuzdeki hafta plani', 'haftaya neler var', 'haftaya ne yapıyoruz'):
            with self.subTest(text=text):
                self.assertIn('Gelecek hafta planı', say(self.rt(), text))
        reply = say(self.rt(), 'önümüzdeki 7 gün')
        self.assertIn('Önümüzdeki 7 gün planı (17–23 Ekim)', reply)

    def test_other_requests_are_not_hijacked(self):
        for text in ('haftalık özet', 'bu hafta neler oldu', 'haftalık plan yap', 'haftaya toplantı hatırlat',
                     'yarın planım ne', 'bugünün planı', 'haftaya kadar bitir', 'bu hafta sonu hava nasıl'):
            with self.subTest(text=text):
                self.assertIsNone(main_planner._week_range(main_planner._fold(text)))

    def test_google_failure_still_shows_local_items_and_says_so(self):
        reply = say(self.rt(fail=True), 'haftaya ne var')
        self.assertIn('Ekip toplantısı', reply)
        self.assertIn("Google Takvim'e bakamadım", reply)

    def test_not_connected_does_not_call_google_or_complain(self):
        rt = self.rt(connected=False)
        reply = say(rt, 'haftaya ne var')
        self.assertEqual(rt._calls, [])
        self.assertNotIn('bakamadım', reply)
        self.assertIn('Ekip toplantısı', reply)

    def test_empty_days_are_listed_compactly(self):
        self.profile.data['events'] = [e for e in self.profile.data['events'] if e['title'] != 'İlaç']
        self.profile.save()
        reply = say(self.rt(), 'haftaya ne var')
        self.assertIn('Boş günler: Salı, Perşembe, Cuma, Cumartesi, Pazar', reply)

    def test_expired_google_permission_gets_reconnect_help(self):
        rt = self.rt()
        def boom(offset, days):
            raise PermissionError('izin yok')
        rt.google_api.range_events = boom
        reply = say(rt, 'haftaya ne var')
        self.assertIn('Bağlan', reply)


if __name__ == '__main__':
    unittest.main()
