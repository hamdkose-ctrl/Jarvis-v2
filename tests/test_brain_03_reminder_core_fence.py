"""BRAIN-03: a Core-validated reminder title cannot authorize note mutations.

All raw reminder/note mutation selectors have been retired. A Core plan is
the sole writer; a quoted reminder title can never become another effect.
"""
from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

import test_brain_pr3_raw_text_authority as pr3a
from modules import brain_entry, brain_core_map, brain_model_understanding, engine_intents, main_planner
from modules.brain_contracts import RequestKind


class ReminderNoteMutationFenceTests(pr3a._CanonicalAuthorityHarness):
    def _model_reminder(self, title: str):
        def adopt(semantic, text, *, active_context=None):
            return replace(
                semantic, request_kind=RequestKind.CAPABILITY,
                capability_hint="reminder.propose",
                arguments={"reminder": {
                    "title": title, "when": "2026-11-13T09:00", "repeat": None,
                }},
                ambiguities=(), needs_input=False,
            )
        return adopt

    def _verified_reminder(self, command: str, title: str):
        # If a second raw note owner mutates data, fail at the effect boundary.
        with patch.object(brain_entry, "apply_model_understanding",
                          side_effect=self._model_reminder(title)), \
             patch.object(self.ctx.profile, "clear_note_items",
                          side_effect=AssertionError("bulk notes cleared")) as bulk, \
             patch.object(self.ctx.profile, "delete_note_item",
                          side_effect=AssertionError("note deleted")) as delete, \
             patch.object(main_planner, "_reminder_or_confirm",
                          return_value="HATIRLATMA OLUSTURULDU") as create:
            entry, result, _handler, feedback = self.turn_real(
                command, model_understanding=True,
            )
            self.assertEqual(entry.understanding.capability_hint, "reminder.propose")
            self.assertEqual(result, "HATIRLATMA OLUSTURULDU")
            self.assertEqual(feedback.result_status, "handled")
            create.assert_called_once_with(self.ctx, title, "2026-11-13T09:00")
            bulk.assert_not_called()
            delete.assert_not_called()
            self.assertFalse(hasattr(self.ctx, "_note_fix"))
            self.assertFalse(hasattr(self.ctx, "_planner_command"))
            self.assertFalse(hasattr(main_planner, "_edit_reminder"))

    def test_quoted_bulk_delete_is_only_reminder_title(self):
        self.ctx.profile.add_note_item("Hassas not")
        self._verified_reminder(
            "Yarın bana 'notları sil' ifadesini hatırlat", "notları sil",
        )
        self.assertEqual(len(self.ctx.profile.data["items"]), 1)

    def test_quoted_cleanup_phrase_is_only_reminder_title(self):
        self.ctx.profile.add_note_item("Hassas not")
        self._verified_reminder(
            "Yarın sabah 'notları temizle' diye hatırlat", "notları temizle",
        )
        self.assertEqual(len(self.ctx.profile.data["items"]), 1)

    def test_quoted_numbered_delete_is_only_reminder_title(self):
        self.ctx.profile.add_note_item("Hassas not")
        self._verified_reminder(
            "Yarın bana '3 numaralı notu sil' diye hatırlat", "3 numaralı notu sil",
        )
        self.assertEqual(len(self.ctx.profile.data["items"]), 1)

    def test_typed_plan_must_not_run_named_note_mutation(self):
        self.ctx.profile.add_note_item("Hassas not")
        self._verified_reminder(
            "Yarın bana 'market notunu düzelt' diye hatırlat", "market notunu düzelt",
        )
        self.assertEqual(len(self.ctx.profile.data["items"]), 1)


    def test_typed_reminder_quote_cannot_start_screen_sharing(self):
        # A quoted title is data, never a second instruction to capture screen.
        with patch.object(self.ctx, "set_share",
                          side_effect=AssertionError("screen share changed")) as share:
            self._verified_reminder(
                "Yarın bana 'ekranı paylaş' sözünü hatırlat", "ekranı paylaş",
            )
            share.assert_not_called()

    def test_typed_reminder_quote_cannot_open_camera(self):
        with patch.object(self.ctx, "set_share",
                          side_effect=AssertionError("camera changed")) as share:
            self._verified_reminder(
                "Yarın bana 'kamerayı aç' cümlesini hatırlat", "kamerayı aç",
            )
            share.assert_not_called()

    def test_typed_reminder_quote_cannot_start_voice_selection(self):
        self.assertIsNone(self.ctx._session().pending_voice)
        self._verified_reminder(
            "Yarın bana 'sesimi değiştir' demeyi hatırlat", "sesimi değiştir",
        )
        self.assertIsNone(self.ctx._session().pending_voice)

    def test_typed_screen_sharing_uses_the_existing_single_worker(self):
        plan = brain_core_map.core_plan("device.share", {"action": "screen"})
        self.assertEqual(plan, ("share_control", {"action": "screen"}))
        with patch.object(self.ctx, "set_share", return_value="PAYLASIM ACILDI") as share, \
             patch("modules.requests_state.check"):
            reply = engine_intents.dispatch(self.ctx, *plan, "ekranı paylaş", "ekranı paylaş")
        self.assertEqual(reply, "PAYLASIM ACILDI")
        share.assert_called_once_with("screen")
        self.assertFalse(hasattr(self.ctx, "_user_controls"))

    def test_typed_reminder_quote_cannot_start_previous_table_followup(self):
        # The early file gate must not run workbench.followup on title data.
        with patch.object(self.ctx, "_file_command",
                          side_effect=AssertionError("previous table regenerated")) as raw:
            self._verified_reminder(
                "Yarın bana 'tabloyu Word'de ver' sözünü hatırlat",
                "tabloyu Word'de ver",
            )
        raw.assert_not_called()

    def test_typed_reminder_exception_cannot_start_note_delete(self):
        self.ctx.profile.add_note_item("Hassas not")
        command = "Yarın bana 'notları sil' diye hatırlat"
        with patch.object(brain_entry, "apply_model_understanding",
                          side_effect=self._model_reminder("notları sil")), \
             patch.object(self.ctx.profile, "clear_note_items",
                          side_effect=AssertionError("bulk notes cleared")) as clear, \
             patch.object(main_planner, "_reminder_or_confirm",
                          side_effect=RuntimeError("storage failed")):
            with self.assertRaisesRegex(RuntimeError, "storage failed"):
                self.turn_real(command, model_understanding=True)
            clear.assert_not_called()
        self.assertEqual(len(self.ctx.profile.data["items"]), 1)

    def test_typed_creation_title_cannot_delete_existing_reminder(self):
        self.ctx.profile.add_event("İlaç", "2026-11-15T09:00")
        before = [(e["id"], e["when"]) for e in self.ctx.profile.data["events"]]
        self._verified_reminder(
            "Yarın bana 'ilaç hatırlatmasını sil' ifadesini hatırlat",
            "ilaç hatırlatmasını sil",
        )
        self.assertEqual([(e["id"], e["when"]) for e in self.ctx.profile.data["events"]], before)

    def test_typed_creation_title_cannot_reschedule_existing_reminder(self):
        self.ctx.profile.add_event("Toplantı", "2026-11-15T09:00")
        before = [(e["id"], e["when"]) for e in self.ctx.profile.data["events"]]
        self._verified_reminder(
            "Yarın 'toplantıyı 10 dakika ertele' cümlesini hatırlat",
            "toplantıyı 10 dakika ertele",
        )
        self.assertEqual([(e["id"], e["when"]) for e in self.ctx.profile.data["events"]], before)

    def test_typed_creation_does_not_need_legacy_reminder_keyword(self):
        self._verified_reminder(
            "Yarın saat dokuzda kahve almayı bana anımsat",
            "Kahve al",
        )

    def test_canonical_reminder_date_question_survives_incomplete_answer(self):
        self.ctx._session().pending_event_title = "Su iç"
        with patch.object(brain_entry, "pending_answer_owned", return_value=True), \
             patch.object(brain_entry, "matched_protocol", return_value=False), \
             patch.object(self.ctx.whenmod, "parse_when", return_value=(None, "")), \
             patch.object(main_planner, "_reminder_or_confirm",
                          side_effect=AssertionError("wrote without a date")) as write:
            response = main_planner.continue_pending_event_title(
                self.ctx, "biraz sonra", "biraz sonra")
        self.assertIn("tarih ve saati anlayamadım", response)
        self.assertEqual(self.ctx._session().pending_event_title, "Su iç")
        write.assert_not_called()
        with patch.object(brain_entry, "pending_answer_owned", return_value=True), \
             patch.object(brain_entry, "matched_protocol", return_value=False), \
             patch.object(self.ctx.whenmod, "parse_when",
                          return_value=("2026-11-14T10:00", "")), \
             patch.object(main_planner, "_reminder_or_confirm",
                          return_value="HATIRLATMA EKLENDI") as write:
            response = main_planner.continue_pending_event_title(
                self.ctx, "yarın 10'da", "yarın 10'da")
        self.assertEqual(response, "HATIRLATMA EKLENDI")
        self.assertIsNone(self.ctx._session().pending_event_title)
        write.assert_called_once_with(self.ctx, "Su iç", "2026-11-14T10:00")

    def test_canonical_reminder_conflict_confirmation_is_not_lost_on_unclear_reply(self):
        original = {"confirm": ("Su iç", "2026-11-14T10:00", None)}
        self.ctx._session().pending_event_title = original
        with patch.object(brain_entry, "pending_answer_owned", return_value=True), \
             patch.object(brain_entry, "matched_protocol", return_value=False), \
             patch("modules.confirmation.decision", return_value=None), \
             patch.object(main_planner, "_save_reminder",
                          side_effect=AssertionError("saved without approval")) as write:
            response = main_planner.continue_pending_event_title(
                self.ctx, "anlamadım", "anlamadım")
        self.assertIn("Evet veya hayır", response)
        self.assertEqual(self.ctx._session().pending_event_title, original)
        write.assert_not_called()
        with patch.object(brain_entry, "pending_answer_owned", return_value=True), \
             patch.object(brain_entry, "matched_protocol", return_value=False), \
             patch("modules.confirmation.decision", return_value=True), \
             patch.object(main_planner, "_save_reminder", return_value="KAYDEDILDI") as write:
            response = main_planner.continue_pending_event_title(
                self.ctx, "evet", "evet")
        self.assertEqual(response, "KAYDEDILDI")
        self.assertIsNone(self.ctx._session().pending_event_title)
        write.assert_called_once_with(self.ctx, "Su iç", "2026-11-14T10:00", None)

    def test_model_outage_cannot_delete_existing_reminder_via_legacy_nlp(self):
        self.ctx.profile.add_event("İlaç", "2026-11-15T09:00")
        before = [dict(row) for row in self.ctx.profile.data["events"]]
        with patch.object(brain_model_understanding, "propose", return_value=None):
            _entry, reply, _handler, feedback = self.turn_real(
                "ilaç hatırlatmasını sil", model_understanding=True)
        self.assertEqual(feedback.result_status, "failed")
        self.assertIn("model", reply.casefold())
        self.assertEqual(self.ctx.profile.data["events"], before)
        self.assertFalse(hasattr(self.ctx, "_planner_command"))

    def test_direct_core_reminder_dispatch_does_not_reclassify_raw_edit(self):
        self.ctx.profile.add_event("İlaç", "2026-11-15T09:00")
        with patch.object(main_planner, "_reminder_or_confirm",
                          return_value="HATIRLATMA OLUSTURULDU") as create:
            reply = main_planner.reminder_core(
                self.ctx,
                {"title": "ilaç hatırlatmasını sil", "when": "2026-11-13T09:00", "repeat": None},
                "ilaç hatırlatmasını sil", "ilaç hatırlatmasını sil",
            )
            self.assertEqual(reply, "HATIRLATMA OLUSTURULDU")
            create.assert_called_once_with(self.ctx, "ilaç hatırlatmasını sil", "2026-11-13T09:00")
        self.assertEqual(len(self.ctx.profile.data["events"]), 1)

    def test_typed_notes_clear_requires_snapshot_bound_confirmation(self):
        self.ctx.profile.add_note_item("Not")
        def choose_clear(current, _text, *, active_context=None):
            return replace(current, request_kind=RequestKind.CAPABILITY,
                           capability_hint="notes.manage", arguments={"operation": "clear_all"},
                           ambiguities=(), needs_input=False)
        with patch.object(brain_entry, "apply_model_understanding", side_effect=choose_clear):
            _entry, reply, _handler, feedback = self.turn_real(
                "notları sil", model_understanding=True)
        self.assertIn("onaylıyor musun", reply)
        self.assertEqual(feedback.result_status, "needs_input")
        self.assertEqual(len(self.ctx.profile.data["items"]), 1)
        approval = self.ctx._session().pending_confirm
        self.assertEqual(approval["owner"], self.owner)
        self.assertEqual(approval["action"], "notes_clear")
        self.assertIn("Tüm notlarını sildim",
                      main_planner.clear_notes_confirmed(self.ctx, approval))
        self.assertEqual(self.ctx.profile.data["items"], [])

    def test_model_selected_note_add_does_not_create_a_second_reminder(self):
        def choose_note(current, _text, *, active_context=None):
            return replace(current, request_kind=RequestKind.CAPABILITY,
                           capability_hint="notes.add",
                           arguments={"text": "yarın 9'da ilaç hatırlat"},
                           ambiguities=(), needs_input=False)
        with patch.object(brain_entry, "apply_model_understanding", side_effect=choose_note), \
             patch.object(main_planner, "_reminder_or_confirm",
                          side_effect=AssertionError("second reminder write")) as remind:
            entry, reply, _handler, feedback = self.turn_real(
                "not al: yarın 9'da ilaç hatırlat", model_understanding=True)
        self.assertEqual(entry.understanding.capability_hint, "notes.add")
        self.assertEqual(reply, "Not aldım: yarın 9'da ilaç hatırlat")
        self.assertEqual(feedback.result_status, "handled")
        self.assertEqual(self.ctx.profile.data["events"], [])
        remind.assert_not_called()


if __name__ == "__main__":
    unittest.main()
