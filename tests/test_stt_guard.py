"""Ses tanıma süzgeci, Türkçe dil kodu, paylaşım kapatma ve belirsiz komut sorusu (ağ/mikrofon yok)."""
import asyncio
from contextlib import asynccontextmanager
import importlib
import re
import sys
import types as pytypes
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from google.genai import types

# Windows ses kütüphaneleri (PortAudio) yoksa sahte modülle yer tut; testler yalnız karar mantığını sınar.
for _name in ("edge_tts", "pyttsx3", "sounddevice", "speech_recognition"):
    try:
        importlib.import_module(_name)
    except Exception:   # noqa: BLE001
        _m = pytypes.ModuleType(_name)
        if _name == "speech_recognition":
            _m.Recognizer = Mock
            _m.AudioData = Mock
            _m.UnknownValueError = type("UnknownValueError", (Exception,), {})
            _m.RequestError = type("RequestError", (Exception,), {})
        else:
            _m.__getattr__ = lambda attr: Mock()
        sys.modules[_name] = _m

from modules import engine_context, engine_output, live, live_session_config, llm, stt_guard, voice
from modules.session_state import SessionState


class GuardTests(unittest.TestCase):
    def setUp(self):
        stt_guard._said.clear()
        self.addCleanup(stt_guard._said.clear)
        p = patch.object(stt_guard, 'enabled', return_value=True)
        p.start(); self.addCleanup(p.stop)

    def test_foreign_and_hallucinated_short_phrases_are_rejected(self):
        for text in ('Sí', 'sí.', "C'est bien", "C'est bien.", 'Gracias', 'Thank you for watching!', '감사합니다',
                     'ご視聴ありがとうございました', 'Спасибо', '¿Qué?', 'Très bien', '...', ''):
            self.assertEqual(stt_guard.reject(text), 'foreign', text)

    def test_turkish_speech_passes(self):
        for text in ('Sesi kıs', 'Paylaşımı kapat', 'Chrome aç', 'Hey Jarvis', 'Hâlâ cevap yok', 'YouTube aç',
                     'yarın saat üçte toplantı var', 'Spotify', 'evet', 'tamam'):
            self.assertIsNone(stt_guard.reject(text), text)

    def test_own_recent_speech_is_echo_but_old_or_different_speech_is_not(self):
        stt_guard.note_said('Paylaşımı kapattım. Başka bir şey ister misin?', now=100.0)
        self.assertTrue(stt_guard.echo('Başka bir şey ister misin', now=105.0))
        self.assertTrue(stt_guard.echo('paylaşımı kapattım başka bir şey ister misin', now=105.0))
        self.assertFalse(stt_guard.echo('Başka bir şey ister misin', now=200.0))
        self.assertFalse(stt_guard.echo('Hava durumu nasıl', now=105.0))
        self.assertFalse(stt_guard.echo('kapattım', now=105.0))    # çok kısa: kullanıcı da söyleyebilir

    def test_numeric_answers_and_arithmetic_pass(self):
        # Regresyon: harf içermeyen sayısal cevaplar "yabancı/gürültü" sayılıp atılıyordu.
        for text in ('19', '12 + 7', '12+7', '6 x 7', '6 × 7', '15 - 5', '100 / 4', '%50', '3,5', '-12', '1.250',
                     '12 + 7 = ?', '2026', '19.', 'Yüzde 70', '12 ile 7 topla', "15'ten 5 çıkar", 'kaç eder 8 x 9'):
            self.assertIsNone(stt_guard.reject(text), text)
        stt_guard.note_said('Sonuç 19. Başka bir işlem yapayım mı?', now=stt_guard._clock())
        self.assertIsNone(stt_guard.reject('19'))

    def test_similar_command_with_different_meaning_is_not_echo(self):
        # Regresyon: "Paylaşımı kapattım" yankısı ile gerçek "Paylaşımı kapat" komutu harf benzerliğiyle karışıyordu.
        now = stt_guard._clock()
        stt_guard.note_said('Paylaşımı kapattım.', now=now)
        for text in ('Paylaşımı kapat', 'paylaşımı kapat lütfen', 'Paylaşımı kapatır mısın'):
            self.assertIsNone(stt_guard.reject(text), text)
        stt_guard.note_said('Ekran paylaşımını kapattım, başka bir şey ister misin?', now=now)
        for text in ('Ekran paylaşımını kapat', 'ekran paylaşımını kapat başka bir şey yok', 'Kamerayı da kapat lütfen hemen'):
            self.assertIsNone(stt_guard.reject(text), text)
        self.assertEqual(stt_guard.reject('Ekran paylaşımını kapattım, başka bir şey ister misin?'), 'echo')
        self.assertEqual(stt_guard.reject('başka bir şey ister misin'), 'echo')

    def test_setting_off_disables_filter(self):
        with patch.object(stt_guard, 'enabled', return_value=False):
            self.assertIsNone(stt_guard.reject('Sí'))

    def test_recognize_rejects_foreign_gemini_text_without_fallback_call(self):
        announce = Mock()
        with patch.object(voice, '_engine', return_value='gemini'), patch.object(llm, 'transcribe', return_value='Sí'), \
                patch.object(voice, 'speak', announce), patch.object(voice._rec, 'recognize_google') as google:
            self.assertIsNone(voice.recognize(b'\0\0' * 1600, announce_fail=True))
        google.assert_not_called()
        announce.assert_called_once()
        self.assertIn('tekrar', announce.call_args.args[0])

    def test_recognize_passes_turkish_gemini_text(self):
        with patch.object(voice, '_engine', return_value='gemini'), patch.object(llm, 'transcribe', return_value='Sesi kıs'):
            self.assertEqual(voice.recognize(b'\0\0' * 1600), 'Sesi kıs')

    def test_live_drops_foreign_and_echo_user_transcripts(self):
        obj = live.Live.__new__(live.Live)
        obj.emit = Mock(); obj._in_buf = []; obj._out_buf = []; obj._recent_user = []; obj._convo = []
        obj._suppress_output_turns = 0; obj._tools_running = 0
        obj._out_buf = ['Ekranı paylaşmayı kapattım, başka bir isteğin var mı?']
        obj._flush_transcripts()
        for heard in (["C'est bien."], ['Sí'], ['Ekranı paylaşmayı kapattım, başka bir isteğin var mı']):
            obj._in_buf = list(heard)
            obj._flush_user()
        obj._in_buf = ['Sesi kıs']
        obj._flush_user()
        self.assertEqual([c for c in obj._convo if c[0] == 'user'], [('user', 'Sesi kıs')])
        self.assertEqual(obj._recent_user, ['Sesi kıs'])


