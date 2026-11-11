"""Sabah özeti aynı kullanıcıya bir kez gider; Google izin uyarıları her hizmetin kendi düğmesini gösterir.

Regresyonlar (14 Ekim 2026):
- Arka plan iletisi (sabah özeti, hatırlatma) önce sohbete yazılıyor, sonra seslendirilirken ikinci kez
  sohbet balonu oluyordu. O dönem canlı (Gemini Live) sesi transkripti kendisi basıyordu; tek ses çıkış
  sahibine göçte bu koruma `shown`/`background` ile sahibine notice olarak sıraya alma sözleşmesine taşındı.
- Özet kontrolü ile `last_brief` kaydı arasında yavaş model çağrısı vardı; aynı anda iki çalışma iki özet üretebilirdi.
  Profil süreç içinde önbelleklidir, yeniden başlatma örtüşmesinde önceki sürecin yazdığı kaydı görmüyordu.
- Gmail/Takvim izni düşünce uyarı "Görevler iznini ver" düğmesini söylüyordu: kullanıcıya özel izin yolu eski
  ortak `TOKEN` yoluyla hiç eşit olmadığı için her izin Görevler sayıldı.
- "yarın bitiyor", "bir hafta daha sorun çıkmaz" gibi kesin süre sözleri gerçek token bitişi bilinmeden veriliyordu.
"""
import json
import queue
import re
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

sys.modules.setdefault('sounddevice', MagicMock())

ROOT = Path(__file__).resolve().parents[1]


class MorningBriefOnceTests(unittest.TestCase):
    def runtime(self, owner):
        now = datetime(2026, 10, 14, 9, 0)
        return SimpleNamespace(profile=owner, pc_profile=Mock(return_value=owner), datetime=SimpleNamespace(now=lambda: now),
                               stop_event=SimpleNamespace(wait=Mock(return_value=False), is_set=Mock(return_value=False)),
                               flags={'sleep': False}, _llm=Mock(), _emit_for=Mock(), events=queue.Queue())

    def owner(self, path=None):
        o = SimpleNamespace(name='Hamdi', slug='hamdi', data={'prefs': {}}, path=path)
        o.set_pref = lambda k, v: o.data['prefs'].__setitem__(k, v)
        return o

    def test_concurrent_runs_send_one_brief(self):
        from modules import main_planner
        owner = self.owner()
        runtime = self.runtime(owner)
        started, release = threading.Event(), threading.Event()

        def slow(_owned):
            started.set()
            release.wait(5)
            return 'Günaydın'
        with patch.object(main_planner, '_daily_briefing', side_effect=slow):
            first = threading.Thread(target=main_planner._morning_brief, args=(runtime,))
            first.start()
            self.assertTrue(started.wait(5))
            main_planner._morning_brief(runtime)     # ilk özet hazırlanırken ikinci tetikleme
            release.set()
            first.join(5)
        runtime._emit_for.assert_called_once_with(owner, 'assistant', 'Günaydın')
        self.assertEqual(runtime.events.qsize(), 1)
        self.assertEqual(owner.data['prefs']['last_brief'], '2026-10-14')
        main_planner._morning_brief(runtime)         # aynı gün yeniden
        runtime._emit_for.assert_called_once()

    def test_brief_written_by_previous_process_is_seen_from_disk(self):
        from modules import main_planner
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'hamdi.json'
            path.write_text(json.dumps({'prefs': {'last_brief': '2026-10-14'}}), encoding='utf-8')
            owner = self.owner(path)                 # bu süreçteki önbellek eski: last_brief yok
            runtime = self.runtime(owner)
            with patch.object(main_planner, '_daily_briefing') as briefing:
                main_planner._morning_brief(runtime)
            briefing.assert_not_called()
            runtime._emit_for.assert_not_called()
            self.assertEqual(owner.data['prefs']['last_brief'], '2026-10-14')   # sonraki kayıt silmesin

    def test_brief_written_during_network_call_is_not_repeated(self):
        from modules import main_planner
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'hamdi.json'
            path.write_text(json.dumps({'prefs': {}}), encoding='utf-8')
            owner = self.owner(path)
            runtime = self.runtime(owner)

            def other_process_sent(_owned):
                path.write_text(json.dumps({'prefs': {'last_brief': '2026-10-14'}}), encoding='utf-8')
                return 'Günaydın'
            with patch.object(main_planner, '_daily_briefing', side_effect=other_process_sent):
                main_planner._morning_brief(runtime)
            runtime._emit_for.assert_not_called()
            self.assertTrue(runtime.events.empty())

    def test_failed_brief_releases_claim(self):
        from modules import main_planner
        owner = self.owner()
        runtime = self.runtime(owner)
        with patch.object(main_planner, '_daily_briefing', side_effect=RuntimeError('ağ yok')):
            main_planner._morning_brief(runtime)
        self.assertFalse(main_planner._BRIEF_RUNNING)
        with patch.object(main_planner, '_daily_briefing', return_value='Günaydın'):
            main_planner._morning_brief(runtime)
        runtime._emit_for.assert_called_once()


