"""List-position regressions through real prepare/model decoder/Core/note effect.

Only the external model transport is replaced; Profile IDs deliberately differ
from the numbers shown by the note list.
"""
from provider_fixture import routed_plan
import json
from unittest.mock import patch

import test_engine_modular  # noqa: F401 (headless engine dependencies)
from test_brain_pr3_raw_text_authority import _CanonicalAuthorityHarness
from test_brain_primary_understanding import action, envelope
from modules import brain_entry, tasks


class NotePositionProductionTests(_CanonicalAuthorityHarness):
    def setUp(self):
        super().setUp()
        tasks.add(self.ctx.profile, "Not olmayan kayıt")
        self.first = self.ctx.profile.add_note_item("Market listesi")
        self.second = self.ctx.profile.add_note_item("Toplantı ayrıntıları")

    def model_turn(self, text, *, operation="direct_action", unavailable=False):
        offered = []
        raw = envelope(operation=operation, confidence="HIGH", actions=[] if operation == "chat" else [
            action(capability_id="notes.write", arguments={"operation": "delete"}, reference_slots=["note_0"]),
        ])

        def transport(request, spec, prompt, system, **kwargs):
            prompt = prompt + "\\n" + system
            offered.extend(json.loads(prompt.split("\\n", 1)[0])["note_candidates"])
            if unavailable:
                raise TimeoutError("offline model")
            return raw

        with patch("modules.llm.current_user", return_value=self.owner), \
             patch("modules.llm.provider", return_value="groq"), \
             patch("modules.llm.privacy.mode", return_value="normal"), \
             patch("modules.smart_router.selection", return_value={"candidates": ["groq"]}), \
             routed_plan(count=1), patch("modules.llm.dispatch", side_effect=transport), \
             patch.object(self.ctx, "_extra_commands", create=True,
                          side_effect=AssertionError("raw note fallback")):
            entry, result, _, _ = self.turn_real(text, model_understanding=True)
        return entry, result, offered

    def test_second_and_last_note_delete_uses_displayed_position_despite_id_collision(self):
        self.assertEqual(self.first["id"], 2)
        self.assertNotEqual(self.second["id"], 2)
        for text in ("2 numaralı notu sil", "2 numarali notu sil", "2. notu sil",
                     "ikinci notu sil", "İkinci notu sil", "son notu sil"):
            with self.subTest(text=text):
                self.ctx.profile.data["items"] = [self.first, self.second]
                self.ctx.profile.save()
                entry, result, offered = self.model_turn(text)
                self.assertEqual([row["preview"] for row in offered], [self.second["text"]])
                self.assertEqual(brain_entry.core_plan(entry)[1]["id"], str(self.second["id"]))
                self.assertIn("Notu sildim", result)
                self.assertEqual(self.ctx.profile.data["items"], [self.first])

    def test_explicit_persistent_id_remains_distinct_from_displayed_position(self):
        for text in ("#2 notunu sil", "id: 2 notunu sil"):
            with self.subTest(text=text):
                self.ctx.profile.data["items"] = [self.first, self.second]
                self.ctx.profile.save()
                _, result, offered = self.model_turn(text)
                self.assertEqual([row["preview"] for row in offered], [self.first["text"]])
                self.assertIn("Notu sildim", result)
                self.assertEqual(self.ctx.profile.data["items"], [self.second])

    def test_unknown_and_ambiguous_positions_cannot_delete_a_coincident_id(self):
        self.ctx.profile.data["items"] = [self.first]
        for text in ("2 numaralı notu sil", "0. notu sil", "ilk notu ve ikinci notu sil"):
            with self.subTest(text=text):
                _, _, offered = self.model_turn(text)
                self.assertEqual(offered, [])
                self.assertEqual(self.ctx.profile.data["items"], [self.first])

    def test_last_note_outside_bounded_inventory_is_not_guessed(self):
        for index in range(45):
            self.ctx.profile.add_note_item(f"Ek kayıt {index}")
        before = list(self.ctx.profile.data["items"])
        _, _, offered = self.model_turn("son notu sil")
        self.assertEqual(offered, [])
        self.assertEqual(self.ctx.profile.data["items"], before)

    def test_resolved_position_is_not_effect_authority_for_chat_or_model_outage(self):
        before = list(self.ctx.profile.data["items"])
        for options in ({"operation": "chat"}, {"unavailable": True}):
            with self.subTest(options=options):
                self.model_turn("ikinci notu silme", **options)
                self.assertEqual(self.ctx.profile.data["items"], before)
