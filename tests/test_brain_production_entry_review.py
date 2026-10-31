from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modules import brain_entry, engine_commands
from modules.brain_contracts import ActiveContext, Confidence, RequestKind, TemporalNeed, UnderstandingResult
from modules.brain_gates import GateObservation

OWNER = "hamdi"
RID = "req-production-review"


def _context(*, pending=()) -> ActiveContext:
    return ActiveContext(owner=OWNER, request_id=RID, pending_references=tuple(pending))


def _semantic() -> UnderstandingResult:
    return UnderstandingResult(
        owner=OWNER,
        request_id=RID,
        request_kind=RequestKind.CHAT,
        arguments={"original_text": "selam"},
        temporal_need=TemporalNeed.UNSURE,
        confidence=Confidence.MEDIUM,
    )


def _entry(*, text="selam", pending=(), fast=None):
    return brain_entry.EntryResult(
        owner=OWNER,
        request_id=RID,
        source="yazı",
        text=text,
        active_context=_context(pending=pending),
        state_gate=GateObservation(OWNER, RID, "state", False, "NO_BOUNDED_STATE_MATCH"),
        fast_gate=fast or GateObservation(OWNER, RID, "fast", False, "NO_EXACT_FAST_MATCH"),
        understanding=_semantic(),
    )


class BrainProductionEntryReviewTests(unittest.TestCase):
    def test_plain_chat_without_open_pending_uses_existing_core_handler(self):
        runtime = SimpleNamespace(profile=SimpleNamespace(slug=OWNER))
        handler = Mock(return_value="Merhaba")
        row = _entry()
        with patch.object(brain_entry, "_install_core_guards"), \
             patch.object(brain_entry, "_correlated_job_id", return_value=None), \
             patch("modules.engine_intents.dispatch", side_effect=AssertionError("normal CHAT existing handler'ı bypass etmemeli")):
            output, feedback, job_id = brain_entry.handoff(runtime, row, handler, "selam")
        handler.assert_called_once_with("selam")
        self.assertEqual(output, "Merhaba")
        self.assertEqual(feedback.request_id, RID)
        self.assertIsNone(job_id)

    def test_bound_fast_miss_does_not_reenable_legacy_engine_control(self):
        row = _entry(text="Jarvis'i kapatma")
        self.assertFalse(brain_entry.allow_legacy_engine_control(row))

        close_hit = GateObservation(
            OWNER, RID, "fast", True, "EXACT_ENGINE_CONTROL", "fast.engine.close", "close"
        )
        self.assertTrue(brain_entry.allow_legacy_engine_control(_entry(text="Jarvis'i kapat", fast=close_hit)))

    def test_engine_commands_consults_canonical_fast_fence_before_legacy_engine_control(self):
        source = __import__("inspect").getsource(engine_commands.handle)
        self.assertIn("allow_legacy_engine_control", source)
        self.assertLess(source.index("allow_legacy_engine_control"), source.index("engine_control("))


if __name__ == "__main__":
    unittest.main()
