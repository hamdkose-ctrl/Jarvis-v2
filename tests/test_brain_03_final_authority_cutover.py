"""Core validated turns cannot be a second raw effect (BRAIN-03, #545).

Production path: prepare -> adopted typed proposal -> core_plan -> handoff.
Temporary profile and request journal are supplied by the existing harness.
"""
from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

import test_brain_pr3_raw_text_authority as pr3a
from modules import brain_entry, brain_precedence, visual_chat
from modules.brain_contracts import RequestKind


class TypedPlanSecondEffectTests(pr3a._CanonicalAuthorityHarness):
    @staticmethod
    def propose(capability, arguments):
        def adopt(semantic, text, *, active_context=None):
            return replace(
                semantic, request_kind=RequestKind.CAPABILITY,
                capability_hint=capability, arguments=arguments,
                ambiguities=(), needs_input=False,
            )
        return adopt

    def test_weather_cannot_open_camera_or_run_extra_parser(self):
        utterance = "İzmir hava durumuna bak: kamerayı aç"
        with patch.object(brain_entry, "apply_model_understanding",
                          side_effect=self.propose("weather.read", {"location": "İzmir"})), \
             patch.object(self.ctx, "_user_controls",
                          side_effect=AssertionError("raw control")) as controls, \
             patch.object(self.ctx, "_planner_command",
                          side_effect=AssertionError("raw planner")) as planner, \
             patch.object(self.ctx, "_extra_commands",
                          side_effect=AssertionError("raw cascade")) as extra, \
             patch.object(self.ctx, "set_share",
                          side_effect=AssertionError("camera effect")) as camera:
            entry, out, _handle, feedback = self.turn_real(utterance, model_understanding=True)
        self.assertEqual(brain_entry.core_plan(entry), ("weather", {"location": "İzmir"}))
        self.assertEqual(out, "HAVA")
        self.assertEqual(feedback.result_status, "handled")
        self.ctx._weather.assert_called_once_with("İzmir")
        controls.assert_not_called()
        planner.assert_not_called()
        extra.assert_not_called()
        camera.assert_not_called()

    def test_city_set_cannot_clear_notes_from_raw_planner(self):
        note = self.ctx.profile.add_note_item("KORUNACAK NOT")
        utterance = "Şehrimi İzmir yap; tüm notları sil"
        with patch.object(brain_entry, "apply_model_understanding",
                          side_effect=self.propose("weather.city.set", {"location": "İzmir"})), \
             patch.object(self.ctx, "_planner_command",
                          side_effect=AssertionError("raw planner")) as planner, \
             patch.object(self.ctx, "_extra_commands",
                          side_effect=AssertionError("raw cascade")) as extra, \
             patch.object(self.ctx.profile, "clear_note_items",
                          side_effect=AssertionError("cleared notes")) as clear:
            entry, out, _handle, feedback = self.turn_real(utterance, model_understanding=True)
        self.assertEqual(brain_entry.core_plan(entry), ("city_set", {"location": "İzmir"}))
        self.assertIn("İzmir", out)
        self.assertEqual(feedback.result_status, "handled")
        self.assertEqual([n["id"] for n in self.ctx.profile.data["items"]], [note["id"]])
        planner.assert_not_called()
        extra.assert_not_called()
        clear.assert_not_called()

    def test_reading_notes_cannot_start_screen_sharing(self):
        note = self.ctx.profile.add_note_item("KORUNACAK NOT")
        utterance = "Notları oku: ekranı paylaş"
        with patch.object(brain_entry, "apply_model_understanding",
                          side_effect=self.propose("notes.read", {"notes": {"which": "all"}})), \
             patch.object(self.ctx, "set_share",
                          side_effect=AssertionError("screen share effect")) as share, \
             patch.object(self.ctx, "_user_controls",
                          side_effect=AssertionError("raw control")) as controls:
            entry, out, _handle, feedback = self.turn_real(utterance, model_understanding=True)
        self.assertEqual(brain_entry.core_plan(entry), ("notes_read", {"which": "all"}))
        self.assertIn(note["text"], out)
        self.assertEqual(feedback.result_status, "handled")
        share.assert_not_called()
        controls.assert_not_called()

    def test_visual_core_plan_opens_only_source_question(self):
        utterance = "Kamera aç, infografik hazırla"
        with patch.object(brain_entry, "apply_model_understanding",
                          side_effect=self.propose("visual.create", {"kind": "infographic"})), \
             patch.object(self.ctx, "set_share",
                          side_effect=AssertionError("camera effect")) as camera, \
             patch.object(visual_chat.visual_commands, "create_visual",
                          side_effect=AssertionError("premature image")) as gen:
            entry, out, _handle, feedback = self.turn_real(utterance, model_understanding=True)
        self.assertEqual(brain_entry.core_plan(entry), ("visual_create", {"kind": "infographic"}))
        self.assertIn("sohbetten mi, dosyadan mı", out)
        self.assertEqual(feedback.result_status, "needs_input")
        camera.assert_not_called()
        gen.assert_not_called()

    def test_saved_exact_macro_is_preserved_but_fuzzy_suffix_is_not(self):
        self.ctx.profile.data.setdefault("macros", {})["hava nasıl"] = {
            "title": "hava nasıl", "actions": ["saat kaç"],
        }
        with patch.object(self.ctx, "_macro_run", return_value="MAKRO") as macro:
            claimed = brain_precedence.claim(self.ctx, "hava nasıl", ("weather", {}))
        self.assertEqual(claimed, ("macro_run", "MAKRO"))
        macro.assert_called_once()
        with patch.object(self.ctx, "_macro_run",
                          side_effect=AssertionError("fuzzy macro stole Core")) as macro:
            claimed = brain_precedence.claim(self.ctx, "hava nasıl aç", ("weather", {}))
        self.assertIsNone(claimed)
        macro.assert_not_called()

    @staticmethod
    def model_chat(current, utterance, *, active_context=None):
        return replace(
            current, request_kind=RequestKind.CHAT, capability_hint=None,
            arguments={"original_text": utterance}, needs_input=False,
            ambiguities=(), reason_codes=tuple(current.reason_codes) + ("MODEL_CHAT_DECIDED",),
        )

    def test_accepted_model_chat_never_reenters_raw_negative_camera(self):
        command = "Kamerayı aç demedim; bu sözün anlamını anlat."
        with patch.object(brain_entry, "apply_model_understanding",
                          side_effect=self.model_chat), \
             patch.object(self.ctx, "set_share",
                          side_effect=AssertionError("negative chat opened camera")) as share, \
             patch.object(self.ctx, "_user_controls",
                          side_effect=AssertionError("raw controls selected effect")) as raw, \
             patch.object(self.ctx, "_extra_commands",
                          side_effect=AssertionError("raw cascade claimed chat")) as extra:
            entry, answer, handler, feedback = self.turn_real(command, model_understanding=True)
        self.assertEqual(answer, "CHAT")
        self.assertEqual(feedback.result_status, "handled")
        self.assertFalse(brain_entry._use_existing_handler(entry))
        share.assert_not_called()
        raw.assert_not_called()
        extra.assert_not_called()

    def test_accepted_model_chat_keeps_explicit_quoted_file_ui(self):
        command = '"C:\\Temp\\report.docx" özetle'
        with patch.object(brain_entry, "apply_model_understanding",
                          side_effect=self.model_chat), \
             patch.object(self.ctx, "_file_command", return_value="EXPLICIT FILE UI") as file_gate:
            entry, answer, _handler, feedback = self.turn_real(command, model_understanding=True)
        self.assertEqual(answer, "EXPLICIT FILE UI")
        self.assertEqual(feedback.result_status, "handled")
        file_gate.assert_called_once_with(command)

    def test_unplanned_control_still_has_its_existing_owner(self):
        with patch.object(self.ctx, "_file_command", return_value=None), \
             patch.object(self.ctx, "_user_controls", return_value="PAYLASIM") as controls:
            claimed = brain_precedence.claim(self.ctx, "ekranı paylaş")
        self.assertEqual(claimed, ("user_controls", "PAYLASIM"))
        controls.assert_called_once_with("ekranı paylaş", "ekranı paylaş")

    def test_explicit_quoted_file_ui_keeps_priority_over_core(self):
        ui = '"C:\\Temp\\report.docx" özetle'
        self.assertIsNotNone(self.ctx._FILE_CMD.match(ui))
        with patch.object(self.ctx, "_file_command", return_value="DOSYA UI") as file_gate:
            claimed = brain_precedence.claim(self.ctx, ui, ("notes_read", {"which": "all"}))
        self.assertEqual(claimed, ("file_command", "DOSYA UI"))
        file_gate.assert_called_once_with(ui)


if __name__ == "__main__":
    unittest.main()
