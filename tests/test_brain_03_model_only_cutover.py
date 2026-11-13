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
