"""BRAIN-03 PC guide typed admission; no second raw natural-language owner."""
from dataclasses import replace
import unittest
from unittest.mock import Mock, patch

from modules import brain_core_map, brain_entry, pc_guide
from modules.brain_contracts import RequestKind
from test_brain_pr3_raw_text_authority import _CanonicalAuthorityHarness


class PCGuideCoreContractTests(unittest.TestCase):
    def test_user_grounded_read_only_goal(self):
        self.assertEqual(
            brain_core_map.core_plan("pc.guide.start", {
                "goal": "wifi nasıl açılır"}),
            ("pc_guide_start", {"goal": "wifi nasıl açılır"}))
        for payload in (
            {}, {"goal": ""}, {"goal": "x" * 501},
            {"goal": "wifi\ncommand"}, {"goal": "wifi", "command": "powershell"},
            {"goal": "wifi", "click": True}, {"goal": "wifi", "owner": "another"},
        ):
            with self.subTest(payload=payload):
                self.assertIsNone(brain_core_map.core_plan("pc.guide.start", payload))


class PCGuideCanonicalTests(_CanonicalAuthorityHarness):
    def test_model_selected_guide_reaches_exactly_one_existing_worker(self):
        text = "adım adım wifi nasıl açılır"
        def model(current, text_in, *, active_context=None):
            self.assertEqual(text_in, text)
            return replace(
                current, request_kind=RequestKind.CAPABILITY,
                capability_hint="pc.guide.start",
                arguments={"original_text": text_in, "goal": "wifi nasıl açılır"},
                needs_input=False, ambiguities=(), actions=(),
            )
        with patch.object(brain_entry, "apply_model_understanding", side_effect=model), \
             patch.object(pc_guide, "handle", return_value="Rehber başladı") as worker:
            entry, output, _handler, feedback = self.turn(
                text, handler=Mock(side_effect=AssertionError("raw fallback used")),
                model_understanding=True)
        self.assertEqual(entry.understanding.capability_hint, "pc.guide.start")
        self.assertEqual(output, "Rehber başladı")
        self.assertEqual(feedback.result_status, "handled")
        worker.assert_called_once_with(self.ctx.profile, "PC yardımı: wifi nasıl açılır")

    def test_model_chat_cannot_start_desktop_guidance(self):
        def chat(current, text, *, active_context=None):
            return replace(current, request_kind=RequestKind.CHAT,
                           capability_hint=None,
                           arguments={"original_text": text},
                           needs_input=False, ambiguities=(), actions=())
        with patch.object(brain_entry, "apply_model_understanding", side_effect=chat), \
             patch.object(pc_guide, "handle",
                          side_effect=AssertionError("CHAT invoked desktop worker")) as worker:
            entry, _output, _handler, feedback = self.turn(
                "adım adım wifi nasıl açılır",
                model_understanding=True)
        self.assertEqual(entry.understanding.request_kind, RequestKind.CHAT)
        self.assertEqual(feedback.result_status, "handled")
        worker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
