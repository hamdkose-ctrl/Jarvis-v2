"""Eski `modules.router` hızlı yol Sözleşmeleri artık canonical sınırdadır: hiçbir cümle
model sınıfleyicisine düşmez, model çıktısı karar verici olamaz, deterministik hükümler
tanıyıcı + Core doğrulaması ile üretilir."""
import unittest

from modules import brain_core_map, brain_understanding
from modules.brain_contracts import ActiveContext, RequestKind

OWNER, RID = "hamdi", "rid-router"


def decide(text):
    semantic = brain_understanding.understand(owner=OWNER, request_id=RID, text=text,
                                              active_context=ActiveContext(owner=OWNER, request_id=RID),
                                              candidates=(), references=())
    return semantic, brain_core_map.core_plan(semantic.capability_hint, semantic.arguments)


class CanonicalFastPathTests(unittest.TestCase):
    def test_greeting_is_chat_without_a_model_call(self):
        semantic, plan = decide("merhaba")
        self.assertIs(semantic.request_kind, RequestKind.CHAT)
        self.assertIsNone(plan)

    def test_instruction_question_stays_chat(self):
        semantic, _plan = decide("Chrome nasıl açılır?")
        self.assertIs(semantic.request_kind, RequestKind.CHAT)

    def test_screen_analysis_is_not_status(self):
        from modules import brain_gates
        semantic, plan = decide("ekranı analiz et")
        self.assertEqual(plan, ("screen_analyze", {"question": ""}))
        self.assertFalse(brain_gates.deterministic_fast_gate(
            owner=OWNER, request_id=RID, text="ekranı analiz et",
            active_context=ActiveContext(owner=OWNER, request_id=RID)).matched)
        self.assertTrue(brain_gates.deterministic_fast_gate(
            owner=OWNER, request_id=RID, text="sistem durumu",
            active_context=ActiveContext(owner=OWNER, request_id=RID)).matched)

    def test_system_status_is_separate(self):
        from modules import brain_gates
        hit = brain_gates.deterministic_fast_gate(owner=OWNER, request_id=RID, text="sistem durumu",
                                                  active_context=ActiveContext(owner=OWNER, request_id=RID))
        self.assertTrue(hit.matched)
        self.assertEqual(hit.protocol, "fast.system.status")

    def test_no_hint_without_a_core_intent_can_become_a_promise(self):
        # Model/öneri adı Core manifestinde niyet taşımıyorsa plan üretilemez; projection clarify'e düşer.
        for hint in ("shell", "chat", "", None, "unknown.capability"):
            with self.subTest(hint=hint):
                self.assertIsNone(brain_core_map.core_plan(hint, {}))

    def test_the_legacy_classifier_has_no_module_to_import(self):
        import importlib.util
        for module in ("router", "work_modes", "freshness"):
            with self.subTest(module=module):
                self.assertIsNone(importlib.util.find_spec(f"modules.{module}"), module)


if __name__ == "__main__":
    unittest.main()
