"""PR7 Closeout-B2: weather via Core, open pending_level superseded by an explicit level request, end-to-end."""
from modules import core_brain_adapter
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import test_privacy_voice_and_pending
if 'pyautogui' not in sys.modules:
    _keyboard = ModuleType('pyautogui')
    _keyboard.__getattr__ = lambda name: Mock()
    sys.modules['pyautogui'] = _keyboard

from modules import brain_core_map, brain_entry, engine_intents, session_state
from modules.brain_contracts import ActiveContext, ContextReference, ConversationRelation, RequestKind
from modules.brain_understanding import understand

OWNER = "hamdi"
RID = "req-b2-1"


def understood(text, refs=(), pending=()):
    active = ActiveContext(owner=OWNER, request_id=RID, recent_references=tuple(refs), pending_references=tuple(pending))
    return understand(owner=OWNER, request_id=RID, text=text, active_context=active, candidates=(), references=())


class WeatherUnderstandingTests(unittest.TestCase):
    def test_location_is_extracted_like_the_legacy_city_parser(self):
        for text, location in [("ankara'da hava nasıl", "ankara"), ("izmir hava nasıl", "izmir"),
                               ("istanbul'da hava nasıl olacak", "istanbul")]:
            result = understood(text)
            self.assertIn(result.capability_hint, {"weather.read", "weather.read.current"}, text)
            self.assertEqual(result.arguments.get("location"), location, text)

    def test_capitalized_turkish_cities_keep_their_first_letter(self):
        for text, location in [("İzmir'de hava nasıl", "izmir"), ("İstanbul'da hava nasıl", "istanbul"),
                               ("Isparta'da hava nasıl", "ısparta"), ("ANKARA'DA HAVA NASIL", "ankara")]:
            self.assertEqual(understood(text).arguments.get("location"), location, text)

    def test_filler_words_and_no_city_give_no_location(self):
        for text in ("bugün hava nasıl", "hava nasıl", "yarın hava nasıl", "şu anda hava nasıl"):
            result = understood(text)
            self.assertIn(result.capability_hint, {"weather.read", "weather.read.current"}, text)
            self.assertNotIn("location", result.arguments, text)

    def test_non_weather_text_never_gets_a_location(self):
        for text in ("hava yolu bileti al", "ankara notlarımı göster"):
            self.assertNotIn("location", understood(text).arguments, text)


class WeatherCoreMapTests(unittest.TestCase):
    def test_plan_validates_and_capitalizes_city(self):
        for hint in ("weather.read", "weather.read.current"):
            self.assertEqual(brain_core_map.core_plan(hint, {"location": "izmir"}), ("weather", {"location": "İzmir"}))
            self.assertEqual(brain_core_map.core_plan(hint, {"location": "ısparta"}), ("weather", {"location": "Isparta"}))
            self.assertEqual(brain_core_map.core_plan(hint, {}), ("weather", {}))

    def test_invalid_location_is_not_executed(self):
        for location in ("ab", "x" * 40, "izmir; rm -rf", 5, "", "izmir hava"):
            self.assertIsNone(brain_core_map.core_plan("weather.read", {"location": location}), location)


class WeatherIntentTests(unittest.TestCase):
    def test_dispatch_uses_the_validated_location(self):
        runtime = SimpleNamespace(_weather=Mock(return_value="Güneşli"), _session=lambda: session_state.SessionState())
        with patch("modules.requests_state.check"):
            self.assertEqual(engine_intents.dispatch(runtime, "weather", {"location": "İzmir"}, "x", "x"), "Güneşli")
        runtime._weather.assert_called_once_with("İzmir")
        runtime._weather.reset_mock()
        with patch("modules.requests_state.check"):
            engine_intents.dispatch(runtime, "weather", {}, "x", "x")
        runtime._weather.assert_called_once_with(None)


