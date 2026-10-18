"""Hatırlatma silme ve erteleme (18 Ekim 2026): modelsiz, gerçek profil JSON'u, gerçek EngineContext.handle."""
import unittest
from datetime import datetime

from test_mail_calendar_fixes import ProfileCase, _runtime, say


class ReminderEditTests(ProfileCase):
    now = datetime(2026, 10, 17, 10, 0)

    def rt(self):
        return _runtime(self, self.profile, self.now)

    def titles(self):
        return sorted(e['title'] for e in self.reload().data['events'])

    def test_delete_by_title_and_persists(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00')
        self.profile.add_event('Dişçi', '2026-10-19T15:00')
        reply = say(self.rt(), 'ilaç hatırlatmasını sil')
        self.assertIn('Sildim: İlaç', reply)
        self.assertIn("Google Takvim'e dokunmadım", reply)
        self.assertEqual(self.titles(), ['Dişçi'])

    def test_delete_variants_and_ascii(self):
        for text in ('dişçi randevusunu kaldır', 'dişçi hatırlatmasını iptal et', 'disci hatirlatmasini sil'):
            with self.subTest(text=text):
                self.profile.add_event('Dişçi', '2026-10-19T15:00')
                self.profile.add_event('Başka', '2026-10-20T15:00')
                self.assertIn('Sildim: Dişçi', say(self.rt(), text))
                self.assertEqual(self.titles(), ['Başka'])
                self.profile.data['events'].clear()
                self.profile.save()

    def test_ambiguous_delete_asks_and_deletes_nothing(self):
        self.profile.add_event('Toplantı A', '2026-10-18T09:00')
        self.profile.add_event('Toplantı B', '2026-10-19T09:00')
        reply = say(self.rt(), 'hatırlatmayı sil')
        self.assertIn('Hangisini kastettin', reply)
        self.assertEqual(len(self.reload().data['events']), 2)

    def test_unknown_title_and_empty(self):
        self.assertIn('Kayıtlı bir hatırlatman yok', say(self.rt(), 'ilaç hatırlatmasını sil'))
        self.profile.add_event('Dişçi', '2026-10-19T15:00')
        self.assertIn("'kitap' adında bir kaydın yok", say(self.rt(), 'kitap hatırlatmasını sil'))
        self.assertEqual(self.titles(), ['Dişçi'])

    def test_notes_and_adding_are_not_hijacked(self):
        self.profile.add_event('Dişçi', '2026-10-19T15:00')
        say(self.rt(), 'yarın 10da dişçi hatırlat')
        self.assertEqual(len(self.reload().data['events']), 2)
        self.assertNotIn('Sildim', say(self.rt(), '1 numaralı notu sil'))

    def test_repeating_delete_says_all_repeats(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
        self.assertIn('bütün tekrarlarını', say(self.rt(), 'ilaç hatırlatmasını sil'))
        self.assertEqual(self.titles(), [])

    def test_postpone_future_by_minutes_hours_days(self):
        self.profile.add_event('Sunum', '2026-10-17T14:00')
        self.assertIn('10 dakika erteledim', say(self.rt(), 'sunum hatırlatmasını 10 dakika ertele'))
        self.assertEqual(self.reload().data['events'][0]['when'], '2026-10-17T14:10')
        say(self.rt(), 'sunumu 2 saat ertele')
        self.assertEqual(self.reload().data['events'][0]['when'], '2026-10-17T16:10')
        say(self.rt(), 'sunum randevusunu yarına ertele')
        self.assertEqual(self.reload().data['events'][0]['when'], '2026-10-18T16:10')
        say(self.rt(), 'sunum hatırlatmasını yarım saat ertele')
        self.assertEqual(self.reload().data['events'][0]['when'], '2026-10-18T16:40')

    def test_bare_postpone_snoozes_last_fired_reminder_from_now(self):
        self.profile.add_event('İlaç', '2026-10-17T09:30')
        self.profile.add_event('Başka', '2026-10-20T09:30')
        self.profile.data['events'][0]['notified'] = True
        self.profile.save()
        reply = say(self.rt(), 'ertele')
        self.assertIn('İlaç kaydını 10 dakika erteledim', reply)
        ev = [e for e in self.reload().data['events'] if e['title'] == 'İlaç'][0]
        self.assertEqual((ev['when'], ev['notified']), ('2026-10-17T10:10', False))     # şimdiden itibaren, tekrar çalar

    def test_postpone_refuses_repeating_and_allday_minutes(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
        self.assertIn('Tekrarlayan kaydı ertelemiyorum', say(self.rt(), 'ilaç hatırlatmasını ertele'))
        self.profile.data['events'].clear()
        self.profile.add_event('Hediye', '2026-10-20')
        self.assertIn('tüm gün kaydı', say(self.rt(), 'hediye hatırlatmasını 10 dakika ertele'))
        self.assertIn('erteledim', say(self.rt(), 'hediye hatırlatmasını 2 gün ertele'))
        self.assertEqual(self.reload().data['events'][0]['when'], '2026-10-22')

    def test_postponed_reminder_fires_again(self):
        self.profile.add_event('İlaç', '2026-10-17T09:30')
        self.assertEqual(len(self.profile.due_events(self.now)), 1)
        say(self.rt(), 'ilaç hatırlatmasını 30 dakika ertele')
        self.assertEqual(len(self.profile.due_events(datetime(2026, 10, 17, 10, 29))), 0)
        self.assertEqual(len(self.profile.due_events(datetime(2026, 10, 17, 10, 31))), 1)


if __name__ == '__main__':
    unittest.main()
