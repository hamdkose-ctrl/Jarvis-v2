from __future__ import annotations
from modules import core_brain_adapter

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import brain_entry
from modules.brain_contracts import (
    ActiveContext,
    BrainFeedback,
    Confidence,
    RequestKind,
    TemporalNeed,
    UnderstandingResult,
)
from modules.brain_gates import GateObservation

OWNER = "hamdi"
RID = "req-feedback-contract"
_RESERVED = {
    "allowed", "permission", "permission_granted", "approved", "authorized",
    "completed", "done", "effect_allowed", "execute",
}


def _context() -> ActiveContext:
    return ActiveContext(owner=OWNER, request_id=RID)


def _semantic(*, clarify: bool) -> UnderstandingResult:
    return UnderstandingResult(
        owner=OWNER,
        request_id=RID,
        request_kind=RequestKind.CLARIFY if clarify else RequestKind.CHAT,
        arguments={"original_text": "istek"},
        temporal_need=TemporalNeed.UNSURE,
        confidence=Confidence.LOW if clarify else Confidence.MEDIUM,
        ambiguities=("multiple target references",) if clarify else (),
        needs_input=clarify,
    )


def _entry(*, semantic=None, state=None) -> brain_entry.EntryResult:
    return brain_entry.EntryResult(
        owner=OWNER,
        request_id=RID,
        source="yazı",
        text="istek",
        active_context=_context(),
        state_gate=state or GateObservation(OWNER, RID, "state", False, "NO_BOUNDED_STATE_MATCH"),
        fast_gate=GateObservation(OWNER, RID, "fast", False, "NO_EXACT_FAST_MATCH"),
        understanding=semantic,
    )


def _runtime():
    return SimpleNamespace(profile=SimpleNamespace(slug=OWNER))


class BrainFeedbackContractTests(unittest.TestCase):
    def test_text_semantic_clarification_sets_needs_input_and_safe_ambiguities(self):
        row = _entry(semantic=_semantic(clarify=True))
        handler = Mock(side_effect=AssertionError("clarification effect/worker başlatmamalı"))
        output, feedback, job_id = core_brain_adapter.handoff(_runtime(), row, handler, "onu aç")
        handler.assert_not_called()
        self.assertIn("netleştir", output.casefold())
        self.assertEqual((feedback.owner, feedback.request_id), (OWNER, RID))
        self.assertEqual(feedback.result_status, "needs_input")
        self.assertTrue(feedback.needs_input)
        self.assertEqual(feedback.ambiguities, ("multiple target references",))
        self.assertIsNone(job_id)

    def test_multiple_bounded_state_feedback_is_needs_input_without_effect(self):
        conflict = GateObservation(
            OWNER,
            RID,
            "state",
            False,
            "MULTIPLE_BOUNDED_STATE_MATCHES",
        )
        row = _entry(state=conflict)
        handler = Mock(side_effect=AssertionError("multiple state effect/worker başlatmamalı"))
        output, feedback, job_id = core_brain_adapter.handoff(_runtime(), row, handler, "evet")
        handler.assert_not_called()
        self.assertIn("birden fazla", output.casefold())
        self.assertEqual(feedback.result_status, "needs_input")
        self.assertTrue(feedback.needs_input)
        self.assertEqual(feedback.reason_code, "MULTIPLE_BOUNDED_STATE_MATCHES")
        self.assertIsNone(job_id)

    def test_photo_clarification_cannot_be_reported_as_handled(self):
        row = _entry(semantic=_semantic(clarify=True))
        feedback = brain_entry.feedback(
            row,
            result_status="handled",
            reason_code="PHOTO_CORE_HANDOFF_RETURNED",
        )
        self.assertEqual((feedback.owner, feedback.request_id), (OWNER, RID))
        self.assertEqual(feedback.result_status, "needs_input")
        self.assertTrue(feedback.needs_input)
        self.assertEqual(feedback.ambiguities, ("multiple target references",))
        self.assertEqual(feedback.reason_code, "BRAIN_CLARIFICATION_REQUIRED")

    def test_ordinary_handled_feedback_stays_non_clarifying(self):
        row = _entry(semantic=_semantic(clarify=False))
        feedback = brain_entry.feedback(
            row,
            result_status="handled",
            reason_code="CORE_HANDOFF_RETURNED",
        )
        self.assertEqual(feedback.result_status, "handled")
        self.assertFalse(feedback.needs_input)
        self.assertEqual(feedback.ambiguities, ())
        self.assertEqual(feedback.reason_code, "CORE_HANDOFF_RETURNED")

    def test_feedback_contract_never_exposes_authority_fields(self):
        row = _entry(semantic=_semantic(clarify=True))
        feedback = brain_entry.feedback(row, result_status="handled", reason_code="PHOTO_CORE_HANDOFF_RETURNED")
        self.assertIsInstance(feedback, BrainFeedback)
        payload = feedback.to_dict()
        self.assertFalse(_RESERVED.intersection(payload))
        encoded = json.dumps(payload, ensure_ascii=False)
        for forbidden in _RESERVED:
            self.assertNotIn(f'"{forbidden}"', encoded)


if __name__ == "__main__":
    unittest.main()