class EndToEndTests(unittest.TestCase):
    """Real SessionStore -> build_active_context -> prepare (gates, candidates, understanding) -> handoff."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from modules import llm, service_store
        token=llm._key_context.set(OWNER)
        self.addCleanup(llm._key_context.reset,token)
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        checkpoint_root=patch.object(service_store,'ROOT',Path(temporary.name))
        checkpoint_root.start();self.addCleanup(checkpoint_root.stop)
        self.store = session_state.SessionStore()
        self.state = self.store.for_owner(OWNER)
        self.runtime = SimpleNamespace(
            profile=SimpleNamespace(slug=OWNER, name="Hamdi", data={}),
            _sessions=self.store, _session=lambda: self.state,
            flags={"sleep": False}, _pending_photo={},
        )

    def run_turn(self, text, *, model_understanding=False):
        history = lambda owner, *, limit: []
        original = brain_entry.brain_context.build_active_context

        def context(**kwargs):
            kwargs.setdefault("history_reader", history)
            kwargs.setdefault("history_filter", lambda owner, rows: rows)
            kwargs.setdefault("goal_reader", lambda owner: None)
            kwargs.setdefault("goal_is_open", lambda row: False)
            return original(**kwargs)

        handler = Mock(return_value="<<handler>>")
        with patch.object(brain_entry.brain_context, "build_active_context", context), \
             patch("modules.job_front.observe", lambda owner: None), \
             patch("modules.desktop_agent._load", lambda owner: None), \
             patch.object(core_brain_adapter, "_correlated_job_id", return_value=None), \
             patch("modules.engine_intents.dispatch", return_value="<<dispatch>>") as dispatch:
            entry = brain_entry.prepare(self.runtime, owner=OWNER, request_id=RID, text=text, source="yazı", model_understanding=model_understanding)
            output, feedback, _ = core_brain_adapter.handoff(self.runtime, entry, handler, text)
        return entry, output, feedback, handler, dispatch

    def test_open_pending_level_is_superseded_by_an_explicit_level_request(self):
        self.state.pending_level = 70
        entry, output, feedback, handler, dispatch = self.run_turn("sesi 30 yap")
        handler.assert_not_called()   # eski handler pending'deki 70'i uygulamamalı
        dispatch.assert_called_once()
        self.assertEqual(dispatch.call_args.args[1:3], ("level_set", {"property": "volume", "level": 30}))

    def test_level_set_intent_clears_the_stale_question(self):
        self.state.pending_level = 70
        runtime = SimpleNamespace(_session=lambda: self.state,
                                  system_control=Mock(set_volume=Mock(return_value=True)))
        with patch("modules.requests_state.check"):
            engine_intents.dispatch(runtime, "level_set", {"property": "volume", "level": 30}, "x", "x")
        self.assertIsNone(self.state.pending_level)
        runtime.system_control.set_volume.assert_called_once_with(30)

    def test_answer_to_the_level_question_still_goes_through_state_gate(self):
        self.state.pending_level = 70
        entry, output, feedback, handler, dispatch = self.run_turn("ses")
        self.assertEqual((entry.stage, entry.state_gate.protocol), ("state", "session.pending_level.select"))
        # PR3A: cevabın etkisi legacy handler'ın ham metin dalından değil, tek sahibinden yürür.
        handler.assert_not_called()
        self.assertEqual(dispatch.call_args.args[1:3], ("level_set", {"property": "volume", "level": 70}))

    def test_unrelated_pending_state_does_not_veto_the_level_plan(self):
        self.state.pending_confirm = "shutdown"
        entry, output, feedback, handler, dispatch = self.run_turn("sesi 30 yap")
        # NEW_REQUEST + CAPABILITY bağımsız istektir: açık onay yalnız kendi cevabını sahiplenir.
        self.assertEqual(brain_entry.core_plan(entry), ("level_set", {"property": "volume", "level": 30}))
        self.assertEqual(dispatch.call_args.args[1:3], ("level_set", {"property": "volume", "level": 30}))
        self.assertEqual(self.state.pending_confirm, "shutdown")

    def test_bare_number_with_fresh_last_property_end_to_end(self):
        session_state.remember_property(self.state, "brightness")
        entry, output, feedback, handler, dispatch = self.run_turn("70 yap")
        handler.assert_not_called()
        self.assertEqual(dispatch.call_args.args[1:3], ("level_set", {"property": "brightness", "level": 70}))

    def test_bare_number_without_property_asks_and_opens_pending_level_end_to_end(self):
        entry, output, feedback, handler, dispatch = self.run_turn("70 yap")
        self.assertEqual(output, "Yüzde 70, ses mi parlaklık mı?")
        self.assertEqual(self.state.pending_level, 70)
        handler.assert_not_called()
        dispatch.assert_not_called()

    def test_other_owner_property_is_not_used_end_to_end(self):
        session_state.remember_property(self.store.for_owner("hasan"), "volume")
        entry, output, feedback, handler, dispatch = self.run_turn("70 yap")
        self.assertEqual(output, "Yüzde 70, ses mi parlaklık mı?")

    def test_weather_with_city_dispatches_core_intent_end_to_end(self):
        entry, output, feedback, handler, dispatch = self.run_turn("ankara'da hava nasıl")
        handler.assert_not_called()
        self.assertEqual(dispatch.call_args.args[1:3], ("weather", {"location": "Ankara"}))

    def test_sequenced_requests_execute_only_the_model_action_batch(self):
        from brain_turn_fixture import batch_model
        proposal = batch_model(("weather.read", {"location": "ankara"}),
                               ("pc.level.set", {"property": "volume", "level": 30}))
        with patch.object(brain_entry, "apply_model_understanding", side_effect=proposal):
            entry, output, feedback, handler, dispatch = self.run_turn(
                "ankara'da hava nasıl ardından sesi 30 yap", model_understanding=True)
        handler.assert_not_called()
        self.assertEqual(dispatch.call_count, 2)
        self.assertEqual([call.args[1] for call in dispatch.call_args_list], ["weather", "level_set"])
        self.assertEqual(feedback.result_status, "partial")
        self.assertIn("a1:", output)
        self.assertIn("a2:", output)
        # Plain transport strings are not domain success receipts.

    def test_step_marker_matches_the_step_plan(self):
        # Tek gramer sahibi: veto işareti ile tipli adım planı aynı kalıptan doğar ve anlaşır.
        from modules.brain_understanding import is_sequenced, sequence_steps
        for text in ("önce hava nasıl sonra sesi kıs", "ankara'da hava nasıl", "sesi 30 yap",
                     "hava nasıl ardından sesi kıs", "önce sesi kıs", "İzmir'de hava nasıl"):
            self.assertEqual(is_sequenced(text),
                             sequence_steps(text) != () or text.startswith("önce"), text)

    def test_lowercase_city_answer_completes_the_weather_question_without_a_provider(self):
        """Sağlayıcı düşse bile şehir cevabı bitmeli.

        Canlı kanıt (21 Kasım 09:48): Gemini sözleşmeden, Groq 413'ten döndü; tur
        'güvenli biçimde doğrulayamadım' ile bitti. Oysa slot kapalı sözlükle
        ayrılabiliyor: 'istanbul' konumdur, 'hava nasıl'/'merhaba' değildir.
        """
        self.state.pending_weather_location = True
        with patch("modules.engine_intents.dispatch", return_value="İstanbul: parçalı bulutlu") as dispatch:
            answered = core_brain_adapter._pending_weather_answer(self.runtime, "istanbul")
        self.assertEqual(answered, "İstanbul: parçalı bulutlu")
        self.assertEqual(dispatch.call_args.args[1:3], ("weather", {"location": "İstanbul"}))
        self.assertFalse(self.state.pending_weather_location)
        # Şehir olmayan cevap bu yolu kullanmaz: açık soru açık kalır.
        self.state.pending_weather_location = True
        with patch("modules.engine_intents.dispatch") as dispatch2:
            self.assertIsNone(core_brain_adapter._pending_weather_answer(self.runtime, "hava nasıl"))
        dispatch2.assert_not_called()
        self.assertIs(self.state.pending_weather_location, True)

    def test_weather_request_is_not_captured_by_an_open_location_question(self):
        self.state.pending_weather_location = True
        entry, output, feedback, handler, dispatch = self.run_turn("hava nasıl")
        # "hava nasıl" yeni bir hava isteğidir; açık şehir sorusunun cevabı sayılmaz.
        self.assertEqual(entry.understanding.conversation_relation, ConversationRelation.NEW_REQUEST)
        self.assertEqual(brain_entry.core_plan(entry), ("weather", {}))
        self.assertEqual(dispatch.call_args.args[1], "weather")
        self.assertIs(self.state.pending_weather_location, True)


if __name__ == "__main__":
    unittest.main()