class LanguageHintTests(unittest.TestCase):
    def instance(self):
        obj = live.Live.__new__(live.Live)
        obj._stt_hint = False; obj._stt_drop = set(); obj.vocab = lambda: []
        return obj

    services = SimpleNamespace(_cfg=lambda key, default: default)

    def test_turkish_code_and_vocabulary_are_sent_and_safe_mode_keeps_language(self):
        obj = self.instance()
        full = live_session_config.transcription(obj, types, self.services)
        self.assertEqual(full['language_codes'], ['tr-TR']); self.assertIn('Jarvis', full['custom_vocabulary'])
        safe = live_session_config.transcription(obj, types, self.services, minimal=True)
        self.assertEqual(safe, {'language_codes': ['tr-TR']}); self.assertTrue(obj._stt_hint)

    def test_rejection_drops_one_field_per_run_and_never_saves_setting(self):
        obj = self.instance(); obj._stt_hint = True
        with patch('config.save_settings') as save:
            self.assertFalse(live_session_config.stt_rejected(obj, 'api key not valid'))
            self.assertFalse(live_session_config.stt_rejected(obj, 'invalid api key'))
            self.assertTrue(live_session_config.stt_rejected(obj, '1007 invalid argument'))
            self.assertEqual(obj._stt_drop, {'custom_vocabulary'})
            self.assertEqual(live_session_config.transcription(obj, types, self.services), {'language_codes': ['tr-TR']})
            obj._stt_hint = True
            self.assertTrue(live_session_config.stt_rejected(obj, '1007 invalid argument'))
            self.assertEqual(live_session_config.transcription(obj, types, self.services), {})
            self.assertFalse(obj._stt_hint)
            self.assertFalse(live_session_config.stt_rejected(obj, '1007 invalid argument'))
        save.assert_not_called()

    def test_unknown_language_field_drops_language_only(self):
        obj = self.instance(); obj._stt_hint = True
        self.assertTrue(live_session_config.stt_rejected(obj, 'unknown name "language_codes"'))
        self.assertEqual(obj._stt_drop, {'language_codes'})
        self.assertEqual(set(live_session_config.transcription(obj, types, self.services)), {'custom_vocabulary'})

    def test_converse_reconnects_without_rejected_field(self):
        with patch.object(live, '_Player', return_value=Mock()), patch.object(live.threading, 'Thread'):
            obj = live.Live(Mock(), Mock(), Mock())
        self.addCleanup(obj.loop.close)
        obj._save_sent = Mock()
        seen = []
        def config():
            seen.append(set(obj._stt_drop)); obj._stt_hint = True
            return 'config'
        obj._config = config
        @asynccontextmanager
        async def connect(**kwargs):
            if len(seen) == 1:
                raise RuntimeError('1007 Invalid argument: custom_vocabulary')
            yield object()
        async def run(session): obj._closing = True
        obj._run_session = run
        client = SimpleNamespace(aio=SimpleNamespace(live=SimpleNamespace(connect=connect)))
        with patch.object(llm, 'gemini_client', return_value=client), patch.object(live, 'enabled', return_value=True), \
                patch.object(live, 'model_name', return_value='m'), patch.object(live, 'voice_name', return_value='Kore'), \
                patch.object(live, '_cfg', side_effect=lambda key, default: default), patch('config.save_settings') as save:
            asyncio.run(obj._converse())
        self.assertEqual(seen, [set(), {'custom_vocabulary'}])
        save.assert_not_called()


