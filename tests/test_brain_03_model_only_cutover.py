"""BRAIN-03 final cutover: real canonical turns never promote raw NLP effects.

External model and hardware are replaced by deterministic boundary stubs.
These tests are not evidence of live-model or Windows PC acceptance.
"""
from __future__ import annotations

from dataclasses import replace
from unittest.mock import Mock, patch

import test_brain_pr3_raw_text_authority as baseline
from modules import brain_entry, brain_core_map, brain_model_understanding
from modules.brain_contracts import RequestKind


class ModelOnlyCutoverTests(baseline._CanonicalAuthorityHarness):
    def _outage(self, utterance):
        with patch.object(brain_model_understanding, "propose", return_value=None), \
             patch.object(self.ctx, "_add_note",
                          side_effect=AssertionError("legacy note writer was called")) as note, \
             patch.object(self.ctx, "_weather",
                          side_effect=AssertionError("partial weather effect was called")) as weather, \
             patch.object(self.ctx, "set_share",
                          side_effect=AssertionError("camera effect was called")) as share:
            entry, output, handler, feedback = self.turn_real(
                utterance, model_understanding=True)
        self.assertIn("MODEL_UNAVAILABLE", entry.understanding.reason_codes)
        self.assertEqual(feedback.result_status, "failed")
        self.assertIn("model", str(output).casefold())
        self.assertFalse(hasattr(self.ctx, "_planner_command"))
        self.assertFalse(hasattr(self.ctx, "_extra_commands"))
        self.assertFalse(hasattr(self.ctx, "_user_controls"))
        note.assert_not_called()
        weather.assert_not_called()
        share.assert_not_called()
        return entry, output

    def test_model_outage_keeps_explicit_pc_and_workflow_but_not_questions(self):
        from modules import brain_precedence
        from modules import brain_model_understanding
        self.assertTrue(brain_precedence.explicit_workflow_owner_protocol(
            "görev akışı kod: test sonucunu denetle"))
        for phrase in ("görev akışı nedir?", "görev akışı nasıl çalışıyor?",
                       "görev akışı kod nedir?"):
            self.assertFalse(brain_precedence.explicit_workflow_owner_protocol(phrase))
        with patch.object(brain_model_understanding, "propose", return_value=None):
            for command in ("PC görev: hesap makinesini kontrol et",
                            "görev akışı kod: test sonucunu denetle"):
                with self.subTest(command=command):
                    bounded = Mock(return_value="BOUNDED RESULT")
                    entry, out, handler, result = self.turn(
                        command, handler=bounded, model_understanding=True)
                    self.assertIn("MODEL_UNAVAILABLE", entry.understanding.reason_codes)
                    self.assertEqual(out, "BOUNDED RESULT")
                    self.assertEqual(result.reason_code, "EXACT_PROTOCOL_HANDLED")
                    bounded.assert_called_once_with(command)
            for command in ("görev akışı nedir?", "notumu silme"):
                with self.subTest(command=command):
                    forbidden = Mock(side_effect=AssertionError("raw fallback must not run"))
                    entry, out, handler, result = self.turn(
                        command, handler=forbidden, model_understanding=True)
                    self.assertEqual(result.reason_code, "BRAIN_MODEL_UNAVAILABLE")
                    forbidden.assert_not_called()

    def test_production_passes_no_legacy_intent_or_slots_to_primary_model(self):
        seen = []
        def inspect(*, owner, text, current, **kwargs):
            seen.append((owner, text, current))
            return None
        with patch.object(brain_model_understanding, "propose", side_effect=inspect):
            self.turn_real(
                "İzmir hava durumuna bak: kamerayı aç", model_understanding=True)
        self.assertEqual(len(seen), 1)
        owner, text, candidate = seen[0]
        self.assertEqual(owner, self.owner)
        self.assertEqual(text, "İzmir hava durumuna bak: kamerayı aç")
        self.assertIsNone(candidate.capability_hint)
        self.assertEqual(dict(candidate.arguments), {"original_text": text})
        self.assertFalse(candidate.actions)
        self.assertFalse(candidate.ambiguities)
        self.assertFalse(candidate.pending_owner)

    def test_explicit_engine_fast_controls_reject_negation_and_questions(self):
        from modules.command_manager import engine_control
        close, sleep = Mock(return_value="CLOSED"), Mock(return_value="SLEEP")
        for utterance in ("kendini kapatma", "kendini kapat?", "jarvis'i kapatma",
                          "uyku moduna geçme", "uyku moduna geç?", "uyu?"):
            with self.subTest(utterance=utterance):
                self.assertIsNone(engine_control(
                    utterance, source="yazı", sleeping=False, close=close,
                    set_sleep=sleep))
        close.assert_not_called()
        sleep.assert_not_called()
        self.assertEqual(engine_control(
            "kendini kapat", source="yazı", sleeping=False, close=close,
            set_sleep=sleep), "CLOSED")
        self.assertEqual(engine_control(
            "uyku moduna geç", source="yazı", sleeping=False, close=close,
            set_sleep=sleep), "SLEEP")
        close.assert_called_once_with()
        sleep.assert_called_once_with(True, announce=False)

    def test_fast_state_core_is_available_without_general_semantic_model(self):
        # A precise fast lane is NOT a semantic fallback. The real Core worker
        # still owns the action even when the general model cannot answer.
        with patch.object(self.ctx.files, "undo_organize", return_value=2) as undo, \
             patch.object(brain_model_understanding, "propose",
                          side_effect=AssertionError("Fast Gate queried the model")):
            entry, output, _handler, feedback = self.turn_real(
                "düzenlemeyi geri al", model_understanding=True)
        self.assertEqual(entry.stage, "fast")
        self.assertEqual(output, "2 dosyayı eski yerine taşıdım.")
        self.assertEqual(feedback.result_status, "handled")
        undo.assert_called_once_with(self.owner)

    def test_negative_note_cannot_mutate_with_model_unavailable(self):
        saved = self.ctx.profile.add_note_item("Market alışverişi")
        before = [(n["id"], n["text"]) for n in self.ctx.profile.data["items"]]
        self._outage("market notunu düzeltme: süt al")
        after = [(n["id"], n["text"]) for n in self.ctx.profile.data["items"]]
        self.assertEqual(before, after)
        self.assertTrue(any(n["id"] == saved["id"] for n in self.ctx.profile.data["items"]))

    def test_model_unavailable_never_collapses_multiple_actions_to_weather(self):
        self._outage("İzmir hava durumuna bak: kamerayı aç")
        self._outage("önce hava nasıl sonra sesi 50 yap")

    def test_quoted_or_conditional_effect_does_not_run_without_model(self):
        self._outage('Biri "ekrandaki hatayı not al" derse ne olur?')
        self._outage("Notu silme; yalnız bunun ne anlama geldiğini anlat.")

    def test_validated_model_chat_cannot_be_reclassified_as_note_action(self):
        self.ctx.profile.add_note_item("Market alışverişi")
        original = [dict(n) for n in self.ctx.profile.data["items"]]
        def decide_chat(current, text, *, active_context=None):
            return replace(
                current, request_kind=RequestKind.CHAT, capability_hint=None,
                arguments={"original_text": text}, actions=(),
                ambiguities=(), needs_input=False,
                reason_codes=current.reason_codes + ("MODEL_CHAT_DECIDED",),
            )
        with patch.object(brain_entry, "apply_model_understanding", side_effect=decide_chat), \
             patch.object(self.ctx, "handle", wraps=self.ctx.handle) as raw_handler:
            entry, output, handler, feedback = self.turn_real(
                "market notunu düzeltme: süt al", model_understanding=True)
        self.assertIn("MODEL_DECIDED", entry.understanding.reason_codes)
        self.assertEqual(self.ctx.profile.data["items"], original)
        raw_handler.assert_not_called()

    def _proposed_note_turn(self, utterance, *, operation, replacement=None,
                            selected_slot="note_0"):
        from test_brain_primary_understanding import envelope
        item = {"action_id": "a1", "capability_id": "notes.write",
                "arguments": {"operation": operation},
                "reference_slots": [selected_slot], "depends_on": []}
        if replacement is not None:
            item["arguments"]["text"] = replacement
            item["argument_sources"] = {"text": replacement}
        raw = envelope(actions=[item])
        with patch("modules.llm.current_user", return_value=self.owner), \
             patch("modules.llm.provider", return_value="groq"), \
             patch("modules.llm.privacy.mode", return_value="normal"), \
             patch("modules.smart_router.selection",
                   return_value={"candidates": ["groq"]}), \
             patch("modules.smart_router.run", return_value=raw):
            # turn_real returns an ordinary bound method, not a Mock. Keep
            # the real handler available but spy on it so tests can assert the
            # accepted Core note path did not re-enter raw NLP.
            raw_handler = Mock(wraps=self.ctx.handle)
            return self.turn(utterance, handler=raw_handler, model_understanding=True)

    def test_primary_model_updates_one_observed_note_via_core_not_raw_lookup(self):
        original = self.ctx.profile.add_note_item("market listesi süt")
        other = self.ctx.profile.add_note_item("kitap listesi")
        entry, output, handler, feedback = self._proposed_note_turn(
            "market notunu düzelt: süt ve ekmek",
            operation="update", replacement="süt ve ekmek")
        self.assertEqual(entry.understanding.capability_hint, "notes.write")
        self.assertEqual(feedback.result_status, "handled")
        self.assertEqual(entry.understanding.arguments["notes"]["id"],
                         str(original["id"]))
        self.assertEqual(original["text"], "süt ve ekmek")
        self.assertEqual(other["text"], "kitap listesi")
        self.assertIn("Düzelttim", output)
        self.assertFalse(handler.called)

    def test_primary_model_deletes_only_exact_resolved_note(self):
        original = self.ctx.profile.add_note_item("market listesi süt")
        other = self.ctx.profile.add_note_item("kitap listesi")
        entry, output, handler, feedback = self._proposed_note_turn(
            "market notunu sil", operation="delete")
        self.assertEqual(feedback.result_status, "handled")
        self.assertIn("Notu sildim", output)
        self.assertEqual([note["id"] for note in self.ctx.profile.data["items"]],
                         [other["id"]])
        self.assertFalse(handler.called)

    def test_note_edit_refuses_a_changed_snapshot_before_the_core_effect(self):
        from modules import engine_intents, main_planner
        note = self.ctx.profile.add_note_item("market listesi süt")
        observed = main_planner.note_snapshot_digest(note)
        self.assertEqual(len(observed), 64)
        note["text"] = "yeni içerik"
        self.ctx.profile.save()
        with patch("modules.requests_state.check"):
            outcome = engine_intents.dispatch(
                self.ctx, "notes_write", {
                    "operation": "delete", "id": str(note["id"]),
                    "expected_note_digest": observed,
                }, "market notunu sil", "market notunu sil")
        self.assertEqual(getattr(outcome, "ok", None), False)
        self.assertIn("değişti", outcome)
        self.assertEqual(self.ctx.profile.data["items"][0]["text"], "yeni içerik")

    def test_note_core_worker_rejects_missing_snapshot_or_forged_target(self):
        from modules import engine_intents, main_planner
        note = self.ctx.profile.add_note_item("market listesi süt")
        snapshot = main_planner.note_snapshot_digest(note)
        with patch("modules.requests_state.check"):
            for attempt in (
                {"operation": "delete", "id": str(note["id"])},
                {"operation": "delete", "id": "999999",
                 "expected_note_digest": snapshot},
                {"operation": "update", "id": str(note["id"]),
                 "expected_note_digest": "0" * 64, "text": "yanlış"},
            ):
                with self.subTest(attempt=attempt):
                    outcome = engine_intents.dispatch(
                        self.ctx, "notes_write", attempt,
                        "market notunu sil", "market notunu sil")
                    self.assertFalse(outcome.ok)
        self.assertEqual(len(self.ctx.profile.data["items"]), 1)
        self.assertEqual(note["text"], "market listesi süt")

    def test_ambiguous_or_forged_note_slot_never_mutates(self):
        first = self.ctx.profile.add_note_item("market listesi süt")
        second = self.ctx.profile.add_note_item("market listesi ekmek")
        before = [dict(n) for n in self.ctx.profile.data["items"]]
        for slot in ("note_0", "note_7"):
            with self.subTest(slot=slot):
                entry, response, _handler, feedback = self._proposed_note_turn(
                    "market notunu sil", operation="delete", selected_slot=slot)
                self.assertEqual(feedback.result_status, "failed")
                self.assertIn("MODEL_PROPOSAL_REJECTED", entry.understanding.reason_codes)
                self.assertIn("doğrulayamadım", response.casefold())
                self.assertEqual(self.ctx.profile.data["items"], before)
        self.assertNotEqual(first["id"], second["id"])

    def test_voice_identity_selects_existing_profile_writer_with_closed_key(self):
        self.assertEqual(
            brain_core_map.core_plan("voice.select", {"key": "tr_kadin"}),
            ("voice_select", {"key": "tr_kadin"}),
        )
        self.assertIsNone(brain_core_map.core_plan("voice.select", {"key": "unknown"}))
        def choose_voice(current, text, *, active_context=None):
            return replace(
                current, request_kind=RequestKind.CAPABILITY,
                capability_hint="voice.select", arguments={"key": "tr_kadin"},
                needs_input=False, ambiguities=(),
            )
        with patch.object(brain_entry, "apply_model_understanding", side_effect=choose_voice), \
             patch.object(self.ctx, "_set_voice", return_value="Defne sesi seçildi") as voice:
            entry, output, _handler, feedback = self.turn_real(
                "Defne sesine geç", model_understanding=True)
        self.assertIn("MODEL_DECIDED", entry.understanding.reason_codes)
        self.assertEqual(output, "Defne sesi seçildi")
        self.assertEqual(feedback.result_status, "handled")
        voice.assert_called_once_with("tr_kadin")
