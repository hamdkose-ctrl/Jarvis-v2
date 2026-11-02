"""Mail/takvim alanı düzeltmeleri (17 Ekim 2026).

- Sabah özeti Gmail/Takvim iznini eski ortak TOKEN dosyasında arıyordu; bağlanınca o dosya kullanıcı klasörüne
  taşınıp silindiği için özet bağlıyken bile maili ve takvimi atlıyordu.
- "her gün 9'da ilaç hatırlat" yarına tek seferlik "her gün saat ilaç" kaydı oluyordu; tekrar desteği yoktu.
- ASCII yazım ("yarin saat 9da") anlaşılmıyordu; aynı saate ikinci kayıt uyarısız ekleniyordu.
- "maillerime göz at", "son mailleri göster" mail koduna gitmiyor, model sınıflandırmasına düşüyordu.

Profil gerçek JSON dosyasına yazılır ve yeniden okunur; Google servisi taklittir, model çağrılmaz.
"""
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import test_privacy_voice_and_pending  # noqa: F401  (ses/donanım taklitleri, motor testleriyle aynı)
if 'pyautogui' not in sys.modules:
    _keyboard = ModuleType('pyautogui')
    _keyboard.__getattr__ = lambda name: Mock()
    sys.modules['pyautogui'] = _keyboard

from modules import agents, engine_runtime, google_api, main_planner, personalization
from modules import when as whenmod


def _release_logs(folder):
    """EngineContext kök günlükçüye <geçici dizin>/jarvis.log tutucusu ekler; Windows açık dosyayı silemez."""
    import logging
    root = logging.getLogger()
    for h in root.handlers[:]:
        if str(getattr(h, 'baseFilename', '')).startswith(str(Path(folder))):
            root.removeHandler(h)
            h.close()


def _runtime(case, profile, now, busy=()):
    """Gerçek motor bağlamı (EngineContext): komutlar handle() ile gerçek sırasından geçer."""
    temp = tempfile.TemporaryDirectory()
    case.addCleanup(temp.cleanup)
    with patch.object(engine_runtime, 'DATA_DIR', Path(temp.name)):
        rt = engine_runtime.EngineContext()
    case.addCleanup(rt._prefetch_pool.shutdown, wait=False, cancel_futures=True)
    case.addCleanup(_release_logs, temp.name)           # temp.cleanup'tan önce çalışır (LIFO)
    rt.profile = profile
    rt.datetime = SimpleNamespace(now=lambda: now, strptime=datetime.strptime)
    rt.google_api = SimpleNamespace(busy_between=lambda a, b: list(busy), _ready=lambda: 'yok',
                                    handle=lambda t: None, _MAIL_CHECK=google_api._MAIL_CHECK)
    rt._llm = SimpleNamespace(set_user_context=lambda *a: None)
    return rt


def say(rt, text):
    # PR10c: `modules.router` sınıfleyicisi fiziksel olarak kaldırıldı; bunu artık tabandaki
    # `router.classify` bekçisi değil, caller-zero muhafızları kanıtlıyor
    # (tests/test_brain_b3b.py, tests/test_brain_pr10a_live_router_cleanup.py). Domain'in
    # kendi model çağrısı (örn. Outlook taslağı) meşrudur; beklenmeyen model kullanımı
    # isteyen test `say_deterministic` kullanır.
    return rt.handle(text)


def say_deterministic(rt, text):
    """Komut hiçbir model kapısına düşmeden cevaplanmalı: 'ask'/'chat' çağrılırsa test patlar."""
    with patch.object(rt, 'ask', side_effect=AssertionError('deterministik yol modele düşmemeli')), \
         patch.object(rt, 'chat', side_effect=AssertionError('deterministik yol modele düşmemeli')):
        return rt.handle(text)


class ProfileCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patch = patch.object(personalization, 'USERS_DIR', self.root)
        self.patch.start()
        self.profile = personalization.Profile('Deneme')

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def reload(self):
        return personalization.Profile('Deneme')


class BriefUsesPerUserTokenTests(unittest.TestCase):
    def test_brief_reads_gmail_and_calendar_with_per_user_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / 'google_token.json'          # taşınmış: eski ortak dosya yok
            mine = Path(tmp) / 'google_users' / 'hamdi' / 'google_token.json'
            mine.parent.mkdir(parents=True)
            mine.write_text('{}')
            rt = SimpleNamespace(datetime=datetime, timedelta=timedelta, _DAYS=['Pzt'] * 7, google_api=google_api,
                                 weather=SimpleNamespace(report=lambda c: None),
                                 profile=SimpleNamespace(name='Hamdi', data={'prefs': {}, 'tasks': [], 'goals': []},
                                                         events_on=lambda d: []))
            with patch.object(google_api, 'TOKEN', legacy), patch.object(google_api, 'token_path', lambda t=None: mine), \
                    patch.object(google_api, 'agenda', return_value='Bugün Google Takvim: 10:00 Toplantı'), \
                    patch.object(google_api, 'unread_mail', return_value='2 okunmamış e-postan var'), \
                    patch('modules.handoff.brief_line', return_value=None), \
                    patch('modules.outlook.installed', return_value=False):
                facts = main_planner._brief_facts(rt)
                card = agents.state('google', SimpleNamespace(data={}))
        self.assertIn('Gmail: 2 okunmamış e-postan var', facts)
        self.assertIn('Google Takvim: Bugün Google Takvim: 10:00 Toplantı', facts)
        self.assertEqual(card, ('Bağlı', 'good'))

    def test_no_user_selected_means_not_connected(self):
        with patch.object(google_api, 'token_path', side_effect=PermissionError('kullanıcı yok')):
            self.assertFalse(google_api.connected())


