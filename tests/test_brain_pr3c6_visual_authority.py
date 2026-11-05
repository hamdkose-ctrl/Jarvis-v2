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



class VisualNegativeAndParityRegressionTests(unittest.TestCase):
    def test_negated_visual_summary_is_chat(self):
        result = decide("süreç özeti istemiyorum")
        self.assertIs(result.request_kind, RequestKind.CHAT)
        self.assertIsNone(result.capability_hint)

    def test_passive_negated_visual_action_is_chat(self):
        result = decide("bu infografik oluşturulmasın")
        self.assertIs(result.request_kind, RequestKind.CHAT)
        self.assertIsNone(result.capability_hint)

    def test_passive_negated_drawing_is_chat(self):
        result = decide("akış şeması çizilmesin")
        self.assertIs(result.request_kind, RequestKind.CHAT)
        self.assertIsNone(result.capability_hint)

    def test_legacy_positive_visual_phrases_keep_their_type(self):
        cases = (
            ("zihin haritası çıkar", "mindmap"),
            ("infografik istiyorum", "infographic"),
            ("akış şeması yap", "flowchart"),
            ("kronoloji oluştur", "timeline"),
            ("el yazısı notu hazırla", "handwritten"),
            ("teknik çizim tasarla", "blueprint"),
        )
        for phrase, expected in cases:
            with self.subTest(phrase=phrase):
                result = decide(phrase)
                self.assertIs(result.request_kind, RequestKind.CAPABILITY)
                self.assertEqual(result.capability_hint, VISUAL_CAPABILITY)
                self.assertEqual(result.arguments.get("kind"), expected)


class VisualConversationRoundTripTests(pr3b._RawDoorHarness):
    def test_brain_state_core_worker_round_trip_uses_the_bound_source_answer(self):
        from modules.visual_commands import VisualResult

        fake = VisualResult(kind="mindmap", label="zihin haritası", path="/x/mindmap.png")
        with patch("modules.visual_commands.create_visual", return_value=fake) as generate, \
             patch.object(self.ctx.history, "read", return_value=[
                 {"text": "Birinci adım"}, {"text": "İkinci adım"},
             ]) as history_read:
            first, question, _handle, first_feedback = self.turn("zihin haritası oluştur")
            self.assertEqual(first.understanding.capability_hint, VISUAL_CAPABILITY)
            self.assertIn("sohbetten mi, dosyadan mı", question)
            self.assertEqual(first_feedback.result_status, "needs_input")
            self.assertIsNotNone(self.ctx._session().pending_visual)

            second, output, _handle, second_feedback = self.turn("sohbetten")
        self.assertTrue(second.state_gate.matched)
        self.assertEqual(second.state_gate.protocol, "session.pending_visual.select")
        self.assertEqual(second.state_gate.selection, "chat")
        self.assertIn("/x/mindmap.png", output)
        self.assertIsNone(self.ctx._session().pending_visual)
        self.assertEqual(second_feedback.result_status, "handled")
        generate.assert_called_once_with(
            "zihin haritası oluştur", "Birinci adım\\nİkinci adım",
            slug=self.owner, kind="mindmap",
        )
        history_read.assert_called_once()

    def test_second_visual_request_does_not_overwrite_the_first_pending_source(self):
        first, question, _handle, _feedback = self.turn("zihin haritası oluştur")
        pending_before = dict(self.ctx._session().pending_visual)
        second, reply, _handle, _feedback = self.turn("infografik hazırla")
        self.assertEqual(second.understanding.capability_hint, VISUAL_CAPABILITY)
        self.assertEqual(self.ctx._session().pending_visual, pending_before)
        self.assertIn("önce", reply.casefold())
        self.assertIn("zihin haritası", reply.casefold())
        self.assertNotEqual(first.request_id, second.request_id)

    def test_file_source_answer_uses_the_existing_explicit_file_button(self):
        with patch("modules.visual_commands.create_visual") as generate:
            self.turn("zihin haritası oluştur")
            second, reply, _handle, feedback = self.turn("dosyadan olsun")
        self.assertTrue(second.state_gate.matched)
        self.assertEqual(second.state_gate.selection, "file")
        self.assertIn("Dosyalar sayfasında", reply)
        self.assertIsNone(self.ctx._session().pending_visual)
        self.assertEqual(feedback.result_status, "handled")
        generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
