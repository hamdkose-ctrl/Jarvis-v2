from __future__ import annotations

import dataclasses
import json
import unittest

from modules import worker_result
from modules.brain_contracts import (
    ActiveContext,
    BrainFeedback,
    Confidence,
    ContextAction,
    ContextReference,
    ConversationRelation,
    EchoPreview,
    RequestKind,
    TemporalNeed,
    UnderstandingResult,
)


class BrainContractsTests(unittest.TestCase):
    def ref(self, *, owner="hamdi", ident="ref-1"):
        return ContextReference(
            id=ident,
            kind="artifact",
            source="document",
            owner=owner,
            provenance={"path": "rapor.xlsx", "page": 1},
            recency=TemporalNeed.RECENT,
            confidence=Confidence.HIGH,
            relevance=Confidence.MEDIUM,
        )

    def worker_row(self, status="succeeded"):
        return {
            "schema": worker_result.SCHEMA,
            "status": status,
            "evidence": [],
            "owner": "hamdi",
            "job_id": "job-1",
            "step_id": "step-1",
            "command_id": "cmd-1",
            "attempt": 1,
            "expected_job_version": 2,
            "capability_id": "document.read",
            "capability_version": "1",
            "input_digest": "sha256:abc",
        }

    def test_understanding_result_has_no_authority_fields(self):
        forbidden = {
            "allowed", "permission", "permission_granted", "approved",
            "authorized", "completed", "done", "effect_allowed", "execute",
        }
        fields = {field.name for field in dataclasses.fields(UnderstandingResult)}
        self.assertFalse(fields & forbidden)
        with self.assertRaises(TypeError):
            UnderstandingResult(request_kind=RequestKind.CHAT, allowed=True)

    def test_active_context_requires_owner_and_request_identity(self):
        with self.assertRaises(ValueError):
            ActiveContext(owner="", request_id="req-1")
        with self.assertRaises(ValueError):
            ActiveContext(owner="hamdi", request_id="")

    def test_active_context_rejects_reference_from_other_owner(self):
        with self.assertRaises(ValueError):
            ActiveContext(
                owner="hamdi",
                request_id="req-1",
                recent_references=(self.ref(owner="hasan"),),
            )

    def test_context_and_reference_are_json_compatible(self):
        context = ActiveContext(
            owner="hamdi",
            request_id="req-1",
            topic="rapor",
            recent_references=(self.ref(),),
        )
        json.dumps(context.to_dict(), ensure_ascii=False, allow_nan=False)
        json.dumps(self.ref().to_dict(), ensure_ascii=False, allow_nan=False)

    def test_contracts_are_frozen_and_nested_json_cannot_mutate(self):
        ref = self.ref()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            ref.kind = "task"
        with self.assertRaises(TypeError):
            ref.provenance["path"] = "baska.xlsx"

        result = UnderstandingResult(
            request_kind=RequestKind.CAPABILITY,
            arguments={"filters": {"days": [1, 7]}},
        )
        with self.assertRaises(TypeError):
            result.arguments["filters"] = {}
        with self.assertRaises(TypeError):
            result.arguments["filters"]["days"] = ()

    def test_low_confidence_can_carry_real_ambiguity(self):
        result = UnderstandingResult(
            request_kind=RequestKind.CLARIFY,
            confidence=Confidence.LOW,
            ambiguities=("Hangi rapor kastediliyor?",),
            needs_input=True,
        )
        self.assertEqual(result.confidence, Confidence.LOW)
        self.assertTrue(result.ambiguities)
        self.assertTrue(result.needs_input)

    def test_clarify_can_carry_candidate_references(self):
        result = UnderstandingResult(
            request_kind=RequestKind.CLARIFY,
            references=(self.ref(), self.ref(ident="ref-2")),
            confidence=Confidence.LOW,
            ambiguities=("İki aday var.",),
            needs_input=True,
        )
        self.assertEqual(len(result.references), 2)

    def test_context_action_is_advisory_not_goalstate_cancel_or_permission(self):
        result = UnderstandingResult(
            request_kind=RequestKind.CONTEXT_CONTROL,
            context_actions=(ContextAction.DROP_ACTIVE_TASK_REFERENCE,),
        )
        self.assertEqual(result.context_actions, (ContextAction.DROP_ACTIVE_TASK_REFERENCE,))
        self.assertNotIn("cancel", result.to_dict())
        self.assertNotIn("permission", result.to_dict())

    def test_echo_preview_is_not_permission_or_approval(self):
        preview = EchoPreview(text="2024 finans raporunu Excel'e çevireceğim.")
        fields = {field.name for field in dataclasses.fields(EchoPreview)}
        self.assertFalse(fields & {"permission", "approved", "authorized", "confirmation_receipt"})
        self.assertEqual(preview.to_dict()["text"], preview.text)

    def test_brain_feedback_carries_recovery_metadata_without_actions(self):
        feedback = BrainFeedback(
            owner="hamdi",
            request_id="req-1",
            result_status="failed",
            candidates=(self.ref(),),
            reason_code="FILE_LOCKED",
            recovery_class="user_action_required",
            effect_state="not_started",
            needs_input=True,
            ambiguities=("Dosyanın kapatılması gerekiyor.",),
        )
        payload = feedback.to_dict()
        self.assertEqual(payload["reason_code"], "FILE_LOCKED")
        self.assertEqual(payload["recovery_class"], "user_action_required")
        self.assertFalse(any(callable(getattr(feedback, field.name)) for field in dataclasses.fields(feedback)))
        self.assertFalse({"retry", "rollback", "permission", "execute"} & set(payload))

    def test_reverse_clarification_does_not_change_worker_result_v1_fields(self):
        self.assertEqual(
            worker_result._FIELDS,
            frozenset({
                "schema", "status", "evidence", "owner", "job_id", "step_id",
                "command_id", "attempt", "expected_job_version", "capability_id",
                "capability_version", "input_digest",
            }),
        )

    def test_worker_result_validate_still_accepts_only_canonical_statuses(self):
        self.assertEqual(worker_result.validate(self.worker_row("succeeded"))["status"], "succeeded")
        self.assertEqual(worker_result.validate(self.worker_row("failed"))["status"], "failed")
        with self.assertRaises(ValueError):
            worker_result.validate(self.worker_row("waiting"))

    def test_clarification_needed_is_not_a_worker_result_status(self):
        with self.assertRaises(ValueError):
            worker_result.validate(self.worker_row("ClarificationNeeded"))

    def test_contract_rejects_executable_callback(self):
        with self.assertRaises(ValueError):
            UnderstandingResult(
                request_kind=RequestKind.CAPABILITY,
                arguments={"callback": lambda: None},
            )
        with self.assertRaises(ValueError):
            ContextReference(
                id="ref-1", kind="artifact", source="document", owner="hamdi",
                provenance={"callback": lambda: None},
            )

    def test_unknown_enum_values_fail_closed(self):
        with self.assertRaises(ValueError):
            UnderstandingResult(request_kind="DO_SOMETHING")
        with self.assertRaises(ValueError):
            UnderstandingResult(
                request_kind=RequestKind.CHAT,
                conversation_relation="MAYBE",
            )
        with self.assertRaises(ValueError):
            ContextReference(
                id="ref-1", kind="artifact", source="document", owner="hamdi",
                recency="TOMORROW",
            )


if __name__ == "__main__":
    unittest.main()