class AsciiAndRepeatParsingTests(unittest.TestCase):
    now = datetime(2026, 10, 17, 10, 0)        # cumartesi

    def test_ascii_dates_and_hours(self):
        cases = {'yarin saat 9da toplanti': ('2026-10-18T09:00', 'toplanti'),
                 'bugun 14te dis': ('2026-10-17T14:00', 'dis'),
                 'carsamba aksam 8de yemek': ('2026-10-21T20:00', 'yemek'),
                 "yarın saat 9'da ilaç": ('2026-10-18T09:00', 'ilaç'),     # "saat" başlıkta kalmıyor
                 'yarın 14:00 dişçi': ('2026-10-18T14:00', 'dişçi')}
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(whenmod.parse_when(text, self.now), want)

    def test_repeat_rules(self):
        cases = {"her gün saat 9'da ilaç": 'daily', 'her gun 9da ilac': 'daily', 'her sabah 8de su': 'daily',
                 "her pazartesi 10'da toplantı": 'weekly:0', "her hafta salı 15'te spor": 'weekly:1',
                 "pazartesileri 9'da rapor": 'weekly:0', "hafta içi her gün 8'de yürüyüş": 'weekdays',
                 "her ayın 1'inde kira": 'monthly:1', 'her 2 saatte bir su iç': 'unknown', 'her hafta çöp': 'unknown',
                 'yarın 10da dişçi': None, 'her şey yolunda mı': None}
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(whenmod.parse_repeat(text)[0], want)

    def test_next_occurrence(self):
        self.assertEqual(whenmod.next_occurrence('daily', self.now, 9, 0), datetime(2026, 10, 18, 9, 0))
        self.assertEqual(whenmod.next_occurrence('weekdays', self.now, 8, 0), datetime(2026, 10, 19, 8, 0))
        self.assertEqual(whenmod.next_occurrence('weekly:2', self.now, 8, 0), datetime(2026, 10, 21, 8, 0))
        self.assertEqual(whenmod.next_occurrence('monthly:31', datetime(2026, 11, 5), 9, 0),
                         datetime(2026, 11, 30, 9, 0))    # 31'i olmayan ay: son gün


class ReminderCommandTests(ProfileCase):
    now = datetime(2026, 10, 17, 10, 0)

    def test_daily_reminder_saved_with_rule_and_clean_title(self):
        reply = say(_runtime(self, self.profile, self.now), "Her gün saat 9'da ilaç almayı hatırlat")
        self.assertIn('her gün 09:00', reply)
        ev = self.reload().data['events'][0]
        self.assertEqual((ev['when'], ev['repeat']), ('2026-10-18T09:00', 'daily'))
        self.assertNotIn('her', ev['title'])
        self.assertNotIn('saat', ev['title'])

    def test_ascii_reminder(self):
        reply = say(_runtime(self, self.profile, self.now), 'yarin saat 9da toplanti hatirlat')
        self.assertIn('Takvime ekledim', reply)
        self.assertEqual(self.reload().data['events'][0]['when'], '2026-10-18T09:00')

    def test_unknown_repeat_is_asked_not_saved(self):
        reply = say(_runtime(self, self.profile, self.now), 'her 2 saatte bir su içmeyi hatırlat')
        self.assertIn('anlayamadım', reply)
        self.assertEqual(self.reload().data['events'], [])

    def test_conflict_asks_then_adds_on_yes(self):
        self.profile.add_event('Dişçi', '2026-10-18T09:00')
        rt = _runtime(self, self.profile, self.now)
        reply = say(rt, "yarın 9'da toplantı hatırlat")
        self.assertIn('Dişçi', reply)
        self.assertEqual(len(self.reload().data['events']), 1)      # sormadan eklemedi
        self.assertIn('Takvime ekledim', say(rt, 'evet'))
        self.assertEqual(len(self.reload().data['events']), 2)

    def test_conflict_no_cancels(self):
        self.profile.add_event('Dişçi', '2026-10-18T09:15')
        rt = _runtime(self, self.profile, self.now)
        say(rt, "yarın 9'da toplantı hatırlat")
        self.assertEqual(say(rt, 'hayır'), 'Tamam, eklemedim.')
        self.assertEqual(len(self.reload().data['events']), 1)

    def test_google_meeting_conflict_and_other_command_drops_question(self):
        busy = [(datetime(2026, 10, 18, 8, 30), datetime(2026, 10, 18, 9, 30), 'Proje toplantısı')]
        rt = _runtime(self, self.profile, self.now, busy)
        self.assertIn('Proje toplantısı (Google Takvim)', say(rt, "yarın 9'da dişçi hatırlat"))
        self.assertIn('Not defterin boş', say(rt, 'notlarım'))      # başka komut: soru düşer, kayıt açılmaz
        self.assertIsNone(rt._session().pending_event_title)
        self.assertEqual(self.reload().data['events'], [])

    def test_no_conflict_for_far_events(self):
        self.profile.add_event('Dişçi', '2026-10-18T11:00')
        self.assertIn('Takvime ekledim', say(_runtime(self, self.profile, self.now), "yarın 9'da toplantı hatırlat"))


