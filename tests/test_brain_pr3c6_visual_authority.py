"""PR3C-6 RED tests: chat visual creation must be proposed by canonical Brain.

The current visual_chat keyword detector runs before Understanding and can claim
ordinary text. These tests pin the desired proposal boundary before production
changes: explicit visual creation is a typed capability; asking about a visual
term remains ordinary chat.
"""
from __future__ import annotations

import unittest

from modules.brain_contracts import ActiveContext, RequestKind
from modules.brain_understanding import understand


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
        self.assertEqual(result.capability_hint, "visual.create")
        self.assertEqual(result.arguments.get("kind"), "mindmap")

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