class BackgroundSpeechNotDuplicatedTests(unittest.TestCase):
    def session(self, source=''):
        from modules.engine_voice import VoiceSession
        lane = Mock()
        lane.say.return_value = Mock(is_set=Mock(return_value=True))
        runtime = SimpleNamespace(
            flags={'speak': True, 'mic': True}, _cur_source=source, _cur_rid='rid-1',
            profile=SimpleNamespace(slug='hamdi', data={'prefs': {'voice': 'tr_erkek'}}),
            emit=Mock(), threading=SimpleNamespace(Thread=Mock()))
        session = VoiceSession.__new__(VoiceSession)
        session.runtime, session.speak_enabled = runtime, True
        session.voice_lane, session.voice_core_fault = lane, None
        return session, lane

    def test_already_shown_background_text_is_enqueued_as_notice_not_a_bubble(self):
        session, lane = self.session(source='ses')
        session.speak('Günaydın Hamdi', shown=True)
        # The chat already carries this text; the single owner must enqueue it as a
        # background notice, never re-present it as a fresh foreground reply bubble.
        self.assertTrue(lane.say.call_args.kwargs['background'])
        self.assertEqual(lane.say.call_args.kwargs['kind'], 'notice')

    def test_reply_still_foreground_when_not_written(self):
        session, lane = self.session(source='ses')
        session.speak('Merhaba')
        self.assertFalse(lane.say.call_args.kwargs['background'])
        self.assertEqual(lane.say.call_args.kwargs['kind'], 'reply')

    def test_owner_tagged_say_events_are_marked_shown(self):
        src = (ROOT / 'modules' / 'engine_loop.py').read_text(encoding='utf-8')
        self.assertIn('voice_session.speak(event[1], slow=(kind == "say_slow"), shown=len(event) > 2)', src)
        for path in ('modules/main_planner.py', 'modules/engine_background.py', 'modules/engine_tools.py'):
            text = (ROOT / path).read_text(encoding='utf-8')
            for line in re.findall(r"events\.put\(\(['\"]say['\"],[^\n]*", text):
                self.assertRegex(line, r"\.slug\)\)", f'{path}: arka plan say olayı sahibini taşımalı')

    def test_shutdown_stops_background_before_releasing_instance_lock(self):
        src = (ROOT / 'web.py').read_text(encoding='utf-8')
        body = src[src.index('def _shutdown('):src.index('def _capabilities(')]
        self.assertLess(body.index('engine.stop_event.set()'), body.index('instance.release()'))


class GooglePermissionWarningTests(unittest.TestCase):
    def run_health(self, expired=(), age_days=None, production=False):
        from modules import google_api
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'google_users' / 'hamdi'
            folder.mkdir(parents=True)
            for legacy in (google_api.TOKEN, google_api.TASKS_TOKEN):
                (folder / legacy.name).write_text('{}', encoding='utf-8')
            settings = {'google_oauth_production': production}
            if age_days is not None:
                for name in ('google_token', 'google_tasks_token'):
                    settings[f'granted_hamdi_{name}'] = time.time() - age_days * 86400

            def creds(token, scopes, interactive=True):
                if token.stem in expired:
                    raise Exception('invalid_grant: Token has been expired or revoked.')
                return Mock(valid=True)
            with patch.object(google_api, 'token_path', side_effect=lambda t=None: folder / (t or google_api.TOKEN).name), \
                    patch.object(google_api, '_creds', side_effect=creds), \
                    patch('config.load_settings', return_value=settings), patch('config.save_settings'):
                return google_api.health()

    def test_gmail_expiry_points_to_gmail_connect_button(self):
        msgs = self.run_health(expired={'google_token'})
        self.assertEqual(len(msgs), 1)
        self.assertIn('Gmail ve Takvim', msgs[0])
        self.assertIn('“Bağlan”', msgs[0])
        self.assertNotIn('Görevler iznini ver', msgs[0])

    def test_tasks_expiry_points_to_tasks_button(self):
        msgs = self.run_health(expired={'google_tasks_token'})
        self.assertEqual(len(msgs), 1)
        self.assertIn('Görevler', msgs[0])
        self.assertIn('“Görevler iznini ver”', msgs[0])

    def test_age_warning_makes_no_exact_duration_promise(self):
        msgs = self.run_health(age_days=6.5)
        self.assertEqual(len(msgs), 2)
        self.assertIn('“Bağlan”', msgs[0])
        self.assertIn('“Görevler iznini ver”', msgs[1])
        for m in msgs:
            low = m.casefold()
            for promise in ('yarın', 'bir hafta', '7 gün', 'bitiyor', 'sorun çıkmaz'):
                self.assertNotIn(promise, low)
            self.assertIn('doğrulanamıyor', low)

    def test_production_and_fresh_grants_stay_quiet(self):
        self.assertEqual(self.run_health(age_days=10, production=True), [])
        self.assertEqual(self.run_health(age_days=2), [])

    def test_grant_time_is_per_user(self):
        from modules import google_api
        self.assertEqual(google_api._grant_key(Path('/x/google_users/hamdi/google_token.json')), 'granted_hamdi_google_token')
        self.assertNotEqual(google_api._grant_key(Path('/x/google_users/can/google_token.json')),
                            google_api._grant_key(Path('/x/google_users/hamdi/google_token.json')))

    def test_user_facing_texts_do_not_promise_exact_expiry(self):
        for path in ('modules/google_api.py', 'modules/diagnose.py', 'modules/handoff.py', 'web_integrations.py', 'webui/nx.js'):
            text = (ROOT / path).read_text(encoding='utf-8')
            self.assertNotRegex(text, r'7 gün(de|lük| sonra)|yarın bitiyor|bir hafta daha|6\. günde', path)
            self.assertNotIn('Bağlan / dene', text, path)

    def test_tasks_permission_button_is_always_available(self):
        js = (ROOT / 'webui' / 'nx.js').read_text(encoding='utf-8')
        self.assertNotIn("(ho.ready?'':pad18(`<button class=\"btn sm\" data-act=\"hoconn\"", js)
        self.assertIn('data-act="hoconn"', js)


if __name__ == '__main__':
    unittest.main()
