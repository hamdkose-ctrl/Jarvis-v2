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
    }
    values.update(changes)
    return json.dumps(values)


class BrainModelUnderstandingTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