class RepeatingDueTests(ProfileCase):
    def test_fires_and_moves_to_next_day(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
        due = self.profile.due_events(datetime(2026, 10, 18, 9, 0, 5))
        self.assertEqual([e['title'] for e in due], ['İlaç'])
        ev = self.reload().data['events'][0]
        self.assertEqual((ev['when'], ev['notified']), ('2026-10-19T09:00', False))
        self.assertEqual(self.profile.due_events(datetime(2026, 10, 18, 9, 0, 10)), [])   # aynı gün ikinci kez yok

    def test_missed_while_closed_is_not_read_but_moves_forward(self):
        self.profile.add_event('Rapor', '2026-10-12T09:00', repeat='weekly:0')   # pazartesi
        self.assertEqual(self.profile.due_events(datetime(2026, 10, 17, 10, 0)), [])
        self.assertEqual(self.reload().data['events'][0]['when'], '2026-10-19T09:00')

    def test_save_failure_restores_time(self):
        self.profile.add_event('İlaç', '2026-10-18T09:00', repeat='daily')
        with patch.object(self.profile, 'save', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                self.profile.due_events(datetime(2026, 10, 18, 9, 1))
        self.assertEqual(self.profile.data['events'][0]['when'], '2026-10-18T09:00')

    def test_one_off_events_unchanged(self):
        self.profile.add_event('Dişçi', '2026-10-18T09:00')
        self.assertEqual(len(self.profile.due_events(datetime(2026, 10, 18, 9, 1))), 1)
        self.assertTrue(self.reload().data['events'][0]['notified'])


class MailPhrasingTests(unittest.TestCase):
    def test_mail_check_variants(self):
        yes = ['maillerime göz at', 'son mailleri göster', 'mailleri listele', 'maillerimi kontrol eder misin',
               'yeni mail var mi', 'gelen kutuma bak', 'okunmamış e-postalar']
        no = ['mail taslağını göster', 'ilk mailin eklerini göster', 'ilk mailin ilk ekini oku', "mail at ahmet'e",
              'ahmete mail gönder']
        with patch.object(google_api, 'unread_mail', return_value='LISTE'):
            for text in yes:
                with self.subTest(text=text):
                    self.assertEqual(google_api.handle(text), 'LISTE')
            for text in no:
                with self.subTest(text=text):
                    self.assertIsNone(google_api.handle(text))


class GoogleBusyTests(unittest.TestCase):
    def test_busy_between_skips_all_day_and_handles_errors(self):
        items = [{'start': {'date': '2026-10-18'}, 'end': {'date': '2026-10-19'}, 'summary': 'Tatil'},
                 {'start': {'dateTime': '2026-10-18T08:30:00+03:00'}, 'end': {'dateTime': '2026-10-18T09:30:00+03:00'},
                  'summary': 'Toplantı'}]
        svc = SimpleNamespace(events=lambda: SimpleNamespace(
            list=lambda **k: SimpleNamespace(execute=lambda: {'items': items})))
        from datetime import timezone
        start = datetime(2026, 10, 18, 9, 0, tzinfo=timezone(timedelta(hours=3)))
        with patch.object(google_api, 'connected', return_value=True), patch.object(google_api, '_ready', return_value=None), \
                patch.object(google_api, '_service', return_value=svc):
            got = google_api.busy_between(start, start + timedelta(minutes=30))
        self.assertEqual([x[2] for x in got], ['Toplantı'])
        with patch.object(google_api, 'connected', return_value=True), patch.object(google_api, '_ready', return_value=None), \
                patch.object(google_api, '_service', side_effect=OSError('ağ yok')):
            self.assertEqual(google_api.busy_between(start, start + timedelta(minutes=30)), [])
        with patch.object(google_api, 'connected', return_value=False):
            self.assertEqual(google_api.busy_between(start, start + timedelta(minutes=30)), [])


if __name__ == '__main__':
    unittest.main()
