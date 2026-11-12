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

    def test_without_core_plan_exact_legacy_notes_delete_remains_supported(self):
        self.ctx.profile.add_note_item("Not")
        # BRAIN-03 does not silently remove an unmigrated feature.
        reply = self.ctx._planner_command("notları sil", "notları sil")
        self.assertIn("Tüm notlarını sildim", reply)
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
