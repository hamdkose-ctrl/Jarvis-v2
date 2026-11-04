from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from modules.brain_contracts import (
    Confidence, ConversationRelation, RequestKind, TemporalNeed, UnderstandingResult,
)
from modules import brain_model_understanding as model


OWNER = "hamdi"


def current(**changes):
    values = dict(
        owner=OWNER,
        request_id="req-model-1",
        request_kind=RequestKind.CAPABILITY,
        capability_hint="files.read",
        arguments={"operation": "summarize", "path": "C:/Users/hamdi/Documents/rapor.pdf"},
        conversation_relation=ConversationRelation.NEW_REQUEST,
        temporal_need=TemporalNeed.UNSURE,
        confidence=Confidence.MEDIUM,
    )
    values.update(changes)
    return UnderstandingResult(**values)


def answer(**changes):
    values = {
        "request_kind": "CHAT",
        "conversation_relation": "NEW_REQUEST",
        "temporal_need": "STATIC",
        "capability_hint": None,
        "confidence": "LOW",
        "file_operation": None,
        "file_slots": [],
    }
    values.update(changes)
    return json.dumps(values)


class BrainModelUnderstandingTests(unittest.TestCase):
    def setUp(self):
        owner_patch = patch("modules.llm.current_user", return_value=OWNER)
        owner_patch.start()
        self.addCleanup(owner_patch.stop)

    def eligible(self):
        return (
            patch("modules.llm.provider", return_value="groq"),
            patch("modules.llm.privacy.mode", return_value="normal"),
            patch("modules.smart_router.selection", return_value={"candidates": ["groq"]}),
        )

    def test_model_can_conservatively_downgrade_false_capability_to_chat(self):
        p1, p2, p3 = self.eligible()
        with p1, p2, p3, patch("modules.smart_router.run", return_value=answer()):
            result = model.refine(
                owner=OWNER, text="rapor dosyasını özetle", current=current(),
                arguments=current().arguments,
            )
        self.assertIsNotNone(result)
        self.assertIs(result.request_kind, RequestKind.CHAT)
        self.assertIs(result.temporal_need, TemporalNeed.STATIC)

    def test_owner_mismatch_never_uses_another_profiles_provider_key(self):
        with patch("modules.llm.current_user", return_value="other"), \
                patch("modules.smart_router.run") as run:
            result = model.refine(owner=OWNER, text="rapor", current=current(), arguments=current().arguments)
        self.assertIsNone(result)
        run.assert_not_called()

    def test_paid_provider_is_never_used_by_brain_refinement(self):
        with patch("modules.llm.provider", return_value="openai"), patch("modules.smart_router.run") as ask:
            result = model.refine(owner=OWNER, text="rapor", current=current(), arguments=current().arguments)
        self.assertIsNone(result)
        ask.assert_not_called()

    def test_local_ollama_is_not_silently_started_or_selected(self):
        with patch("modules.llm.provider", return_value="ollama"), patch("modules.smart_router.run") as ask:
            result = model.refine(owner=OWNER, text="rapor", current=current(), arguments=current().arguments)
        self.assertIsNone(result)
        ask.assert_not_called()

    def test_no_verified_free_provider_means_no_model_call(self):
        p1, p2, _ = self.eligible()
        with p1, p2, patch("modules.smart_router.selection", return_value={"candidates": ["ollama"]}), patch("modules.smart_router.run") as ask:
            result = model.refine(owner=OWNER, text="rapor", current=current(), arguments=current().arguments)
        self.assertIsNone(result)
        ask.assert_not_called()

    def test_unknown_capability_is_rejected(self):
        p1, p2, p3 = self.eligible()
        raw = answer(request_kind="CAPABILITY", capability_hint="shell.execute", confidence="LOW")
        with p1, p2, p3, patch("modules.smart_router.run", return_value=raw):
            result = model.refine(owner=OWNER, text="çalıştır", current=current(), arguments=current().arguments)
        self.assertIsNone(result)

    def test_capability_requires_independent_core_argument_validation(self):
        p1, p2, p3 = self.eligible()
        raw = answer(request_kind="CAPABILITY", capability_hint="files.read", confidence="LOW")
        with p1, p2, p3, patch("modules.smart_router.run", return_value=raw):
            result = model.refine(owner=OWNER, text="rapor", current=current(), arguments={"execute": True})
        self.assertIsNone(result)

    def test_model_cannot_upgrade_confidence_or_rewrite_pending_relation(self):
        p1, p2, p3 = self.eligible()
        raw = answer(confidence="HIGH")
        with p1, p2, p3, patch("modules.smart_router.run", return_value=raw):
            result = model.refine(owner=OWNER, text="rapor", current=current(), arguments=current().arguments)
        self.assertIsNone(result)

        pending = current(
            conversation_relation=ConversationRelation.ANSWER_TO_PENDING,
        )
        raw = answer(conversation_relation="NEW_REQUEST")
        with p1, p2, p3, patch("modules.smart_router.run", return_value=raw):
            result = model.refine(owner=OWNER, text="İstanbul", current=pending, arguments=pending.arguments,
                                  protected_relation=True)
        self.assertIsNone(result)

    def test_malformed_json_fails_closed(self):
        p1, p2, p3 = self.eligible()
        with p1, p2, p3, patch("modules.smart_router.run", return_value="not json"):
            result = model.refine(owner=OWNER, text="rapor", current=current(), arguments=current().arguments)
        self.assertIsNone(result)


    def test_request_cancellation_propagates_instead_of_becoming_chat_fallback(self):
        from modules import requests_state
        p1, p2, p3 = self.eligible()
        with p1, p2, p3, patch("modules.smart_router.run", side_effect=requests_state.Cancelled("cancelled")):
            with self.assertRaises(requests_state.Cancelled):
                model.refine(owner=OWNER, text="rapor", current=current(), arguments=current().arguments)

    def test_model_timeout_fails_closed_without_changing_existing_proposal(self):
        p1, p2, p3 = self.eligible()
        with p1, p2, p3, patch("modules.smart_router.run", side_effect=TimeoutError("late")):
            result = model.refine(owner=OWNER, text="rapor", current=current(), arguments=current().arguments)
        self.assertIsNone(result)


    def test_model_cannot_create_a_clarification_without_a_typed_reason(self):
        p1, p2, p3 = self.eligible()
        raw = answer(request_kind="CLARIFY", capability_hint=None)
        with p1, p2, p3, patch("modules.smart_router.run", return_value=raw):
            result = model.refine(owner=OWNER, text="rapor", current=current(), arguments=current().arguments)
        self.assertIsNone(result)


    def test_model_maps_file_operation_only_through_supplied_reference_slot(self):
        from modules.brain_contracts import ContextReference
        from modules.brain_core_map import core_plan
        file_ref = ContextReference(
            id="file-ref-1", kind="file", source="candidate", owner=OWNER,
            provenance={"path": "C:/Users/hamdi/Documents/rapor.pdf", "name": "rapor.pdf"},
        )
        active = current(
            request_kind=RequestKind.CHAT,
            capability_hint=None,
            arguments={"original_text": "şu raporu bir incele"},
            references=(file_ref,),
        )
        p1, p2, p3 = self.eligible()
        raw = answer(request_kind="CAPABILITY", capability_hint="files.read",
                     file_operation="analyze", file_slots=["file_0"], confidence="MEDIUM")
        with p1, p2, p3, patch("modules.smart_router.run", return_value=raw), \
                patch("modules.brain_core_map._validated_file_path", side_effect=lambda value: value):
            result = model.refine(owner=OWNER, text="şu raporu bir incele", current=active,
                                  arguments=active.arguments)
            self.assertIsNotNone(result)
            self.assertEqual(result.capability_hint, "files.read")
            self.assertEqual(result.arguments, {
                "original_text": "şu raporu bir incele",
                "operation": "analyze",
                "path": "C:/Users/hamdi/Documents/rapor.pdf",
            })
            self.assertEqual(core_plan(result.capability_hint, result.arguments),
                             ("file_action", {"operation": "analyze",
                                              "path": "C:/Users/hamdi/Documents/rapor.pdf"}))

    def test_model_cannot_invent_file_slot_or_path(self):
        from modules.brain_contracts import ContextReference
        file_ref = ContextReference(
            id="file-ref-1", kind="file", source="candidate", owner=OWNER,
            provenance={"path": "C:/Users/hamdi/Documents/rapor.pdf", "name": "rapor.pdf"},
        )
        active = current(request_kind=RequestKind.CHAT, capability_hint=None,
                         arguments={"original_text": "şu raporu incele"}, references=(file_ref,))
        p1, p2, p3 = self.eligible()
        unknown_slot = answer(request_kind="CAPABILITY", capability_hint="files.read",
                              file_operation="analyze", file_slots=["file_9"], confidence="MEDIUM")
        with p1, p2, p3, patch("modules.smart_router.run", return_value=unknown_slot):
            self.assertIsNone(model.refine(owner=OWNER, text="şu raporu incele", current=active,
                                           arguments=active.arguments))
        invented_path = answer(request_kind="CAPABILITY", capability_hint="files.read",
                               file_operation="analyze", file_slots=["file_0"], path="C:/secret.txt")
        with p1, p2, p3, patch("modules.smart_router.run", return_value=invented_path):
            self.assertIsNone(model.refine(owner=OWNER, text="şu raporu incele", current=active,
                                           arguments=active.arguments))


    def test_model_cannot_switch_a_current_capability_to_another_domain(self):
        p1, p2, p3 = self.eligible()
        active = current(capability_hint="notes.read", arguments={"original_text": "notları göster"})
        raw = answer(request_kind="CAPABILITY", capability_hint="files.read",
                     file_operation="list", file_slots=[], confidence="MEDIUM")
        with p1, p2, p3, patch("modules.smart_router.run", return_value=raw):
            result = model.refine(owner=OWNER, text="notları göster", current=active,
                                  arguments=active.arguments)
        self.assertIsNone(result)


    def test_model_cannot_change_deterministic_file_operation_or_target(self):
        from modules.brain_contracts import ContextReference
        first = ContextReference(
            id="file-ref-1", kind="file", source="candidate", owner=OWNER,
            provenance={"path": "C:/Users/hamdi/Documents/rapor.pdf", "name": "rapor.pdf"},
        )
        second = ContextReference(
            id="file-ref-2", kind="file", source="candidate", owner=OWNER,
            provenance={"path": "C:/Users/hamdi/Documents/butce.pdf", "name": "butce.pdf"},
        )
        active = current(
            capability_hint="files.read",
            arguments={"original_text": "rapor dosyasını özetle", "operation": "summarize",
                       "path": "C:/Users/hamdi/Documents/rapor.pdf"},
            references=(first, second),
        )
        p1, p2, p3 = self.eligible()
        changed_operation = answer(request_kind="CAPABILITY", capability_hint="files.read",
                                  file_operation="analyze", file_slots=["file_0"], confidence="MEDIUM")
        with p1, p2, p3, patch("modules.smart_router.run", return_value=changed_operation):
            self.assertIsNone(model.refine(owner=OWNER, text="rapor dosyasını özetle", current=active,
                                           arguments=active.arguments))
        wrong_target = answer(request_kind="CAPABILITY", capability_hint="files.read",
                              file_operation="summarize", file_slots=["file_1"], confidence="MEDIUM")
        with p1, p2, p3, patch("modules.smart_router.run", return_value=wrong_target):
            self.assertIsNone(model.refine(owner=OWNER, text="rapor dosyasını özetle", current=active,
                                           arguments=active.arguments))


if __name__ == "__main__":
    unittest.main()
