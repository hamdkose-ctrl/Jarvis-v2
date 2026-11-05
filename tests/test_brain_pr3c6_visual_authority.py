"""PR3C-6 RED tests: chat visual creation must be proposed by canonical Brain.

The current visual_chat keyword detector runs before Understanding and can claim
ordinary text. These tests pin the desired proposal boundary before production
changes: explicit visual creation is a typed capability; asking about a visual
term remains ordinary chat.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import test_brain_pr3b_legacy_front_door_authority as pr3b
from modules.brain_contracts import (
    ActiveContext, Confidence, ConversationRelation, RequestKind, TemporalNeed,
)
from modules.brain_core_map import core_plan
from modules.brain_understanding import VISUAL_CAPABILITY, apply_model_refinement, understand


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

    def test_optional_model_cannot_downgrade_visual_creation_to_chat(self):
        from modules.brain_model_understanding import SemanticRefinement

        result = decide("zihin haritası oluştur")
        proposal = SemanticRefinement(
            request_kind=RequestKind.CHAT,
            conversation_relation=ConversationRelation.NEW_REQUEST,
            temporal_need=TemporalNeed.UNSURE,
            capability_hint=None,
            confidence=Confidence.MEDIUM,
        )
        with patch("modules.brain_model_understanding.refine", return_value=proposal):
            refined = apply_model_refinement(result, "zihin haritası oluştur")
        self.assertIs(refined, result)
        self.assertEqual(refined.capability_hint, VISUAL_CAPABILITY)
        self.assertIs(refined.request_kind, RequestKind.CAPABILITY)

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


    def test_explicit_pc_task_prefix_is_not_a_visual_capability(self):
        result = decide("pc görevi: infografik çiz")
        self.assertNotEqual(result.capability_hint, VISUAL_CAPABILITY)


class VisualCoreDispatchTests(pr3b._RawDoorHarness):
    def test_chat_visual_request_reaches_core_and_only_opens_source_question(self):
        from modules import visual_chat

        with patch.object(visual_chat.visual_commands, "create_visual") as create_visual:
            entry, out, _handle, _feedback = self.turn("zihin haritası oluştur")

        self.assertIs(entry.understanding.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(entry.understanding.capability_hint, VISUAL_CAPABILITY)
        self.assertIn("sohbetten mi, dosyadan mı", out)
        self.assertEqual(
            self.ctx._session().pending_visual,
            {"text": "zihin haritası oluştur", "kind": "mindmap", "stage": "source"},
        )
        create_visual.assert_not_called()
        self.ctx._extra_commands.assert_not_called()


if __name__ == "__main__":
    unittest.main()
