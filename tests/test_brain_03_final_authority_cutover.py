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
             patch.object(self.ctx, "_user_controls", side_effect=AssertionError("raw control"), create=True) as controls, \
             patch.object(self.ctx, "_planner_command", side_effect=AssertionError("raw planner"), create=True) as planner, \
             patch.object(self.ctx, "_extra_commands", side_effect=AssertionError("raw cascade"), create=True) as extra, \
             patch.object(self.ctx, "set_share",
                          side_effect=AssertionError("camera effect")) as camera:
            entry, out, _handle, feedback = self.turn_real(utterance, model_understanding=True)
        # A single action cannot partially execute a multi-command utterance.
        self.assertIsNone(brain_entry.core_plan(entry))
        self.assertIn("işlem başlatılmadı", out)
        self.assertEqual(feedback.result_status, "failed")
        self.ctx._weather.assert_not_called()
        controls.assert_not_called()
        planner.assert_not_called()
        extra.assert_not_called()
        camera.assert_not_called()

    def test_city_set_cannot_clear_notes_from_raw_planner(self):
        note = self.ctx.profile.add_note_item("KORUNACAK NOT")
        utterance = "Şehrimi İzmir yap; tüm notları sil"
        with patch.object(brain_entry, "apply_model_understanding",
                          side_effect=self.propose("weather.city.set", {"location": "İzmir"})), \
             patch.object(self.ctx, "_planner_command", side_effect=AssertionError("raw planner"), create=True) as planner, \
             patch.object(self.ctx, "_extra_commands", side_effect=AssertionError("raw cascade"), create=True) as extra, \
             patch.object(self.ctx.profile, "clear_note_items",
                          side_effect=AssertionError("cleared notes")) as clear:
            entry, out, _handle, feedback = self.turn_real(utterance, model_understanding=True)
        self.assertIsNone(brain_entry.core_plan(entry))
        self.assertIn("işlem başlatılmadı", out)
        self.assertEqual(feedback.result_status, "failed")
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
             patch.object(self.ctx, "_user_controls", side_effect=AssertionError("raw control"), create=True) as controls:
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
             patch.object(self.ctx, "_user_controls", side_effect=AssertionError("raw controls selected effect"), create=True) as raw, \
             patch.object(self.ctx, "_extra_commands", side_effect=AssertionError("raw cascade claimed chat"), create=True) as extra:
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

    def test_model_outage_negative_or_quoted_note_clear_never_mutates(self):
        from modules import brain_model_understanding
        note = self.ctx.profile.add_note_item("ASIL NOT")
        with patch.object(brain_model_understanding, "propose", return_value=None), \
             patch.object(self.ctx.profile, "clear_note_items",
                          side_effect=AssertionError("negative note deletion")) as clear:
            for command in ("notları silme", "Ali'ye 'tüm notları sil' mesaj gönder",
                            "notları sil demedim"):
                with self.subTest(command=command):
                    entry, reply, _handler, feedback = self.turn_real(
                        command, model_understanding=True)
                    self.assertEqual(feedback.result_status, "failed")
                    self.assertIn("model", reply.casefold())
        self.assertEqual([x["id"] for x in self.ctx.profile.data["items"]], [note["id"]])
        clear.assert_not_called()
    def test_typed_note_clear_requires_owner_bound_snapshot_confirmation(self):
        note = self.ctx.profile.add_note_item("ASIL NOT")
        from modules import main_planner
        command = "tüm notları sil"
        with patch.object(brain_entry, "apply_model_understanding",
                          side_effect=self.propose("notes.manage", {"operation": "clear_all"})), \
             patch.object(self.ctx.profile, "clear_note_items",
                          side_effect=AssertionError("clear before approval")) as clear:
            _entry, response, _handler, feedback = self.turn_real(
                command, model_understanding=True)
        self.assertEqual(feedback.result_status, "needs_input")
        self.assertIn("onaylıyor musun", response)
        clear.assert_not_called()
        proposal = self.ctx._session().pending_confirm
        self.assertEqual(proposal["action"], "notes_clear")
        self.assertEqual(proposal["owner"], self.owner)
        invalid = {**proposal, "owner": "foreign"}
        self.assertIn("geçersiz", main_planner.clear_notes_confirmed(self.ctx, invalid))
        self.assertEqual([row["id"] for row in self.ctx.profile.data["items"]],
                         [note["id"]])
    def test_numbered_note_delete_cannot_be_guessed_on_model_outage(self):
        from modules import brain_model_understanding, main_planner
        first = self.ctx.profile.add_note_item("SİLİNECEK")
        second = self.ctx.profile.add_note_item("KALACAK")
        self.assertFalse(hasattr(main_planner, "_planner_command"))
        with patch.object(brain_model_understanding, "propose", return_value=None), \
             patch.object(self.ctx.profile, "delete_note_item",
                          side_effect=AssertionError("legacy ordinal deletion")) as delete:
            for command in ("2. notu silme", "1. notu sil"):
                _entry, reply, _handler, feedback = self.turn_real(
                    command, model_understanding=True)
                self.assertEqual(feedback.result_status, "failed")
                self.assertIn("model", reply.casefold())
        delete.assert_not_called()
        self.assertEqual([row["id"] for row in self.ctx.profile.data["items"]],
                         [first["id"], second["id"]])
    def test_legacy_named_note_update_negative_must_not_change_profile(self):
        from modules import brain_model_understanding
        note = self.ctx.profile.add_note_item("Market alışverişi")
        snapshot = [dict(row) for row in self.ctx.profile.data["items"]]
        with patch.object(brain_model_understanding, "propose", return_value=None), \
             patch.object(self.ctx.profile, "add_note_item",
                          side_effect=AssertionError("negative update added a note")) as add, \
             patch.object(self.ctx.profile, "delete_note_item",
                          side_effect=AssertionError("negative update deleted a note")) as delete:
            self.turn_real("market notunu düzeltme: süt al", model_understanding=True)
        self.assertEqual(self.ctx.profile.data["items"], snapshot)
        self.assertEqual(next(row["text"] for row in self.ctx.profile.data["items"]
                              if row["id"] == note["id"]), "Market alışverişi")
        add.assert_not_called()
        delete.assert_not_called()

    def test_model_unavailable_multi_effect_turn_does_not_replay_raw_planner(self):
        from modules import brain_model_understanding
        original = self.ctx.profile.add_note_item("KORUNACAK")
        with patch.object(brain_model_understanding, "propose", return_value=None), \
             patch.object(self.ctx, "_planner_command", side_effect=AssertionError("raw planner replay"), create=True) as planner, \
             patch.object(self.ctx, "_extra_commands", side_effect=AssertionError("raw cascade replay"), create=True) as cascade, \
             patch.object(self.ctx.profile, "clear_note_items",
                          side_effect=AssertionError("note cleared")) as clear:
            entry, output, _handler, feedback = self.turn_real(
                "İzmir hava durumuna bak: kamerayı aç", model_understanding=True)
        self.assertIsNone(brain_entry.core_plan(entry))
        self.assertIn("işlem başlatmadım", output)
        self.assertEqual(feedback.result_status, "failed")
        self.assertEqual([row["id"] for row in self.ctx.profile.data["items"]],
                         [original["id"]])
        planner.assert_not_called()
        cascade.assert_not_called()
        clear.assert_not_called()
        self.ctx._weather.assert_not_called()
        self.ctx.system_control.open_application.assert_not_called()

    def test_note_mutation_grammar_requires_whole_imperative_not_negative(self):
        from modules.brain_understanding import _note_write_request
        for utterance in ("market notunu silme", "market notunu kaldırma",
                          "market notunu sil demedim", "market notunu siler misin",
                          '"market notunu sil" ne demek?', "market notunu silmeli miyim?"):
            with self.subTest(utterance=utterance):
                self.assertIsNone(_note_write_request(utterance))
        self.assertEqual(_note_write_request("market notunu sil"), ("delete", "market"))
        self.assertEqual(_note_write_request("market notunu düzelt: süt al"), ("update", "market"))

    def test_single_typed_core_failure_is_never_reported_as_handled(self):
        from modules.engine_intents import ActionOutcome
        with patch.object(brain_entry, "apply_model_understanding",
                          side_effect=self.propose("device.share", {"action": "camera"})), \
             patch("modules.engine_intents.dispatch",
                   return_value=ActionOutcome("Kamera açılamadı.", False)) as dispatch, \
             patch.object(self.ctx, "handle",
                          side_effect=AssertionError("raw handler replay")) as fallback:
            entry, output, _handler, feedback = self.turn_real(
                "Kamerayı aç", model_understanding=True)
        self.assertEqual(brain_entry.core_plan(entry),
                         ("share_control", {"action": "camera"}))
        self.assertEqual(output, "Kamera açılamadı.")
        self.assertEqual(feedback.result_status, "failed")
        self.assertEqual(feedback.reason_code, "CORE_ACTION_FAILED")
        dispatch.assert_called_once()
        fallback.assert_not_called()

    def test_single_typed_core_success_preserves_success_feedback(self):
        from modules.engine_intents import ActionOutcome
        with patch.object(brain_entry, "apply_model_understanding",
                          side_effect=self.propose("device.share", {"action": "camera"})), \
             patch("modules.engine_intents.dispatch",
                   return_value=ActionOutcome("Kamera açıldı.", True)) as dispatch:
            _entry, output, _handler, feedback = self.turn_real(
                "Kamerayı aç", model_understanding=True)
        self.assertEqual(output, "Kamera açıldı.")
        self.assertEqual(feedback.result_status, "handled")
        dispatch.assert_called_once()

    def test_document_output_is_not_hidden_by_other_session_artifacts(self):
        from modules.brain_model_understanding import _current_output
        doc = {"slot": "last_doc", "label": "Son rapor"}
        workbench = {"slot": "last_workbench", "label": "Tablo"}
        self.assertEqual(_current_output([doc, workbench])["slot"], "last_doc")
        self.assertTrue(_current_output([doc, workbench])["available"])
        self.assertFalse(_current_output([workbench])["available"])
        self.assertFalse(_current_output([doc, doc])["available"])

    def test_failed_model_negated_note_delete_is_safe_in_real_production_turn(self):
        from modules import brain_model_understanding
        original = self.ctx.profile.add_note_item("KORUNACAK")
        with patch.object(brain_model_understanding, "propose", return_value=None), \
             patch.object(self.ctx.profile, "clear_note_items",
                          side_effect=AssertionError("negative model fallback deleted notes")) as clear:
            entry, output, handler, feedback = self.turn_real(
                "notları silme", model_understanding=True)
        self.assertEqual(
            [row["id"] for row in self.ctx.profile.data["items"]],
            [original["id"]],
        )
        self.assertIsNone(self.ctx._session().pending_confirm)
        clear.assert_not_called()

    def test_failed_model_negated_note_reminder_camera_effects_are_safe(self):
        from modules import brain_model_understanding
        self.ctx.profile.add_note_item("Market alışverişi")
        self.ctx.profile.add_event("İlaç", "2026-11-15T09:00")
        with patch.object(brain_model_understanding, "propose", return_value=None), \
             patch.object(self.ctx.profile, "delete_note_item",
                          side_effect=AssertionError("negated note deleted")) as note_delete, \
             patch.object(self.ctx.profile, "delete_event",
                          side_effect=AssertionError("negated reminder deleted")) as event_delete, \
             patch.object(self.ctx, "set_share",
                          side_effect=AssertionError("quoted camera activated")) as share:
            for utterance in (
                    "son notu silme", "market notunu silme",
                    "ilaç hatırlatmasını silme", "ilaç hatırlatmasını sil demedim",
                    "kamerayı açma", "kamerayı aç demedim",
                    "Ali'ye 'kamerayı aç' mesaj gönder"):
                with self.subTest(utterance=utterance):
                    self.turn_real(utterance, model_understanding=True)
        note_delete.assert_not_called()
        event_delete.assert_not_called()
        share.assert_not_called()
        self.assertEqual(len(self.ctx.profile.data["items"]), 1)
        self.assertEqual(len(self.ctx.profile.data["events"]), 1)

    def test_validated_note_clear_uses_real_bounded_state_confirmation(self):
        old = self.ctx.profile.add_note_item("KORUNACAK")
        with patch.object(brain_entry, "apply_model_understanding",
                          side_effect=self.propose("notes.manage", {"operation": "clear_all"})):
            entry, answer, _handler, feedback = self.turn_real(
                "tüm notları sil", model_understanding=True)
        self.assertIn("onaylıyor musun", answer)
        self.assertEqual(feedback.result_status, "needs_input")
        self.assertEqual(len(self.ctx.profile.data["items"]), 1)
        self.assertEqual(self.ctx._session().pending_confirm["action"], "notes_clear")
        approved, outcome, _, approved_feedback = self.turn_real(
            "evet", model_understanding=True)
        self.assertTrue(approved.state_gate.matched)
        self.assertEqual(approved.state_gate.protocol, "session.pending_confirm.confirm")
        self.assertIn("Tüm notlarını sildim", outcome)
        self.assertEqual(approved_feedback.result_status, "handled")
        self.assertEqual(self.ctx.profile.data["items"], [])
    def test_typed_control_uses_the_existing_single_screen_share_worker(self):
        from modules import brain_core_map, engine_intents
        plan = brain_core_map.core_plan("device.share", {"action": "screen"})
        self.assertEqual(plan, ("share_control", {"action": "screen"}))
        with patch("modules.requests_state.check"), \
             patch.object(self.ctx, "set_share", return_value="PAYLASIM") as worker:
            response = engine_intents.dispatch(
                self.ctx, *plan, "ekranı paylaş", "ekranı paylaş")
        self.assertEqual(response, "PAYLASIM")
        worker.assert_called_once_with("screen")
        self.assertFalse(hasattr(self.ctx, "_user_controls"))
    def test_explicit_quoted_file_ui_keeps_priority_over_core(self):
        ui = '"C:\\Temp\\report.docx" özetle'
        self.assertIsNotNone(self.ctx._FILE_CMD.match(ui))
        with patch.object(self.ctx, "_file_command", return_value="DOSYA UI") as file_gate:
            claimed = brain_precedence.claim(self.ctx, ui, ("notes_read", {"which": "all"}))
        self.assertEqual(claimed, ("file_command", "DOSYA UI"))
        file_gate.assert_called_once_with(ui)


if __name__ == "__main__":
    unittest.main()
