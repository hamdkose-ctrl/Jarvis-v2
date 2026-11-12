"""BRAIN-03: a Core-validated reminder is not raw text for the legacy note planner.

The Core plan is a completed authority decision. These tests use the real
brain_precedence entry and (in the second class) prepare -> handoff -> EngineContext
with temporary owner state and mocked external effects.
"""
from __future__ import annotations

from dataclasses import replace
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_brain_pr3_raw_text_authority as pr3a
from modules import brain_entry, brain_precedence, main_planner
from modules.brain_contracts import RequestKind


class ReminderGateTests(unittest.TestCase):
    def setUp(self):
        self.runtime = SimpleNamespace(
            _tr_lower=lambda command: command.casefold(),
            _file_command=Mock(return_value=None),
            _user_controls=Mock(return_value=None),
            _planner_command=Mock(side_effect=AssertionError(
                "Core-validated reminder must never enter the raw planner")),
            _macro_run=Mock(return_value=None),
            _extra_commands=Mock(return_value=None),
        )
        self.args = {"title": "notları sil", "when": "2026-11-13T09:00", "repeat": None}

    def test_reminder_plan_uses_typed_executor_not_raw_planner(self):
        command = "Yarın bana 'notları sil' ifadesini hatırlat"
        with patch.object(main_planner, "reminder_core", return_value="HATIRLATMA") as core:
            claimed = brain_precedence.claim(self.runtime, command, ("reminder", self.args))
        self.assertEqual(claimed, ("planner_command", "HATIRLATMA"))
        core.assert_called_once_with(self.runtime, self.args, command, command.casefold())
        self.runtime._planner_command.assert_not_called()
        self.runtime._extra_commands.assert_not_called()

    def test_a_legacy_unplanned_reminder_keeps_its_existing_owner(self):
        self.runtime._planner_command = Mock(return_value="MEVCUT PLANLAYICI")
        text = "yarın bana ilaç almayı hatırlat"
        claimed = brain_precedence.claim(self.runtime, text, None)
        self.assertEqual(claimed, ("planner_command", "MEVCUT PLANLAYICI"))
        self.runtime._planner_command.assert_called_once_with(text, text)

    def test_typed_executor_exception_never_falls_back_to_raw_planner(self):
        text = "yarın bana notları sil diye hatırlat"
        with patch.object(main_planner, "reminder_core", side_effect=RuntimeError("disk failed")):
            with self.assertRaisesRegex(RuntimeError, "disk failed"):
                brain_precedence.claim(self.runtime, text, ("reminder", self.args))
        self.runtime._planner_command.assert_not_called()
        self.runtime._extra_commands.assert_not_called()


class ReminderCanonicalProductionTests(pr3a._CanonicalAuthorityHarness):
    """Real prepare -> handoff -> engine entry; no real user files or provider."""

    def _adopt_reminder(self, title: str):
        def adopt(semantic, text, *, active_context=None):
            return replace(
                semantic,
                request_kind=RequestKind.CAPABILITY,
                capability_hint="reminder.propose",
                arguments={"reminder": {
                    "title": title, "when": "2026-11-13T09:00", "repeat": None,
                }},
                ambiguities=(), needs_input=False,
            )
        return adopt

    def test_quoted_bulk_note_command_is_reminder_text_not_note_deletion(self):
        command = "Yarın bana 'notları sil' ifadesini hatırlat"
        with patch.object(brain_entry, "apply_model_understanding",
                          side_effect=self._adopt_reminder("notları sil")), \
             patch.object(self.ctx, "_planner_command",
                          side_effect=AssertionError("raw planner reinterpreted Core plan")) as raw, \
             patch.object(self.ctx.profile, "clear_note_items",
                          side_effect=AssertionError("notes were cleared")) as cleared, \
             patch.object(main_planner, "_reminder_or_confirm", return_value="HATIRLATMA") as create:
            entry, result, _handler, feedback = self.turn_real(
                command, model_understanding=True,
            )
        self.assertEqual(entry.understanding.capability_hint, "reminder.propose")
        self.assertEqual(result, "HATIRLATMA")
        self.assertEqual(feedback.result_status, "handled")
        create.assert_called_once_with(self.ctx, "notları sil", "2026-11-13T09:00")
        raw.assert_not_called()
        cleared.assert_not_called()

    def test_quoted_single_note_delete_is_reminder_text_not_note_deletion(self):
        command = "Yarın bana '3 numaralı notu sil' diye hatırlat"
        with patch.object(brain_entry, "apply_model_understanding",
                          side_effect=self._adopt_reminder("3 numaralı notu sil")), \
             patch.object(self.ctx, "_planner_command",
                          side_effect=AssertionError("raw planner reinterpreted Core plan")) as raw, \
             patch.object(self.ctx.profile, "delete_note_item",
                          side_effect=AssertionError("note deleted")) as deleted, \
             patch.object(main_planner, "_reminder_or_confirm", return_value="HATIRLATMA") as create:
            _entry, result, _handler, _feedback = self.turn_real(
                command, model_understanding=True,
            )
        self.assertEqual(result, "HATIRLATMA")
        create.assert_called_once_with(self.ctx, "3 numaralı notu sil", "2026-11-13T09:00")
        raw.assert_not_called()
        deleted.assert_not_called()


if __name__ == "__main__":
    unittest.main()
