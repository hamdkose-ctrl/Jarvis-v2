"""Ses tanıma süzgeci, paylaşım kapatma ve belirsiz komut sorusu (ağ/mikrofon yok)."""
from modules import core_brain_adapter
import importlib
import re
import sys
import types as pytypes
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

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

from modules import engine_context, engine_output, llm, stt_guard, voice
from modules.session_state import SessionState
from modules.brain_contracts import Confidence, ConversationRelation, TemporalNeed
from modules.brain_model_understanding import UnderstandingProposal


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
        # STT uyarısı tek ses sahibinden (_say_feedback → voice_runtime) çıkar; eski voice.speak yolu değil.
        announce = Mock()
        with patch.object(voice, '_engine', return_value='gemini'), patch.object(llm, 'transcribe', return_value='Sí'), \
                patch.object(voice, '_say_feedback', announce), patch.object(voice._rec, 'recognize_google') as google:
            self.assertIsNone(voice.recognize(b'\0\0' * 1600, announce_fail=True))
        google.assert_not_called()
        announce.assert_called_once()
        self.assertIn('tekrar', announce.call_args.args[0])

    def test_recognize_passes_turkish_gemini_text(self):
        with patch.object(voice, '_engine', return_value='gemini'), patch.object(llm, 'transcribe', return_value='Sesi kıs'):
            self.assertEqual(voice.recognize(b'\0\0' * 1600), 'Sesi kıs')


class ShareAndClarifyTests(unittest.TestCase):
    def test_share_stop_uses_typed_core_and_one_existing_executor(self):
        # The removed _user_controls() parser is not an execution interface.
        # These phrasings are evaluated by the semantic model in production;
        # this test verifies the one permitted Core/effect contract.
        from modules import brain_core_map, engine_intents
        plan = brain_core_map.core_plan("device.share", {"action": "stop"})
        self.assertEqual(plan, ("share_control", {"action": "stop"}))
        control = Mock(return_value="kapatma sonucu")
        runtime = SimpleNamespace(set_share=control)
        for text in ('paylaşımı kapat', 'paylaşımı durdur', 'paylaşımı bitir',
                     'paylasimi kapat', 'paylaşımı kapatır mısın',
                     'paylaşmayı durdur'):
            with self.subTest(text=text):
                control.reset_mock()
                result = engine_intents.dispatch(runtime, plan[0], plan[1], text, text.casefold())
                self.assertEqual(result, "kapatma sonucu")
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


if __name__ == '__main__':
    unittest.main()


