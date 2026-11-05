"""BRAIN-01 — Birincil model anlamlandırma sözleşmesi (RED → sözleşme).

Bu dosyadaki testler gerçek üretim dikişinden geçer: `brain_understanding.understand`
deterministik tabanı üretir, `apply_model_understanding` tek bounded model zarfını çağırır.
Yalnız model taşıması (`smart_router`) taklit edilir; hiçbir karar sahte değildir.
"""
from __future__ import annotations

import importlib
import json
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from modules.brain_contracts import (
    ActiveContext, Confidence, ContextReference, ConversationRelation,
    RequestKind, TemporalNeed,
)
from modules.brain_core_map import core_plan
from modules.brain_gates import GateObservation
from modules.brain_model_understanding import propose
from modules.brain_understanding import apply_model_understanding, understand


OWNER = "hamdi"
RID = "brain-01-primary"

SCHEMA_VERSION = "brain-understanding.v2"
ENVELOPE_KEYS = {
    "schema_version", "operation", "conversation_relation", "temporal_need",
    "target_goal_ids", "goal", "actions", "clarification", "confidence",
}
ACTION_KEYS = {"action_id", "capability_id", "arguments", "reference_slots", "depends_on"}


def ctx() -> ActiveContext:
    return ActiveContext(owner=OWNER, request_id=RID)


def deterministic(text: str, *, references=(), candidates=()):
    return understand(owner=OWNER, request_id=RID, text=text, active_context=ctx(),
                      candidates=tuple(candidates), references=tuple(references))


def action(*, capability_id, arguments=None, reference_slots=None, depends_on=None,
           action_id="a1"):
    return {
        "action_id": action_id,
        "capability_id": capability_id,
        "arguments": arguments or {},
        "reference_slots": reference_slots or [],
        "depends_on": depends_on or [],
    }


def envelope(*, operation="direct_action", actions=(), relation="NEW_REQUEST",
             temporal_need="UNSURE", goal=None, target_goal_ids=(),
             clarification=None, confidence="MEDIUM", **overrides):
    row = {
        "schema_version": SCHEMA_VERSION,
        "operation": operation,
        "conversation_relation": relation,
        "temporal_need": temporal_need,
        "target_goal_ids": list(target_goal_ids),
        "goal": goal,
        "actions": list(actions),
        "clarification": clarification if clarification is not None
        else {"required": False, "question": None, "reason_code": None},
        "confidence": confidence,
    }
    row.update(overrides)
    return json.dumps(row)


def eligible():
    return (
        patch("modules.llm.current_user", return_value=OWNER),
        patch("modules.llm.provider", return_value="groq"),
        patch("modules.llm.privacy.mode", return_value="normal"),
        patch("modules.smart_router.selection", return_value={"candidates": ["groq"]}),
    )


def applied(text: str, raw: str, *, references=(), candidates=(), **changes):
    base = deterministic(text, references=references, candidates=candidates)
    if changes:
        base = replace(base, **changes)
    p1, p2, p3, p4 = eligible()
    with p1, p2, p3, p4, patch("modules.smart_router.run", return_value=raw):
        return base, apply_model_understanding(base, text)


