"""PR8 slice: Failure Synthesis / Recovery presentation.

Brain's handoff() already records one BrainFeedback (failed/cancelled) before
re-raising a Core exception. These tests check that (a) handoff grounds that
feedback's recovery_class/reason_code in the single failure_policy classifier
instead of leaving a flat "CORE_HANDLER_FAILED" bucket, and (b) the
presentation layer built on top of it never claims an automatic retry.
"""
from __future__ import annotations
from modules import core_brain_adapter

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from modules import brain_entry, brain_failure_synthesis, failure_policy
from modules.brain_contracts import ActiveContext, BrainFeedback
from modules.brain_gates import GateObservation

OWNER = "hamdi"
RID = "req-failure-synthesis"


class Http(RuntimeError):
    def __init__(self, code, text=""):
        super().__init__(text)
        self.status_code = code


def _entry() -> brain_entry.EntryResult:
    return brain_entry.EntryResult(
        owner=OWNER,
        request_id=RID,
        source="yazı",
        text="istek",
        active_context=ActiveContext(owner=OWNER, request_id=RID),
        state_gate=GateObservation(OWNER, RID, "state", True, "EXACT_STATE_MATCH"),
        fast_gate=GateObservation(OWNER, RID, "fast", False, "NO_EXACT_FAST_MATCH"),
        understanding=None,
    )


def _runtime():
    return SimpleNamespace(profile=SimpleNamespace(slug=OWNER))


class HandoffStructuredFailureTests(unittest.TestCase):
    def test_classified_core_exception_grounds_recovery_class_on_feedback(self):
        exc = Http(429, "Quota exceeded GenerateRequestsPerDayPerProjectPerModel-FreeTier")
        handler = Mock(side_effect=exc)
        with self.assertRaises(Http):
            core_brain_adapter.handoff(_runtime(), _entry(), handler, "haber özetle")
        row = brain_entry.last_feedback()
        self.assertEqual(row.result_status, "failed")
        self.assertEqual(row.reason_code, "PROVIDER_QUOTA_EXHAUSTED")
        self.assertEqual(row.recovery_class, "fallback_possible")

    def test_unclassified_core_exception_keeps_flat_bucket_without_recovery_class(self):
        handler = Mock(side_effect=ValueError("beklenmeyen"))
        with self.assertRaises(ValueError):
            core_brain_adapter.handoff(_runtime(), _entry(), handler, "bir şey yap")
        row = brain_entry.last_feedback()
        self.assertEqual(row.result_status, "failed")
        self.assertEqual(row.reason_code, "CORE_HANDLER_FAILED")
        self.assertIsNone(row.recovery_class)


class SynthesizeTests(unittest.TestCase):
    def _feedback(self, **overrides) -> BrainFeedback:
        base = dict(owner=OWNER, request_id=RID, result_status="failed")
        base.update(overrides)
        return BrainFeedback(**base)

    def test_rejects_non_failure_status(self):
        row = self._feedback(result_status="handled")
        with self.assertRaises(ValueError):
            brain_failure_synthesis.synthesize(row)

    def test_grounds_message_in_failure_policy_when_exception_given(self):
        exc = Http(429, "Quota exceeded GenerateRequestsPerDayPerProjectPerModel-FreeTier")
        row = self._feedback(reason_code="PROVIDER_QUOTA_EXHAUSTED", recovery_class="fallback_possible")
        message = brain_failure_synthesis.synthesize(row, exc)
        self.assertEqual(message, failure_policy.user_message(exc))
        self.assertIn("günlük kota", message)

    def test_known_reason_code_has_text_without_original_exception(self):
        row = self._feedback(reason_code="FILE_TARGET_NOT_ACCESSIBLE")
        message = brain_failure_synthesis.synthesize(row)
        self.assertIn("erişemiyorum", message)

    def test_unknown_reason_code_falls_back_without_fabricating_detail(self):
        row = self._feedback(reason_code="SOME_FUTURE_REASON_CODE")
        message = brain_failure_synthesis.synthesize(row)
        self.assertEqual(message, "İşlem tamamlanamadı; tanı kaydına bakılmalı.")

    def test_never_claims_an_automatic_retry_regardless_of_recovery_class(self):
        for recovery_class in ("retryable", "fallback_possible", "user_action_required", "fail_closed", None):
            with self.subTest(recovery_class=recovery_class):
                row = self._feedback(reason_code="CORE_HANDLER_FAILED", recovery_class=recovery_class)
                message = brain_failure_synthesis.synthesize(row)
                for phrase in ("otomatik", "yeniden deniyorum", "tekrar deniyorum"):
                    self.assertNotIn(phrase, message.casefold())

    def test_cancelled_status_is_accepted(self):
        row = self._feedback(result_status="cancelled", reason_code="CORE_CANCELLED")
        self.assertEqual(brain_failure_synthesis.synthesize(row), "İşlem senin isteğinle durduruldu.")


if __name__ == "__main__":
    unittest.main()
