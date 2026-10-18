"""Modelsiz "bugünün planı" (17 Ekim 2026).

Takvim (Jarvis + Google), sıradaki iş, gecikmiş/bugünkü görevler ve okunmamış mail sayısı tek cevapta toplanır.
Gerçek profil JSON'u ve gerçek EngineContext.handle; Google taklit, model çağrılırsa test düşer.
"""
import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from test_mail_calendar_fixes import ProfileCase, _runtime, say


def _google(events=(), unread=3, connected=True, fail=False):
    def day_events(offset):
        if fail:
            raise OSError('ağ yok')
        return list(events)

    def unread_count():
        if fail:
            raise OSError('ağ yok')
        return unread
    return dict(connected=lambda: connected, day_events=day_events, unread_count=unread_count)


class DayPlanTests(ProfileCase):
    now = datetime(2026, 10, 17, 10, 0)      # cumartesi

    def rt(self, **google):
        rt = _runtime(self, self.profile, self.now)
        for k, v in _google(**google).items():
            setattr(rt.google_api, k, v)
        return rt

    def setUp(self):
        super().setUp()
        self.handoff = patch('modules.handoff.brief_status', return_value=(None, None))
        self.handoff.start()
        self.addCleanup(self.handoff.stop)

    def test_full_plan_without_model(self):
        self.profile.add_event('Dişçi', '2026-10-17T09:00')
        self.profile.add_event('Sunum', '2026-10-17T14:30')
        self.profile.add_event('Anneme hediye', '2026-10-17')
        self.profile.data['tasks'] = [
            {'id': 1, 'text': 'Fatura öde', 'done': False, 'when': '2026-10-15'},
            {'id': 2, 'text': 'Raporu bitir', 'done': False, 'when': '2026-10-17T18:00'},
            {'id': 3, 'text': 'Kitap oku', 'done': False, 'when': ''},
            {'id': 4, 'text': 'Eski iş', 'done': True, 'when': '2026-10-10'}]
        tz = datetime.now().astimezone().tzinfo
        google = [(datetime(2026, 10, 17, 12, 0, tzinfo=tz), 'Proje toplantısı')]
        reply = say(self.rt(events=google, unread=5), 'bugünün planı ne')
        self.assertIn('Bugünün planı (17 Ekim Cumartesi)', reply)
        self.assertIn('09:00 Dişçi (geçti); 12:00 Proje toplantısı; 14:30 Sunum; tüm gün Anneme hediye', reply)
        self.assertIn('Sıradaki: 12:00 Proje toplantısı, 2 saat sonra.', reply)
        self.assertIn('1 gecikmiş (Fatura öde)', reply)
        self.assertIn('bugün 1 (Raporu bitir)', reply)
        self.assertIn('ayrıca 1 açık görev', reply)
        self.assertNotIn('Eski iş', reply)
        self.assertIn("Gmail'de 5 okunmamış mail var.", reply)

    def test_variants_reach_plan(self):
        for text in ('bugun planim ne', 'planımı söyle', 'bugün ne yapmalıyım', 'günümü planla', 'Bugünün planı'):
            with self.subTest(text=text):
                self.assertIn('Bugünün planı', say(self.rt(), text))

    def test_tomorrow_plan_skips_mail_and_past_marks(self):
        self.profile.add_event('Toplantı', '2026-10-18T09:00')
        reply = say(self.rt(unread=9), 'yarın planım ne')
        self.assertIn('Yarının planı (18 Ekim Pazar)', reply)
        self.assertIn('09:00 Toplantı', reply)
        self.assertNotIn('geçti', reply)
        self.assertNotIn('Gmail', reply)

    def test_empty_day_and_google_not_connected(self):
        reply = say(self.rt(connected=False), 'bugünün planı')
        self.assertIn('Takviminde bir şey yok.', reply)
        self.assertNotIn('Gmail', reply)

    def test_google_failure_is_said_not_hidden(self):
        self.profile.add_event('Dişçi', '2026-10-17T15:00')
        reply = say(self.rt(fail=True), 'bugünün planı')
        self.assertIn('15:00 Dişçi', reply)
        self.assertIn("Google Takvim'e bakamadım ve Gmail'e bakamadım.", reply)

    def test_expired_google_permission_says_reconnect_in_plain_turkish(self):
        """Süresi dolan/geri alınan Google izni (invalid_grant): cevap ne yapılacağını söyler, tek cümlede."""
        def boom(*a, **k):
            raise Exception("('invalid_grant: Token has been expired or revoked.', {'error': 'invalid_grant'})")
        rt = self.rt()
        rt.google_api.day_events = boom
        rt.google_api.unread_count = boom
        reply = say(rt, 'bugünün planı')
        self.assertIn('Google izni çalışmıyor', reply)
        self.assertIn('“Bağlan” düğmesine basıp izni yenile', reply)
        self.assertEqual(reply.count('Google izni çalışmıyor'), 1)       # Takvim ve Gmail aynı izin: bir kez söylenir
        self.assertNotIn('invalid_grant', reply)

    def test_handoff_line_and_failure_are_both_said(self):
        with patch('modules.handoff.brief_status', return_value=('Ev için bekleyen 2 devir notu var: çizim.', None)):
            self.assertIn('2 devir notu', say(self.rt(), 'bugünün planı'))
        problem = 'Google Görevler izni yok ya da çalışmıyor. Menü › Yapay zekâ › Gmail ve Takvim bölümünde “Görevler iznini ver” düğmesine bas.'
        with patch('modules.handoff.brief_status', return_value=(None, problem)):
            reply = say(self.rt(), 'bugünün planı')
        self.assertIn('Devir notlarına bakamadım', reply)
        self.assertIn('“Görevler iznini ver”', reply)
        with patch('modules.handoff.brief_status', return_value=(None, problem)):
            self.assertNotIn('Devir', say(self.rt(), 'yarın planım ne'))      # yalnız bugünün planında

    def test_duplicate_jarvis_and_google_entry_shown_once(self):
        self.profile.add_event('Sunum', '2026-10-17T14:30')
        tz = datetime.now().astimezone().tzinfo
        reply = say(self.rt(events=[(datetime(2026, 10, 17, 14, 30, tzinfo=tz), 'sunum')]), 'bugünün planı')
        calendar = reply.split('Takvim: ')[1].split('.')[0]
        self.assertEqual(calendar.lower().count('14:30 sunum'), 1)

    def test_other_plans_are_not_hijacked(self):
        for text in ('çalışma planım', 'proje planım ne durumda'):
            with self.subTest(text=text):
                self.assertIsNone(__import__('modules.main_planner', fromlist=['x'])._PLAN_ASK.search(text))

    def test_agenda_questions_unchanged(self):
        self.profile.add_event('Dişçi', '2026-10-17T15:00')
        reply = say(self.rt(), 'bugün ne var')
        self.assertNotIn('planı', reply)
        self.assertIn('Dişçi', reply)


