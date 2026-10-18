"""GPT'nin #74-#84 incelemesindeki mail/takvim maddeleri (18 Ekim 2026): önce başarısız olan testler.

10 "her 2 günde" tek seferlik kayıt olmasın, 11 tekrarlayan kayıt plan ve çakışmada görünsün,
12 yarının planında gecikme gerçek bugüne göre, 13 sınırlı tarama söylensin, 15 To adresi tam eşleşsin,
16 "cevap vermediğim maillere cevap yaz" salt okunur listeye düşmesin.
"""
import time
import unittest
from datetime import datetime
from unittest.mock import patch

from modules import google_api
from modules import when as whenmod
from test_day_plan import _google
from test_mail_awaiting import DAY, FakeGmail, ME, _msg
from test_mail_calendar_fixes import ProfileCase, _runtime, say


class EveryTwoDaysTests(ProfileCase):
    now = datetime(2026, 10, 17, 10, 0)

    def test_every_n_days_is_unknown_not_one_off(self):
        for text in ("her 2 günde 9'da ilaç hatırlat", 'her 3 gunde 9da ilac hatirlat', 'iki günde bir ilaç hatırlat'):
            with self.subTest(text=text):
                rule, _ = whenmod.parse_repeat(text)
                self.assertEqual(rule, 'unknown')
        reply = say(_runtime(self, self.profile, self.now), "her 2 günde 9'da ilaç hatırlat")
        self.assertIn('anlayamadım', reply)
        self.assertEqual(self.reload().data['events'], [])

    def test_plain_every_day_still_works(self):
        self.assertEqual(whenmod.parse_repeat("her gün 9'da ilaç")[0], 'daily')


class RecurringInPlanTests(ProfileCase):
    now = datetime(2026, 10, 17, 10, 0)      # cumartesi

    def setUp(self):
        super().setUp()
        p = patch('modules.handoff.brief_line', return_value=None)
        p.start()
        self.addCleanup(p.stop)

    def rt(self):
        rt = _runtime(self, self.profile, self.now)
        for k, v in _google(connected=False).items():
            setattr(rt.google_api, k, v)
        return rt

    def test_rules_in_tomorrows_plan(self):
        self.profile.add_event('İlaç', '2026-10-17T21:00', repeat='daily')
        self.profile.add_event('Spor', '2026-10-19T07:00', repeat='weekly:0')        # pazartesi
        self.profile.add_event('Kira', '2026-11-01T09:00', repeat='monthly:1')
        reply = say(self.rt(), 'yarın planım ne')
        self.assertIn('21:00 İlaç', reply)
        self.assertNotIn('Spor', reply)
        self.assertNotIn('Kira', reply)

    def test_weekly_and_weekdays_on_matching_day(self):
        self.profile.add_event('Spor', '2026-10-19T07:00', repeat='weekly:0')
        self.profile.add_event('Stand-up', '2026-10-19T09:30', repeat='weekdays')
        days = {d: [e['title'] for e in self.profile.events_on(d)]
                for d in ('2026-10-19', '2026-10-26', '2026-10-24', '2026-10-18')}
        self.assertEqual(days['2026-10-19'], ['Spor', 'Stand-up'])
        self.assertEqual(days['2026-10-26'], ['Spor', 'Stand-up'])
        self.assertEqual(days['2026-10-24'], [])           # cumartesi: ikisi de değil
        self.assertEqual(days['2026-10-18'], [])

    def test_not_before_first_occurrence(self):
        self.profile.add_event('İlaç', '2026-10-20T08:00', repeat='daily')
        self.assertEqual(self.profile.events_on('2026-10-18'), [])
        self.assertEqual([e['when'] for e in self.profile.events_on('2026-10-21')], ['2026-10-21T08:00'])

    def test_conflict_with_recurring_reminder(self):
        self.profile.add_event('İlaç', '2026-10-17T21:00', repeat='daily')
        reply = say(self.rt(), "yarın 21:10'da toplantı hatırlat")
        self.assertIn('İlaç', reply)
        self.assertEqual(len(self.reload().data['events']), 1)          # sormadan eklemedi


class LateTasksTests(ProfileCase):
    now = datetime(2026, 10, 17, 10, 0)

    def test_tomorrow_lateness_is_relative_to_today(self):
        self.profile.data['tasks'] = [
            {'id': 1, 'text': 'Fatura öde', 'done': False, 'when': '2026-10-15'},
            {'id': 2, 'text': 'Raporu bitir', 'done': False, 'when': '2026-10-17T18:00'},
            {'id': 3, 'text': 'Sunum', 'done': False, 'when': '2026-10-18'}]
        rt = _runtime(self, self.profile, self.now)
        for k, v in _google(connected=False).items():
            setattr(rt.google_api, k, v)
        with patch('modules.handoff.brief_line', return_value=None):
            reply = say(rt, 'yarın planım ne')
        self.assertIn('1 gecikmiş (Fatura öde)', reply)
        self.assertIn('yarın 1 (Sunum)', reply)
        self.assertIn('bugün bitmezse yarına kalır 1 (Raporu bitir)', reply)