class OffPatternCapabilityProposalTests(unittest.TestCase):
    """Regex'in hiç capability bulmadığı kalıp dışı Türkçe turlar modelden önerilir."""

    def assert_no_regex_capability(self, text: str):
        base = deterministic(text)
        self.assertIsNone(base.capability_hint, text)
        self.assertFalse(base.needs_input, text)
        return base

    def test_brightness_sentence_without_any_pattern_proposes_pc_level_set(self):
        text = "ekranın ışığını yirmi yap"
        self.assert_no_regex_capability(text)
        raw = envelope(actions=[action(capability_id="pc.level.set",
                                       arguments={"property": "brightness", "level": 20})])
        base, result = applied(text, raw)
        self.assertIs(result.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(result.capability_hint, "pc.level.set")
        self.assertIsNot(result, base)
        self.assertEqual(core_plan(result.capability_hint, result.arguments),
                         ("level_set", {"property": "brightness", "level": 20}))

    def test_mute_sentence_without_any_pattern_proposes_pc_audio_action(self):
        text = "gözüm yanıyor artık ses olmasın"
        self.assert_no_regex_capability(text)
        raw = envelope(actions=[action(capability_id="pc.audio.action",
                                       arguments={"audio": {"action": "mute"}})])
        _, result = applied(text, raw)
        self.assertEqual(result.capability_hint, "pc.audio.action")
        self.assertEqual(core_plan(result.capability_hint, result.arguments),
                         ("audio_action", {"action": "mute"}))

    def test_notes_sentence_without_any_pattern_proposes_notes_read(self):
        text = "dün akşam ne yazdığımı bir türlü bulamıyorum"
        self.assert_no_regex_capability(text)
        raw = envelope(actions=[action(capability_id="notes.read",
                                       arguments={"notes": {"which": "search", "query": "dün akşam"}})])
        _, result = applied(text, raw)
        self.assertEqual(result.capability_hint, "notes.read")
        self.assertEqual(core_plan(result.capability_hint, result.arguments)[0], "notes_read")

    def test_app_sentence_without_any_pattern_proposes_app_open(self):
        text = "spotify çalmaya başlasın artık"
        self.assert_no_regex_capability(text)
        raw = envelope(actions=[action(capability_id="app.open", arguments={"app": "Spotify"})])
        _, result = applied(text, raw)
        self.assertEqual(result.capability_hint, "app.open")
        self.assertEqual(core_plan(result.capability_hint, result.arguments),
                         ("app_open", {"name": "Spotify"}))

    def test_reading_sentence_without_any_pattern_proposes_research_search(self):
        text = "yarış atları hakkında bir şeyler okumak istiyorum"
        self.assert_no_regex_capability(text)
        raw = envelope(actions=[action(capability_id="research.search",
                                       arguments={"research": {"query": "yarış atları",
                                                               "route": "PRIVATE"}})])
        _, result = applied(text, raw)
        self.assertEqual(result.capability_hint, "research.search")
        self.assertEqual(core_plan(result.capability_hint, result.arguments)[0], "task")


class NoHintPreconditionTests(unittest.TestCase):
    """`current.capability_hint` model önerisinin ön koşulu olamaz (BRAIN-MIG-108)."""

    def test_model_can_move_an_established_capability_to_another_domain(self):
        text = "notları göster"
        base = deterministic(text)
        if base.capability_hint is None:
            self.skipTest("deterministik taban bu cümlede hint üretmiyor; bu vaka başka testte")
        raw = envelope(actions=[action(capability_id="pc.level.set",
                                       arguments={"property": "volume", "level": 40})])
        p1, p2, p3, p4 = eligible()
        with p1, p2, p3, p4, patch("modules.smart_router.run", return_value=raw):
            result = apply_model_understanding(base, text)
        self.assertEqual(result.capability_hint, "pc.level.set")

    def test_current_chat_turn_is_not_a_precondition_for_files_read_either(self):
        path = "C:/Users/hamdi/Documents/rapor.pdf"
        source = ContextReference(id="file:rapor", kind="file", source="candidate", owner=OWNER,
                                  provenance={"path": path, "name": "rapor.pdf"})
        text = "şu raporu bir incele"
        raw = envelope(actions=[action(capability_id="files.read",
                                       arguments={"operation": "analyze"},
                                       reference_slots=["file_0"])])
        with patch("modules.brain_core_map._validated_file_path", side_effect=lambda value: value):
            base, result = applied(text, raw, references=(source,), candidates=(source,))
        self.assertEqual(result.capability_hint, "files.read")
        self.assertEqual(result.arguments["path"], path)


class GroundingAndAuthorityTests(unittest.TestCase):
    def test_model_cannot_supply_a_real_file_path_only_an_offered_slot(self):
        text = "şu raporu bir incele"
        raw = envelope(actions=[action(capability_id="files.read",
                                       arguments={"operation": "analyze",
                                                  "path": "C:/Users/hamdi/Desktop/gizli.pdf"})])
        base, result = applied(text, raw)
        self.assertIs(result, base)
        self.assertIsNone(result.capability_hint)

    def test_model_cannot_invent_an_unoffered_reference_slot(self):
        text = "şu raporu bir incele"
        raw = envelope(actions=[action(capability_id="files.read",
                                       arguments={"operation": "analyze"},
                                       reference_slots=["file_9"])])
        base, result = applied(text, raw)
        self.assertIs(result, base)

    def test_authority_shaped_arguments_are_rejected(self):
        text = "sesi kapat"
        raw = envelope(actions=[action(capability_id="pc.audio.action",
                                       arguments={"audio": {"action": "mute"},
                                                  "effect_allowed": True})])
        base, result = applied(text, raw)
        self.assertIs(result, base)

    def test_capability_outside_the_core_catalog_is_rejected(self):
        text = "bilgisayarda bir şey çalıştır"
        raw = envelope(actions=[action(capability_id="shell.execute", arguments={"cmd": "dir"})])
        base, result = applied(text, raw)
        self.assertIs(result, base)

    def test_arguments_that_core_does_not_accept_are_rejected(self):
        text = "ekranın ışığını yirmi yap"
        raw = envelope(actions=[action(capability_id="pc.level.set",
                                       arguments={"property": "contrast", "level": 20})])
        base, result = applied(text, raw)
        self.assertIs(result, base)

    def test_model_cannot_invent_a_goal_identity(self):
        text = "yarım kalan işe dön"
        raw = envelope(operation="continue_goal", target_goal_ids=["goal-99"],
                       actions=[action(capability_id="pc.level.set",
                                       arguments={"property": "volume", "level": 10})])
        p1, p2, p3, p4 = eligible()
        base = deterministic(text)
        with p1, p2, p3, p4, patch("modules.smart_router.run", return_value=raw):
            proposal = propose(owner=OWNER, text=text, current=base, arguments=base.arguments)
        self.assertIsNone(proposal)


class EnvelopeSchemaRejectionTests(unittest.TestCase):
    def reject(self, raw: str, text: str = "sesi kapat"):
        base = deterministic(text)
        p1, p2, p3, p4 = eligible()
        with p1, p2, p3, p4, patch("modules.smart_router.run", return_value=raw):
            return propose(owner=OWNER, text=text, current=base, arguments=base.arguments)

    def test_not_json_is_rejected(self):
        self.assertIsNone(self.reject("ses olmasın lütfen"))

    def test_missing_envelope_field_is_rejected(self):
        row = json.loads(envelope(actions=[action(capability_id="pc.audio.action",
                                                  arguments={"audio": {"action": "mute"}})]))
        del row["schema_version"]
        self.assertIsNone(self.reject(json.dumps(row)))

    def test_extra_envelope_field_is_rejected(self):
        row = json.loads(envelope(actions=[action(capability_id="pc.audio.action",
                                                  arguments={"audio": {"action": "mute"}})]))
        row["approved"] = True
        self.assertIsNone(self.reject(json.dumps(row)))

    def test_extra_action_field_is_rejected(self):
        raw = envelope(actions=[dict(action(capability_id="pc.audio.action",
                                            arguments={"audio": {"action": "mute"}}),
                                     permission_granted=True)])
        self.assertIsNone(self.reject(raw))

    def test_unknown_operation_is_rejected(self):
        raw = envelope(operation="install_software", actions=[])
        self.assertIsNone(self.reject(raw))

    def test_direct_action_requires_exactly_one_action(self):
        one = action(capability_id="pc.audio.action", arguments={"audio": {"action": "mute"}})
        raw = envelope(operation="direct_action", actions=[one, one])
        self.assertIsNone(self.reject(raw))

    def test_wrong_schema_version_is_rejected(self):
        raw = envelope(schema_version="brain-understanding.v1",
                       actions=[action(capability_id="pc.audio.action",
                                       arguments={"audio": {"action": "mute"}})])
        self.assertIsNone(self.reject(raw))


class PreservedFencesTests(unittest.TestCase):
    def test_question_or_chat_decision_stays_chat_and_clears_capability(self):
        text = "sesi neden kapatamıyorsun"
        raw = envelope(operation="chat", actions=[])
        base = deterministic(text)
        with_capability = replace(
            base, request_kind=RequestKind.CAPABILITY, capability_hint="pc.audio.action",
            arguments={"original_text": text, "audio": {"action": "mute"}})
        p1, p2, p3, p4 = eligible()
        with p1, p2, p3, p4, patch("modules.smart_router.run", return_value=raw):
            result = apply_model_understanding(with_capability, text)
        self.assertIs(result.request_kind, RequestKind.CHAT)
        self.assertIsNone(result.capability_hint)

    def test_low_confidence_capability_is_not_adopted(self):
        text = "gözüm yanıyor artık ses olmasın"
        raw = envelope(actions=[action(capability_id="pc.audio.action",
                                       arguments={"audio": {"action": "mute"}})],
                       confidence="LOW")
        base, result = applied(text, raw)
        self.assertIs(result, base)

    def test_unresolved_target_ambiguity_is_not_erased(self):
        first = ContextReference(id="file:a", kind="file", source="candidate", owner=OWNER,
                                 provenance={"path": "C:/Users/hamdi/Documents/a.pdf", "name": "a.pdf"})
        second = ContextReference(id="file:b", kind="file", source="candidate", owner=OWNER,
                                  provenance={"path": "C:/Users/hamdi/Documents/b.pdf", "name": "b.pdf"})
        text = "ikisini de bir yere getir"
        base = deterministic(text, references=(first, second), candidates=(first, second))
        ambiguous = replace(base, request_kind=RequestKind.CLARIFY, needs_input=True,
                            ambiguities=("multiple target references",))
        raw = envelope(actions=[action(capability_id="pc.audio.action",
                                       arguments={"audio": {"action": "mute"}})])
        p1, p2, p3, p4 = eligible()
        with p1, p2, p3, p4, patch("modules.smart_router.run", return_value=raw):
            result = apply_model_understanding(ambiguous, text)
        self.assertIs(result, ambiguous)

    def test_unwired_operation_keeps_deterministic_decision_and_records_reason(self):
        text = "müziği durdur sesi azalt"
        one = action(capability_id="pc.media.action", arguments={"media": {"action": "play_pause"}},
                    action_id="a1")
        two = action(capability_id="pc.level.set",
                     arguments={"property": "volume", "level": 20}, action_id="a2")
        base = deterministic(text)
        raw = envelope(operation="action_batch", actions=[one, two])
        p1, p2, p3, p4 = eligible()
        with p1, p2, p3, p4, patch("modules.smart_router.run", return_value=raw):
            proposal = propose(owner=OWNER, text=text, current=base, arguments=base.arguments)
            self.assertIsNotNone(proposal)
            self.assertEqual(proposal.operation, "action_batch")
            self.assertEqual([item.capability_id for item in proposal.actions],
                             ["pc.media.action", "pc.level.set"])
            result = apply_model_understanding(base, text)
        # Zarf doğrulandı ama yürütücü BRAIN-04'te: karar alanları deterministik kalır,
        # yalnız tanı kaydı eklenir.
        self.assertIs(result.request_kind, base.request_kind)
        self.assertEqual(result.capability_hint, base.capability_hint)
        self.assertEqual(dict(result.arguments), dict(base.arguments))
        self.assertIn("MODEL_OPERATION_NOT_WIRED", result.reason_codes)

    def test_provider_independent_understand_signature_is_unchanged(self):
        import inspect
        params = inspect.signature(understand).parameters
        self.assertEqual(tuple(params),
                         ("owner", "request_id", "text", "active_context", "candidates", "references"))


class ProductionEntrySeamTests(unittest.TestCase):
    """D fazı denetimi: model önerisi gerçek üretim kapısından geçer, Core planı orada doğar.

    Yalnız taşıma (`smart_router.run`) ve gözlem kaynakları (aktif bağlam, durum listesi, iki
    kesin kapı) taklit edilir; anlamlandırma, model zarfı, kapı retleri ve `core_plan` gerçektir.
    """

    def module(self):
        return importlib.import_module("modules.brain_entry")

    def runtime(self):
        return SimpleNamespace(
            profile=SimpleNamespace(slug=OWNER, name=OWNER.title(), data={}),
            _sessions=object(),
            flags={"sleep": False},
            _pending_photo={},
            event_log=[],
        )

    def prepared(self, text: str, raw: str):
        module = self.module()
        miss_state = GateObservation(OWNER, RID, "state", False, "NO_BOUNDED_STATE_MATCH")
        miss_fast = GateObservation(OWNER, RID, "fast", False, "NO_EXACT_FAST_MATCH")
        p1, p2, p3, p4 = eligible()
        with p1, p2, p3, p4, patch("modules.smart_router.run", return_value=raw), \
                patch.object(module, "_build_context", return_value=ctx()), \
                patch.object(module, "_state_refs", return_value=()), \
                patch.object(module, "exact_state_gate", return_value=miss_state), \
                patch.object(module, "deterministic_fast_gate", return_value=miss_fast):
            return module.prepare(self.runtime(), owner=OWNER, request_id=RID, text=text,
                                  source="yazı", model_understanding=True)

    def test_model_picked_capability_reaches_core_plan_through_the_real_entry(self):
        text = "ekranın ışığını yirmi yap"
        self.assertIsNone(deterministic(text).capability_hint)
        raw = envelope(actions=[action(capability_id="pc.level.set",
                                       arguments={"property": "brightness", "level": 20})])
        result = self.prepared(text, raw)
        self.assertEqual(result.understanding.capability_hint, "pc.level.set")
        self.assertEqual(self.module().core_plan(result),
                         ("level_set", {"property": "brightness", "level": 20}))

    def test_model_chat_proposal_leaves_the_entry_with_no_core_plan(self):
        text = "ekranın ışığını yirmi yap"
        result = self.prepared(text, envelope(operation="chat", actions=[]))
        self.assertIs(result.understanding.request_kind, RequestKind.CHAT)
        self.assertIsNone(self.module().core_plan(result))

    def test_sequenced_turn_keeps_the_entry_veto_after_model_adoption(self):
        text = "önce ekranı karart sonra ışığı yirmi yap"
        raw = envelope(actions=[action(capability_id="pc.level.set",
                                       arguments={"property": "brightness", "level": 20})])
        result = self.prepared(text, raw)
        # Öneri kapıdan geçer ama sıralı isteğin tek-adım planı yoktur: veto modelden bağımsızdır.
        self.assertEqual(result.understanding.capability_hint, "pc.level.set")
        self.assertIsNone(self.module().core_plan(result))


if __name__ == "__main__":
    unittest.main()