class ShareAndClarifyTests(unittest.TestCase):
    def test_share_stop_phrases_route_to_existing_close(self):
        control = Mock(return_value='kapatma sonucu')
        runtime = SimpleNamespace(re=re, set_share=control, _session=lambda: SessionState())
        for text in ('paylaşımı kapat', 'paylaşımı durdur', 'paylaşımı bitir', 'paylasimi kapat', 'paylaşımı kapatır mısın',
                     'paylaşmayı durdur'):
            control.reset_mock()
            self.assertEqual(engine_context._user_command(runtime, text, text), 'kapatma sonucu', text)
            control.assert_called_once_with(None)

    def test_set_share_reports_real_result(self):
        def runtime(mode):
            state = {'mode': mode}
            vision = SimpleNamespace(mode=lambda: state['mode'], stop=lambda: state.update(mode=None))
            return SimpleNamespace(vision=vision, emit=Mock(), privacy=Mock(), _record_failure=Mock())
        self.assertEqual(engine_output.set_share(runtime('screen'), None), 'Paylaşımı kapattım.')
        self.assertIn('yoktu', engine_output.set_share(runtime(None), None))
        stuck = runtime('camera'); stuck.vision.stop = lambda: None
        self.assertIn('kapatamadım', engine_output.set_share(stuck, None))
        # Durdurma başarısız: arayüze "kapalı" olayı gitmez, gerçek durum (kamera) gider; "kapatıldı" kaydı oluşmaz.
        stuck.emit.assert_called_once_with('share', 'camera')
        stuck.privacy.audit.assert_not_called()
        done = runtime('screen')
        engine_output.set_share(done, None)
        done.emit.assert_called_once_with('share', '')
        done.privacy.audit.assert_called_once_with('paylaşım', 'kapatıldı')
        broken = runtime('camera')
        def fail(): raise RuntimeError('aygıt meşgul')
        broken.vision.stop = fail
        self.assertTrue(engine_output.set_share(broken, None).startswith('Paylaşım kapatılamadı'))

    def test_live_prompt_asks_instead_of_guessing_and_routes_share(self):
        prompt = live.build_prompt('Jarvis', 'Hamdi')
        self.assertIn("'paylaşımı kapat'", prompt)
        self.assertIn('Neyi kapatmamı istiyorsun?', prompt)
        self.assertTrue(live._CLAIM.search('kapatıyorum'))
        self.assertTrue(live._CLAIM.search('durduruyorum'))


if __name__ == '__main__':
    unittest.main()


class EngineClarifyTests(unittest.TestCase):
    """Gerçek komut motoru: nesnesiz işlem modele/tahmine gitmez; sesle tek 'kapat' Jarvis'i kapatmaz."""
    def context(self):
        import test_engine_modular
        return test_engine_modular.ModularEngineTests.context(self)

    def test_bare_verbs_ask_without_model_call(self):
        context = self.context()
        context.route = Mock(side_effect=AssertionError('model çağrılmamalı'))
        for text, word in (('kapat', 'kapatmamı'), ('Kapatır mısın?', 'kapatmamı'), ('aç', 'açmamı'), ('sil', 'silmemi')):
            with context.as_user(context.profile.name):
                answer = context.handle(text)
            self.assertEqual(answer, f'Neyi {word} istiyorsun?', text)
            self.assertEqual(context._session().pending_request['question'], answer)

    def test_voice_bare_close_reaches_handler_but_typed_close_still_quits(self):
        import contextlib
        import time
        context = self.context()
        owner = context.profile.name
        context.list_users = lambda: [owner]
        context.requests_state = SimpleNamespace(is_cancelled=lambda *a: False, activate=lambda *a: contextlib.nullcontext())
        context.handle = Mock(return_value='Neyi kapatmamı istiyorsun?')
        context.emit = Mock(); context._finalize = lambda text: text
        context._start_hang_watch = Mock(); context.profile.log_agent = Mock()
        context.threading = SimpleNamespace(Thread=Mock(), Timer=Mock())
        context.time = SimpleNamespace(time=time.time, sleep=lambda seconds: None)
        context.events.put(('command', 'Kapat.', 'ses', owner, 'one'))
        context.events.put(('command', 'kapat', 'yazı', owner, 'two'))
        voice = SimpleNamespace(manual_local_stt=False, listening_enabled=False, speak_enabled=False, live_on=False, state={}, speak=Mock())
        with patch('modules.engine_voice.VoiceSession', return_value=voice), patch('instance.take_over', return_value=False), \
                patch('updater.pop_notice', return_value=None), patch('modules.perf.start'), patch('release_guard.ready'):
            context.main(ui=Mock())
        context.handle.assert_called_once_with('Kapat.')
        self.assertTrue(context.stop_event.is_set())