class EngineClarifyTests(unittest.TestCase):
    """Gerçek komut motoru: nesnesiz işlem modele/tahmine gitmez; bare close Jarvis'i doğrudan kapatmaz."""
    def context(self):
        import test_engine_modular
        return test_engine_modular.ModularEngineTests.context(self)

    def test_bare_verbs_ask_without_model_call(self):
        # PR3A: soru engine_commands ham dalından değil üretim zincirinden çıkar.
        # prepare → handoff clarify üretir; sorunun cevabı canonical pending_action'a yazılır.
        import uuid
        from modules import brain_entry
        context = self.context()
        context.route = Mock(side_effect=AssertionError('model çağrılmamalı'))
        owner = context.profile.slug
        for text, word in (('kapat', 'kapatmamı'), ('Kapatır mısın?', 'kapatmamı'), ('aç', 'açmamı')):
            rid = 'clarify-' + uuid.uuid4().hex[:8]
            context.requests_state.register(owner, rid)
            with context.as_user(context.profile.name), context.requests_state.activate(owner, rid):
                entry = brain_entry.prepare(context, owner=owner, request_id=rid, text=text, source='yazı')
                answer, _feedback, _job = core_brain_adapter.handoff(context, entry, context.handle, text)
            self.assertEqual(entry.understanding.ambiguities, ('APP_TARGET_MISSING',), text)
            self.assertEqual(answer, f'Neyi {word} istiyorsun?', text)
            self.assertEqual(context._session().pending_action['question'], answer)
        context.route.assert_not_called()

    def test_bare_verbs_without_bounded_owner_fail_closed_without_model_call(self):
        context = self.context()
        context.route = Mock(side_effect=AssertionError('model çağrılmamalı'))
        for text in ('sil', 'gönder', 'başlat'):
            with context.as_user(context.profile.name):
                answer = context.handle(text)
            self.assertEqual(answer, 'Bu cümle Brain turunda yorumlanmadı; işlem başlatılmadı.', text)
            self.assertEqual(context._session().pending_action['question'], answer)
            self.assertNotIn('Neyi', answer, text)

    def test_voice_and_typed_bare_close_are_clarified_without_handler_or_stop(self):
        import contextlib
        import time
        from modules.brain_contracts import ActiveContext
        from modules.brain_gates import deterministic_fast_gate

        context = self.context()
        owner = context.profile.name
        canonical_owner = context.profile.slug
        context.list_users = lambda: [owner]
        context.route = Mock(side_effect=AssertionError('model çağrılmamalı'))
        context.requests_state = SimpleNamespace(is_cancelled=lambda *a: False, activate=lambda *a: contextlib.nullcontext())

        for text, source, rid in (('Kapat.', 'ses', 'voice-probe'), ('kapat', 'yazı', 'typed-probe')):
            gate = deterministic_fast_gate(
                owner=canonical_owner,
                request_id=rid,
                text=text,
                active_context=ActiveContext(owner=canonical_owner, request_id=rid),
                sleeping=False,
                source=source,
            )
            self.assertFalse(gate.matched, (text, source))
            self.assertNotEqual(gate.protocol, 'fast.engine.close')

        turns = []
        answered = []
        test_terminated = {'value': False}

        def record(kind, *args):
            # Üretim döngüsünün gerçek sinyali: cevabın 'assistant' olarak yayımlanması.
            # Legacy handler'a kadar gelen bir tur bu sayaca hiç ulaşmaz.
            if kind == 'user':
                turns.append((args[0], context._cur_source, context.stop_event.is_set()))
            elif kind == 'assistant':
                answered.append(args[0])
                if len(answered) == 2:
                    test_terminated['value'] = True
                    context.stop_event.set()

        context.handle = Mock(side_effect=AssertionError('legacy ham handler çağrılmamalı'))
        context.emit = Mock(side_effect=record); context._finalize = lambda text: text
        context._start_hang_watch = Mock(); context.profile.log_agent = Mock()
        context.threading = SimpleNamespace(Thread=Mock(), Timer=Mock())
        context.time = SimpleNamespace(time=time.time, sleep=lambda seconds: None)
        context.events.put(('command', 'Kapat.', 'ses', owner, 'one'))
        context.events.put(('command', 'kapat', 'yazı', owner, 'two'))
        voice = SimpleNamespace(manual_local_stt=False, listening_enabled=False, speak_enabled=False, state={}, speak=Mock())
        with patch('modules.engine_voice.VoiceSession', return_value=voice), patch('instance.take_over', return_value=False), \
                patch('updater.pop_notice', return_value=None), patch('modules.perf.start'), patch('release_guard.ready'), \
                patch('modules.brain_model_understanding.propose', return_value=UnderstandingProposal(
                        operation='clarify', conversation_relation=ConversationRelation.NEW_REQUEST,
                        temporal_need=TemporalNeed.STATIC,
                        confidence=Confidence.HIGH,
                        clarification_required=True, clarification_question='Neyi kapatmamı istiyorsun?',
                        clarification_reason_code='APP_TARGET_MISSING')):
            context.main(ui=Mock())

        self.assertEqual(
            turns,
            [('Kapat.', 'ses', False), ('kapat', 'yazı', False)],
        )
        self.assertEqual(answered, ['Neyi kapatmamı istiyorsun?', 'Neyi kapatmamı istiyorsun?'])
        context.handle.assert_not_called()
        context.route.assert_not_called()
        self.assertTrue(test_terminated['value'])
        self.assertTrue(context.stop_event.is_set())