class HandoffStatusTests(unittest.TestCase):
    def test_not_connected_is_silent_permission_and_other_errors_are_explained(self):
        from modules import handoff
        with patch.object(handoff, 'ready', return_value=False):
            self.assertEqual(handoff.brief_status(), (None, None))
        with patch.object(handoff, 'ready', return_value=True), \
                patch.object(handoff, 'pending', side_effect=Exception("('invalid_grant: Token has been expired or revoked.')")):
            line, problem = handoff.brief_status()
            self.assertIsNone(line)
            self.assertIn('“Görevler iznini ver”', problem)
            self.assertIsNone(handoff.brief_line())                         # açılış duyurusu eskisi gibi sessiz
        with patch.object(handoff, 'ready', return_value=True), \
                patch.object(handoff, 'pending', side_effect=OSError('ağ yok')):
            self.assertEqual(handoff.brief_status(), (None, 'Devir notlarına bakamadım (Google Görevler).'))
        with patch.object(handoff, 'ready', return_value=True), patch.object(handoff, 'place', return_value='ev'), \
                patch.object(handoff, 'pending', return_value=[{'id': '1', 'where': 'ev', 'text': 'çizim', 'due': ''}]):
            self.assertIn('1 devir notu', handoff.brief_status()[0])


if __name__ == '__main__':
    unittest.main()
