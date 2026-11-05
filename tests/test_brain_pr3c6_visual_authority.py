"""PR3C-6 RED tests: chat visual creation must be proposed by canonical Brain.

The current visual_chat keyword detector runs before Understanding and can claim
ordinary text. These tests pin the desired proposal boundary before production
changes: explicit visual creation is a typed capability; asking about a visual
term remains ordinary chat.
"""
from __future__ import annotations

import unittest

from modules.brain_contracts import ActiveContext, RequestKind
from modules.brain_core_map import core_plan
from modules.brain_understanding import VISUAL_CAPABILITY, understand


OWNER = "hamdi"


def decide(text: str):
    request_id = "visual-authority-test"
    return understand(
        owner=OWNER,
        request_id=request_id,
        text=text,
        active_context=ActiveContext(owner=OWNER, request_id=request_id),
        candidates=(),
        references=(),
    )


class CanonicalVisualProposalTests(unittest.TestCase):
    def test_explicit_mindmap_creation_is_a_typed_visual_capability(self):
        result = decide("zihin haritası oluştur")
        self.assertIs(result.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(result.capability_hint, VISUAL_CAPABILITY)
        self.assertEqual(result.arguments.get("kind"), "mindmap")
        self.assertEqual(core_plan(result.capability_hint, result.arguments),
                         ("visual_create", {"kind": "mindmap"}))

    def test_natural_process_summary_phrase_is_a_visual_request(self):
        result = decide("süreç özeti")
        self.assertIs(result.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(result.capability_hint, VISUAL_CAPABILITY)
        self.assertEqual(result.arguments.get("kind"), "visualize")
        self.assertEqual(core_plan(result.capability_hint, result.arguments),
                         ("visual_create", {"kind": "visualize"}))

    def test_core_rejects_unknown_visual_kind(self):
        self.assertIsNone(core_plan(VISUAL_CAPABILITY, {"kind": "arbitrary", "original_text": "görsel oluştur"}))

    def test_visual_type_question_remains_chat(self):
        result = decide("infografik nedir?")
        self.assertIs(result.request_kind, RequestKind.CHAT)
        self.assertIsNone(result.capability_hint)

    def test_visual_type_mentioned_as_subject_is_not_an_execution_request(self):
        result = decide("infografik hazırlamak için hangi veriler gerekir?")
        self.assertIs(result.request_kind, RequestKind.CHAT)
        self.assertIsNone(result.capability_hint)


if __name__ == "__main__":
    unittest.main()
