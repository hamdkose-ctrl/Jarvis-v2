"""Reminder migration parity: explicit model decisions, real Core/State/profile.

Turkish recognition belongs to live semantic acceptance. These cases exercise
persistence, recurrence, snooze, unique target and approval without resurrecting
the retired raw planner. Every mutation first crosses a real State approval.
"""
from datetime import datetime
import unittest
from unittest.mock import patch
from brain_turn_fixture import reminder_change, turn
from test_mail_calendar_fixes import ProfileCase, _runtime, typed_reminder_create


class ReminderCase(ProfileCase):
    now = datetime(2026, 10, 17, 10)

    def rt(self):
        return _runtime(self, self.profile, self.now)

    def change(self, operation, title=None, *, text='hatırlatmayı değiştir', **fields):
        args = {'operation': operation, **fields}
        if title is not None:
            args['title'] = title
        return reminder_change(self.rt(), text, args)

    def ev(self, title='İlaç'):
        return next(e for e in self.reload().data['events'] if e['title'] == title)

    def titles(self):
        return sorted(e['title'] for e in self.reload().data['events'])


class ReminderEditTests(ReminderCase):
    def test_delete_by_title_and_persists(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00')
        self.profile.add_event('Dişçi', '2026-10-19T15:00')
        reply = self.change('delete', 'İlaç')
        self.assertIn('Sildim: İlaç', reply)
        self.assertIn("Google Takvim'e dokunmadım", reply)
        self.assertEqual(self.titles(), ['Dişçi'])

    def test_delete_variants_and_ascii(self):
        for text in ('dişçi randevusunu kaldır', 'dişçi hatırlatmasını iptal et', 'disci hatirlatmasini sil'):
            with self.subTest(text=text):
                self.profile.add_event('Dişçi', '2026-10-19T15:00')
                self.profile.add_event('Başka', '2026-10-20T15:00')
                self.assertIn('Sildim: Dişçi', self.change('delete', 'Dişçi', text=text))
                self.assertEqual(self.titles(), ['Başka'])
                self.profile.data['events'].clear(); self.profile.save()

    def test_ambiguous_delete_asks_and_deletes_nothing(self):
        self.profile.add_event('Toplantı A', '2026-10-18T09:00')
        self.profile.add_event('Toplantı B', '2026-10-19T09:00')
        self.assertIn('netleştir', self.change('delete', target='only'))
        self.assertEqual(len(self.reload().data['events']), 2)

    def test_unknown_title_and_empty(self):
        self.assertIn('bulamadım', self.change('delete', 'İlaç'))
        self.profile.add_event('Dişçi', '2026-10-19T15:00')
        self.assertIn('bulamadım', self.change('delete', 'kitap'))
        self.assertEqual(self.titles(), ['Dişçi'])

    def test_notes_and_adding_are_not_hijacked(self):
        self.profile.add_event('Dişçi', '2026-10-19T15:00')
        typed_reminder_create(self.rt(), 'yarın 10da dişçi hatırlat', title='dişçi', when='2026-10-18T10:00')
        self.assertEqual(len(self.reload().data['events']), 2)
        before = list(self.reload().data['events'])
        rt = self.rt(); rt.chat = unittest.mock.Mock(return_value='CHAT')
        self.assertNotIn('Sildim', turn(rt, 'bu cümlede notu sil yazıyor'))
        self.assertEqual(self.reload().data['events'], before)

    def test_repeating_delete_says_all_repeats(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
        self.assertIn('bütün tekrarları', self.change('delete', 'İlaç'))
        self.assertEqual(self.titles(), [])

    def test_postpone_future_by_minutes_hours_days(self):
        self.profile.add_event('Sunum', '2026-10-17T14:00')
        for duration, expected in (('10 dakika', '2026-10-17T14:10'), ('2 saat', '2026-10-17T16:10'),
                                   ('yarına', '2026-10-18T16:10'), ('yarım saat', '2026-10-18T16:40')):
            self.assertIn('erteledim', self.change('postpone', 'Sunum', duration=duration))
            self.assertEqual(self.ev('Sunum')['when'], expected)

    def test_bare_postpone_snoozes_last_fired_reminder_from_now(self):
        self.profile.add_event('İlaç', '2026-10-17T09:30')
        self.profile.add_event('Başka', '2026-10-20T09:30')
        self.profile.data['events'][0]['notified'] = True; self.profile.save()
        self.assertIn('İlaç', self.change('postpone', target='last_fired', duration='10 dakika', occurrence='fired'))
        self.assertEqual((self.ev()['when'], self.ev()['notified']), ('2026-10-17T10:10', False))

    def test_postpone_allday_minutes_refused_days_ok(self):
        self.profile.add_event('Hediye', '2026-10-20')
        self.assertIn('tüm gün kaydı', self.change('postpone', 'Hediye', duration='10 dakika'))
        self.assertIn('erteledim', self.change('postpone', 'Hediye', duration='2 gün'))
        self.assertEqual(self.ev('Hediye')['when'], '2026-10-22')

    def test_postponed_reminder_fires_again(self):
        self.profile.add_event('İlaç', '2026-10-17T09:30')
        self.assertEqual(len(self.profile.due_events(self.now)), 1)
        self.change('postpone', 'İlaç', duration='30 dakika', occurrence='fired')
        self.assertEqual(self.profile.due_events(datetime(2026, 10, 17, 10, 29)), [])
        self.assertEqual(len(self.profile.due_events(datetime(2026, 10, 17, 10, 31))), 1)


class RepeatingEditTests(ReminderCase):
    def test_postpone_next_occurrence_only(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
        reply = self.change('postpone', 'İlaç', duration='1 saat', on_date='yarınki')
        self.assertIn('yarın 10:00', reply); self.assertIn('09:00', reply)
        e = self.ev()
        self.assertEqual((e['when'], e['base'], e['repeat']), ('2026-10-18T10:00', '09:00', 'daily'))
        self.assertEqual(self.reload().events_on('2026-10-19')[0]['when'], '2026-10-19T09:00')

    def test_shifted_occurrence_fires_then_rule_returns_to_base_time(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
        self.change('postpone', 'İlaç', duration='1 saat')
        p = self.reload()
        self.assertEqual(p.due_events(datetime(2026, 10, 18, 9, 30)), [])
        self.assertEqual(len(p.due_events(datetime(2026, 10, 18, 10, 1))), 1)
        self.assertEqual(p.data['events'][0]['when'], '2026-10-19T09:00')
        self.assertNotIn('base', p.data['events'][0])

    def test_ascii_and_typo_variants(self):
        for duration in ('1 saat', 'bir saat'):
            self.profile.data['events'].clear()
            self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
            self.change('postpone', 'İlaç', duration=duration)
            self.assertEqual(self.ev()['when'], '2026-10-18T10:00')

    def test_move_to_weekday(self):
        self.profile.add_event('Toplantı', '2026-10-19T10:00', repeat='weekly:0')
        self.assertIn('23 Ekim 10:00', self.change('postpone', 'Toplantı', schedule='cumaya'))
        self.assertEqual(self.ev('Toplantı')['when'], '2026-10-23T10:00')
        self.assertNotIn('base', self.ev('Toplantı'))
        self.change('postpone', 'Toplantı', schedule='pazartesiye')
        self.assertEqual(self.ev('Toplantı')['when'], '2026-10-19T10:00')

    def test_move_past_regular_occurrences_says_so(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
        self.assertIn('Aradaki', self.change('postpone', 'İlaç', schedule='cumaya'))
        self.assertEqual(self.ev()['when'], '2026-10-23T09:00')

    def test_move_one_off_event_and_not_hijacking(self):
        self.profile.add_event('Sunum', '2026-10-19T14:00')
        self.assertIn('Sunum', self.change('postpone', 'Sunum', schedule='cumaya'))
        self.assertEqual(self.ev('Sunum')['when'], '2026-10-23T14:00')
        from modules import main_planner
        self.assertFalse(hasattr(main_planner, '_edit_reminder'))
        rt = self.rt(); rt.chat = unittest.mock.Mock(return_value='CHAT')
        for text in ('sayfayı aşağı kaydır', 'ekranı yukarı kaydır', 'oyunu atla', 'reklamı atla', 'bugünkü reklamı atla'):
            before = list(self.reload().data['events'])
            self.assertEqual(turn(rt, text), 'CHAT')
            self.assertEqual(self.reload().data['events'], before)

    def test_skip_today_and_ascii(self):
        for qualifier in ('bugünkü', 'bugunku'):
            self.profile.data['events'].clear()
            self.profile.add_event('İlaç', '2026-10-17T18:00', repeat='daily')
            self.assertIn('atladım', self.change('skip', target='only', on_date=qualifier))
            self.assertEqual(self.ev()['when'], '2026-10-18T18:00')

    def test_skip_clears_shift_and_uses_rule(self):
        self.profile.add_event('Toplantı', '2026-10-19T10:00', repeat='weekly:0')
        self.change('postpone', 'Toplantı', schedule='cumaya')
        self.change('skip', 'Toplantı')
        self.assertEqual(self.ev('Toplantı')['when'], '2026-10-26T10:00')
        self.assertNotIn('base', self.ev('Toplantı'))

    def test_day_qualifier_mismatch_changes_nothing(self):
        self.profile.add_event('İlaç', '2026-10-19T09:00', repeat='weekly:0')
        self.assertIn('yarınki', self.change('skip', 'İlaç', on_date='yarınki'))
        self.assertEqual(self.ev()['when'], '2026-10-19T09:00')

    def test_skip_one_off_is_refused(self):
        self.profile.add_event('Dişçi', '2026-10-19T15:00')
        self.assertIn('Silmeyi', self.change('skip', 'Dişçi'))
        self.assertEqual(self.ev('Dişçi')['when'], '2026-10-19T15:00')

    def test_bare_postpone_does_not_touch_repeating_only(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
        self.assertIn('bulamadım', self.change('postpone', target='last_fired', duration='10 dakika', occurrence='fired'))
        self.assertEqual(self.ev()['when'], '2026-10-18T09:00')

    def test_delete_still_removes_all_repeats(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
        self.assertIn('bütün tekrarları', self.change('delete', 'İlaç'))
        self.assertEqual(self.titles(), [])


class RepeatSnoozeTests(ReminderCase):
    def fire(self):
        self.profile.add_event('İlaç', '2026-10-17T09:30', repeat='daily')
        self.assertEqual(len(self.profile.due_events(self.now)), 1)

    def test_bare_postpone_snoozes_without_moving_next_occurrence(self):
        self.fire()
        self.assertIn('yeniden çalacak', self.change('postpone', target='last_fired', duration='10 dakika', occurrence='fired'))
        e = self.ev()
        self.assertEqual((e['snooze'], e['when']), ('2026-10-17T10:10', '2026-10-18T09:30'))
        p = self.reload()
        self.assertEqual(p.due_events(datetime(2026, 10, 17, 10, 9)), [])
        self.assertEqual(len(p.due_events(datetime(2026, 10, 17, 10, 11))), 1)
        self.assertEqual(p.due_events(datetime(2026, 10, 17, 10, 12)), [])
        self.assertEqual(p.data['events'][0]['when'], '2026-10-18T09:30')
        self.assertNotIn('snooze', p.data['events'][0])

    def test_named_and_ascii_snooze(self):
        for duration, want in (('yarım saat', '2026-10-17T10:30'), ('1 saat', '2026-10-17T11:00')):
            self.profile.data['events'].clear(); self.fire()
            self.change('postpone', 'İlaç', duration=duration, occurrence='fired')
            self.assertEqual(self.ev()['snooze'], want)

    def test_tomorrow_qualifier_days_and_stale_fire_move_next_occurrence_instead(self):
        for duration, expected in (('1 saat', '2026-10-18T10:30'), ('1 gün', '2026-10-19T09:30')):
            self.profile.data['events'].clear(); self.fire()
            self.change('postpone', 'İlaç', duration=duration, occurrence='next')
            self.assertEqual((self.ev()['when'], self.ev().get('snooze')), (expected, None))
        self.profile.data['events'].clear()
        self.profile.add_event('İlaç', '2026-10-18T09:30', repeat='daily')
        self.change('postpone', 'İlaç', duration='10 dakika')
        self.assertEqual((self.ev()['when'], self.ev().get('snooze')), ('2026-10-18T09:40', None))

    def test_bare_postpone_picks_latest_fired_among_one_off_and_repeating(self):
        self.profile.add_event('Eski', '2026-10-17T08:00')
        self.profile.data['events'][0]['notified'] = True; self.profile.save(); self.fire()
        self.assertIn('İlaç', self.change('postpone', target='last_fired', duration='10 dakika', occurrence='fired'))
        self.assertNotIn('snooze', self.ev('Eski'))

    def test_failed_save_leaves_no_snooze(self):
        self.fire(); p = self.reload(); eid = p.data['events'][0]['id']
        with patch.object(p, 'save', side_effect=OSError('disk dolu')):
            with self.assertRaises(OSError): p.snooze_event(eid, '2026-10-17T10:10')
        self.assertNotIn('snooze', p.data['events'][0])
        self.assertTrue(p.snooze_event(eid, '2026-10-17T10:10'))
        self.assertEqual(self.ev()['snooze'], '2026-10-17T10:10')


class SnoozeWordingTests(ReminderCase):
    fire = RepeatSnoozeTests.fire
    def test_after_n_minutes_again_variants_snooze(self):
        self.fire()
        for duration, want in (('10 dk', '2026-10-17T10:10'), ('5 dakika', '2026-10-17T10:05'), ('1 saat', '2026-10-17T11:00')):
            self.change('postpone', target='last_fired', duration=duration, occurrence='fired')
            self.assertEqual((self.ev()['snooze'], self.ev()['when']), (want, '2026-10-18T09:30'))

    def test_day_part_snooze_and_next_occurrence_shift(self):
        self.fire()
        self.change('postpone', target='last_fired', schedule='akşama', occurrence='fired')
        self.assertEqual((self.ev()['snooze'], self.ev()['when']), ('2026-10-17T18:00', '2026-10-18T09:30'))
        self.change('postpone', 'İlaç', schedule='yarın sabah', occurrence='next')
        self.assertEqual(self.ev()['when'], '2026-10-18T09:00')

    def test_adding_a_new_reminder_is_not_hijacked(self):
        self.fire()
        for title, when in (('toplantı', '2026-10-17T10:10'), ('ilacı', '2026-10-18T09:00'), ('su iç', '2026-10-17T12:00')):
            before = len(self.reload().data['events'])
            typed_reminder_create(self.rt(), f'{title} hatırlat', title=title, when=when)
            self.assertEqual(len(self.reload().data['events']), before + 1)
            self.profile.data['events'] = self.profile.data['events'][:1]; self.profile.save()