class PlanAsciiTests(ProfileCase):
    now = datetime(2026, 10, 17, 10, 0)

    def test_ascii_and_typo_variants_reach_plan(self):
        rt = _runtime(self, self.profile, self.now)
        for k, v in _google(connected=False).items():
            setattr(rt.google_api, k, v)
        with patch('modules.handoff.brief_line', return_value=None):
            for text in ('bugunun plani', 'Bugunun Plani ne', 'bugunku plan', 'bugunku planim', 'bugun ne yapmaliyim',
                         'bugun ne yapacagim', 'gunumu planla', 'gunumun plani', 'planimi soyle', 'planimi goster',
                         'bugunun planini soyle', 'bugun plan ne'):
                with self.subTest(text=text):
                    self.assertIn('Bugünün planı', say(rt, text))
            for text in ('yarinin plani', 'yarin planim ne', 'yarinki plan', 'yarinin planini goster'):
                with self.subTest(text=text):
                    self.assertIn('Yarının planı', say(rt, text))

    def test_other_plans_not_caught(self):
        rt = _runtime(self, self.profile, self.now)
        for text in ('proje planim', 'calisma planim', 'yarin plan yapalim', 'bugun ne var'):
            with self.subTest(text=text), patch('modules.router.classify', return_value=None):
                try:
                    reply = rt.handle(text)
                except Exception:
                    reply = ''
                self.assertNotIn('Bugünün planı', reply or '')
                self.assertNotIn('Yarının planı', reply or '')


class ToHeaderTests(unittest.TestCase):
    def run_mine(self, threads):
        with patch.object(google_api, '_service', return_value=FakeGmail(threads)):
            return [x['subject'] for x in google_api.awaiting('mine')]

    def test_to_must_be_exact_address(self):
        threads = {
            'a': [_msg('A <a@x.com>', ME + '.tr', 'Başka adres', 1)],
            'b': [_msg('B <b@x.com>', 'x' + ME, 'Önekli adres', 1)],
            'c': [_msg('C <c@x.com>', f'Ali <ali@y.com>, Ben <{ME.upper()}>', 'Listede', 1)],
            'd': [_msg('D <d@x.com>', f'"Köse, Hamdi" <{ME}>', 'Virgüllü ad', 1)],
        }
        self.assertEqual(sorted(self.run_mine(threads)), ['Listede', 'Virgüllü ad'])


class ScanLimitTests(unittest.TestCase):
    def test_capped_scan_is_told_not_flat_none(self):
        threads = {f't{i}': [_msg(f'R <no-reply@r{i}.com>', ME, 'x', 1)] for i in range(20)}
        with patch.object(google_api, '_ready', return_value=None), \
                patch.object(google_api, '_service', return_value=FakeGmail(threads)):
            text = google_api.awaiting_text('mine')
        self.assertIn('20', text)
        self.assertNotEqual(text, 'Son bir haftada kişilerden gelip cevaplamadığın mail görmedim (Gmail).')

    def test_limit_hit_says_how_many_shown(self):
        threads = {f't{i}': [_msg(f'P{i} <p{i}@x.com>', ME, f'K{i}', 1)] for i in range(12)}
        with patch.object(google_api, '_ready', return_value=None), \
                patch.object(google_api, '_service', return_value=FakeGmail(threads)):
            text = google_api.awaiting_text('mine')
        self.assertIn('İlk 8', text)


class ReplyIntentTests(unittest.TestCase):
    def test_reply_or_send_requests_do_not_list(self):
        for text in ('cevap vermediğim maillere cevap yaz', 'cevaplamadığım maillere cevap gönder',
                     'cevap vermediğim mailleri cevapla'):
            with self.subTest(text=text), patch.object(google_api, 'awaiting_text', return_value='LISTE') as m:
                self.assertNotEqual(google_api.handle(text), 'LISTE')
                m.assert_not_called()

    def test_plain_lists_still_work(self):
        for text in ('cevap vermediğim mailler', 'kime cevap vermedim'):
            with self.subTest(text=text), patch.object(google_api, 'awaiting_text', return_value='LISTE'):
                self.assertEqual(google_api.handle(text), 'LISTE')


if __name__ == '__main__':
    unittest.main()
