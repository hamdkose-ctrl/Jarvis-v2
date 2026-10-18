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

    def test_postpone_allday_minutes_refused_days_ok(self):
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


class RepeatingEditTests(ProfileCase):
    """Tekrarlayan hatırlatmayı yalnız sıradaki oluşum için ertele / başka güne kaydır / atla (18 Ekim 2026)."""
    now = datetime(2026, 10, 17, 10, 0)       # cumartesi

    def rt(self):
        return _runtime(self, self.profile, self.now)

    def ev(self, title='İlaç'):
        return [e for e in self.reload().data['events'] if e['title'] == title][0]

    def test_postpone_next_occurrence_only(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
        reply = say(self.rt(), 'yarınki ilaç hatırlatmasını 1 saat ertele')
        self.assertIn('yarın 10:00', reply)
        self.assertIn('09:00', reply)                                   # sonrakilerin eski saatte kaldığı söylenir
        e = self.ev()
        self.assertEqual((e['when'], e['base'], e['repeat']), ('2026-10-18T10:00', '09:00', 'daily'))
        self.assertEqual(self.reload().events_on('2026-10-19')[0]['when'], '2026-10-19T09:00')
        self.assertEqual(self.reload().events_on('2026-10-18')[0]['when'], '2026-10-18T10:00')

    def test_shifted_occurrence_fires_then_rule_returns_to_base_time(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
        say(self.rt(), 'yarınki ilaç hatırlatmasını 1 saat ertele')
        p = self.reload()
        self.assertEqual(p.due_events(datetime(2026, 10, 18, 9, 30)), [])
        self.assertEqual(len(p.due_events(datetime(2026, 10, 18, 10, 1))), 1)
        e = p.data['events'][0]
        self.assertEqual(e['when'], '2026-10-19T09:00')                  # kural eski saatine döndü
        self.assertNotIn('base', e)

    def test_ascii_and_typo_variants(self):
        for text in ('yarinki ilac hatirlatmasini 1 saat otele', 'yarınki ilacı 1 saat ertele', 'YARINKİ İlaç hatırlatmasını bir saat ertele'):
            with self.subTest(text=text):
                self.profile.data['events'].clear()
                self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
                say(self.rt(), text)
                self.assertEqual(self.ev()['when'], '2026-10-18T10:00')

    def test_move_to_weekday(self):
        self.profile.add_event('Toplantı', '2026-10-19T10:00', repeat='weekly:0')      # pazartesi
        reply = say(self.rt(), 'bu haftaki toplantı hatırlatmasını cumaya kaydır')
        self.assertIn('23 Ekim 10:00', reply)
        e = self.ev('Toplantı')
        self.assertEqual(e['when'], '2026-10-23T10:00')
        self.assertNotIn('base', e)                                      # saat değişmedi, kaydırılan yalnız gün
        say(self.rt(), 'toplantıyı pazartesiye kaydir')
        self.assertEqual(self.ev('Toplantı')['when'], '2026-10-19T10:00')

    def test_move_past_regular_occurrences_says_so(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
        reply = say(self.rt(), 'ilaç hatırlatmasını cumaya kaydır')
        self.assertEqual(self.ev()['when'], '2026-10-23T09:00')
        self.assertIn('Aradaki', reply)

    def test_move_one_off_event_and_not_hijacking(self):
        self.profile.add_event('Sunum', '2026-10-19T14:00')
        self.assertIn('Sunum', say(self.rt(), 'sunumu cumaya kaydır'))
        self.assertEqual(self.ev('Sunum')['when'], '2026-10-23T14:00')
        from modules import main_planner
        for text in ('sayfayı aşağı kaydır', 'ekranı yukarı kaydır', 'oyunu atla', 'reklamı atla', 'bugünkü reklamı atla'):
            with self.subTest(text=text):
                self.assertIsNone(main_planner._edit_reminder(self.rt(), text, self.now))

    def test_skip_today_and_ascii(self):
        self.profile.add_event('İlaç', '2026-10-17T18:00', repeat='daily')
        reply = say(self.rt(), 'bugünkünü atla')
        self.assertIn('atladım', reply)
        self.assertEqual(self.ev()['when'], '2026-10-18T18:00')
        self.profile.data['events'].clear()
        self.profile.add_event('İlaç', '2026-10-17T18:00', repeat='daily')
        say(self.rt(), 'bugunku hatirlatmayi atla')
        self.assertEqual(self.ev()['when'], '2026-10-18T18:00')

    def test_skip_clears_shift_and_uses_rule(self):
        self.profile.add_event('Toplantı', '2026-10-19T10:00', repeat='weekly:0')
        say(self.rt(), 'toplantıyı cumaya kaydır')
        say(self.rt(), 'toplantı hatırlatmasını atla')
        e = self.ev('Toplantı')
        self.assertEqual(e['when'], '2026-10-26T10:00')                  # sıradaki pazartesi
        self.assertNotIn('base', e)

    def test_day_qualifier_mismatch_changes_nothing(self):
        self.profile.add_event('İlaç', '2026-10-19T09:00', repeat='weekly:0')
        reply = say(self.rt(), 'yarınki ilacı atla')
        self.assertIn('yarın', reply)
        self.assertEqual(self.ev()['when'], '2026-10-19T09:00')

    def test_skip_one_off_is_refused(self):
        self.profile.add_event('Dişçi', '2026-10-19T15:00')
        self.assertIn('silmeyi', say(self.rt(), 'dişçi hatırlatmasını atla'))
        self.assertEqual(self.ev('Dişçi')['when'], '2026-10-19T15:00')

    def test_bare_postpone_does_not_touch_repeating_only(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
        self.assertIn('Hangisini', say(self.rt(), 'ertele'))
        self.assertEqual(self.ev()['when'], '2026-10-18T09:00')

    def test_delete_still_removes_all_repeats(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
        self.assertIn('bütün tekrarlarını', say(self.rt(), 'ilaç hatırlatmasını sil'))


if __name__ == '__main__':
    unittest.main()
