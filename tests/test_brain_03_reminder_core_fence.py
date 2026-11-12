"""BRAIN-03: a Core-validated reminder title cannot authorize note mutations.

The unchanged legacy planner order still handles exact note-add syntax and
non-reminder calendar/pending operations. Only the destructive raw note paths
are fenced when Core has already validated a reminder plan.
"""
from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

import test_brain_pr3_raw_text_authority as pr3a
from modules import brain_entry, main_planner
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
             patch.object(self.ctx, "_note_fix",
                          side_effect=AssertionError("raw note correction")) as fix, \
             patch.object(main_planner, "_edit_reminder",
                          side_effect=AssertionError("raw reminder edit")) as edit, \
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
            fix.assert_not_called()
            edit.assert_not_called()

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

    def test_unplanned_legacy_sharing_still_uses_its_existing_owner(self):
        with patch.object(self.ctx, "set_share", return_value="PAYLASIM ACILDI") as share:
            reply = self.ctx._user_controls("ekranı paylaş", "ekranı paylaş")
            self.assertEqual(reply, "PAYLASIM ACILDI")
            share.assert_called_once_with("screen")

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

    def test_unplanned_legacy_reminder_delete_keeps_existing_behavior(self):
        self.ctx.profile.add_event("İlaç", "2026-11-15T09:00")
        reply = self.ctx._planner_command(
            "ilaç hatırlatmasını sil", "ilaç hatırlatmasını sil",
        )
        self.assertIn("Sildim: İlaç", reply)
        self.assertEqual(self.ctx.profile.data["events"], [])

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

    def test_without_core_plan_exact_legacy_notes_delete_requires_confirmation(self):
        from modules import main_planner
        self.ctx.profile.add_note_item("Not")
        # No model path still recognizes the exact user request, but bulk
        # deletion cannot execute before a bounded State approval.
        reply = self.ctx._planner_command("notları sil", "notları sil")
        self.assertIn("onaylıyor musun", reply)
        self.assertEqual(len(self.ctx.profile.data["items"]), 1)
        approval = self.ctx._session().pending_confirm
        self.assertEqual(approval["owner"], self.owner)
        self.assertEqual(approval["action"], "notes_clear")
        self.assertIn("Tüm notlarını sildim",
                      main_planner.clear_notes_confirmed(self.ctx, approval))
        self.assertEqual(self.ctx.profile.data["items"], [])

    def test_explicit_note_add_still_precedes_reminder_until_parity_cutover(self):
        # This is an existing contracted exception, not a new note classifier.
        with patch.object(brain_entry, "apply_model_understanding",
                          side_effect=self._model_reminder("ilaç")):
            entry, reply, _handler, _feedback = self.turn_real(
                "not al: yarın 9'da ilaç hatırlat", model_understanding=True,
            )
        self.assertEqual(entry.understanding.capability_hint, "reminder.propose")
        self.assertTrue(reply.startswith("Not aldım"), reply)
        self.assertEqual(self.ctx.profile.data["events"], [])


if __name__ == "__main__":
    unittest.main()
