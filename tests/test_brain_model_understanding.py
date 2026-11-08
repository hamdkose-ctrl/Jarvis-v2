"""BRAIN-01: birincil model zarfının sınırları (ücretsiz rota, tek çağrı, Core yeniden doğrulama).

Zarf biçimi ``brain-understanding.v2``dir; eski "yalnız tipli alan cilalama" sözleşmesi
BRAIN-01'de kaldırıldığı için bu dosyadaki beklentiler modelin karar üretebildiğini,
yetkinin ise Core'da kaldığını birlikte doğrular.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
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


def action(capability_id, arguments=None, slots=None, *, action_id="a1"):
    return {
        "action_id": action_id,
        "capability_id": capability_id,
        "arguments": arguments or {},
        "reference_slots": slots or [],
        "depends_on": [],
    }


def answer(**changes):
    values = {
        "schema_version": model.SCHEMA_VERSION,
        "operation": "chat",
        "conversation_relation": "NEW_REQUEST",
        "temporal_need": "STATIC",
        "target_goal_ids": [],
        "goal": None,
        "actions": [],
        "clarification": {"required": False, "question": None, "reason_code": None},
        "confidence": "LOW",
    }
    values.update(changes)
    return json.dumps(values)


def direct(capability_id, arguments=None, slots=None, **changes):
    changes.setdefault("confidence", "MEDIUM")
    return answer(operation="direct_action",
                  actions=[action(capability_id, arguments, slots)], **changes)


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

    def ask(self, raw, text="rapor dosyasını özetle", *, active=None, args=None, **kwargs):
        active = current() if active is None else active
        p1, p2, p3 = self.eligible()
        with p1, p2, p3, patch("modules.smart_router.run", return_value=raw):
            return model.propose(owner=OWNER, text=text, current=active,
                                 arguments=(active.arguments if args is None else args), **kwargs)

    def test_model_can_conservatively_downgrade_false_capability_to_chat(self):
        result = self.ask(answer())
        self.assertIsNotNone(result)
        self.assertEqual(result.operation, "chat")
        self.assertIs(result.temporal_need, TemporalNeed.STATIC)

    def test_owner_mismatch_never_uses_another_profiles_provider_key(self):
        with patch("modules.llm.current_user", return_value="other"), \
                patch("modules.smart_router.run") as run:
            result = model.propose(owner=OWNER, text="rapor", current=current(),
                                   arguments=current().arguments)
        self.assertIsNone(result)
        run.assert_not_called()

    def test_paid_provider_is_never_used_by_brain_understanding(self):
        with patch("modules.llm.provider", return_value="openai"), patch("modules.smart_router.run") as ask:
            result = model.propose(owner=OWNER, text="rapor", current=current(),
                                   arguments=current().arguments)
        self.assertIsNone(result)
        ask.assert_not_called()

    def test_local_ollama_is_not_silently_started_or_selected(self):
        with patch("modules.llm.provider", return_value="ollama"), patch("modules.smart_router.run") as ask:
            result = model.propose(owner=OWNER, text="rapor", current=current(),
                                   arguments=current().arguments)
        self.assertIsNone(result)
        ask.assert_not_called()

    def test_no_verified_free_provider_means_no_model_call(self):
        p1, p2, _ = self.eligible()
        with p1, p2, patch("modules.smart_router.selection", return_value={"candidates": ["ollama"]}), \
                patch("modules.smart_router.run") as ask:
            result = model.propose(owner=OWNER, text="rapor", current=current(),
                                   arguments=current().arguments)
        self.assertIsNone(result)
        ask.assert_not_called()

    def test_unknown_capability_is_rejected(self):
        self.assertIsNone(self.ask(direct("shell.execute", {"cmd": "dir"})))

    def test_capability_requires_independent_core_argument_validation(self):
        self.assertIsNone(self.ask(direct("files.read"), args={"execute": True}))

    def test_model_cannot_upgrade_confidence_or_rewrite_pending_relation(self):
        self.assertIsNone(self.ask(answer(confidence="HIGH")))

        pending = current(conversation_relation=ConversationRelation.ANSWER_TO_PENDING)
        self.assertIsNone(self.ask(answer(conversation_relation="NEW_REQUEST"),
                                   active=pending, args=pending.arguments, protected_relation=True))

    def test_malformed_json_fails_closed(self):
        self.assertIsNone(self.ask("not json"))

    def test_protocol_still_rejects_named_wrapper_and_wrong_version(self):
        with self.assertRaises(ValueError):
            model._decode(json.dumps({model.SCHEMA_VERSION:json.loads(answer())}))
        with self.assertRaises(ValueError):
            model._decode(answer(schema_version='invented-version'))

    def test_request_cancellation_propagates_instead_of_becoming_chat_fallback(self):
        from modules import requests_state
        p1, p2, p3 = self.eligible()
        with p1, p2, p3, patch("modules.smart_router.run",
                               side_effect=requests_state.Cancelled("cancelled")):
            with self.assertRaises(requests_state.Cancelled):
                model.propose(owner=OWNER, text="rapor", current=current(), arguments=current().arguments)

    def test_model_timeout_fails_closed_without_changing_existing_proposal(self):
        p1, p2, p3 = self.eligible()
        with p1, p2, p3, patch("modules.smart_router.run", side_effect=TimeoutError("late")):
            result = model.propose(owner=OWNER, text="rapor", current=current(),
                                   arguments=current().arguments)
        self.assertIsNone(result)

    def test_model_cannot_create_a_clarification_without_a_typed_reason(self):
        raw = answer(operation="clarify", confidence="MEDIUM",
                     clarification={"required": True, "question": "Hangisini?", "reason_code": None})
        self.assertIsNone(self.ask(raw))

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
        raw = direct("files.read", {"operation": "analyze"}, ["file_0"])
        with patch("modules.brain_core_map._validated_file_path", side_effect=lambda value: value):
            result = self.ask(raw, text="şu raporu bir incele", active=active)
            self.assertIsNotNone(result)
            self.assertEqual(result.actions[0].capability_id, "files.read")
            self.assertEqual(dict(result.actions[0].arguments), {
                "original_text": "şu raporu bir incele",
                "operation": "analyze",
                "path": "C:/Users/hamdi/Documents/rapor.pdf",
            })
            self.assertEqual(
                core_plan(result.actions[0].capability_id, result.actions[0].arguments),
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
        self.assertIsNone(self.ask(direct("files.read", {"operation": "analyze"}, ["file_9"]),
                                   text="şu raporu incele", active=active))
        self.assertIsNone(self.ask(
            direct("files.read", {"operation": "analyze", "path": "C:/secret.txt"}, ["file_0"]),
            text="şu raporu incele", active=active))

    def test_model_can_move_an_established_capability_to_another_domain(self):
        """BRAIN-01: `current.capability_hint` öneri ön koşulu değildir; Core argümanı doğrular."""
        active = current(capability_hint="notes.read", arguments={"original_text": "notları göster"})
        result = self.ask(direct("pc.level.set", {"property": "volume", "level": 40}),
                          text="notları göster", active=active)
        self.assertIsNotNone(result)
        self.assertEqual(result.actions[0].capability_id, "pc.level.set")

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
        self.assertIsNone(self.ask(direct("files.read", {"operation": "analyze"}, ["file_0"]),
                                   active=active))
        self.assertIsNone(self.ask(direct("files.read", {"operation": "summarize"}, ["file_1"]),
                                   active=active))

    def test_model_understanding_token_limit_is_separate_from_time_budget(self):
        from modules import requests_state
        raw = answer(confidence="MEDIUM")

        def through_router(owner, prompt, callback, **kwargs):
            return callback("groq")
        p1, p2, p3 = self.eligible()
        with p1, p2, p3, patch("modules.smart_router.run", side_effect=through_router), \
                patch.object(requests_state, "budget", wraps=requests_state.budget) as budget, \
                patch("modules.llm._send_provider", return_value=raw) as send:
            result = model.propose(owner=OWNER, text="rapor dosyasını özetle",
                                   current=current(), arguments=current().arguments)
        self.assertIsNotNone(result)
        self.assertIs(type(send.call_args.args[3]), int)
        self.assertEqual(send.call_args.args[3], 2048)
        budget.assert_called_once_with(12)

    def test_production_groq_http_payload_accepts_brain_token_limit(self):
        raw = answer(confidence="MEDIUM")
        response = SimpleNamespace(status_code=200, headers={},
            json=lambda: {"choices": [{"message": {"content": raw}}]})

        def through_router(owner, prompt, callback, **kwargs):
            return callback("groq")

        def accept_request(url, **kwargs):
            body = kwargs['json']
            self.assertIs(type(body['max_tokens']), int)
            self.assertEqual(body['max_tokens'], 2048)
            prompt=json.loads(body['messages'][-1]['content'])
            schema=prompt['response_schema']
            self.assertEqual(set(schema['required']),model.ENVELOPE_KEYS)
            self.assertEqual(set(schema['properties']),model.ENVELOPE_KEYS)
            self.assertEqual(schema['properties']['schema_version'],{'const':model.SCHEMA_VERSION})
            self.assertFalse(schema['additionalProperties'])
            self.assertEqual(set(schema['properties']['actions']['items']['required']),model.ACTION_KEYS)
            self.assertIn('without a named wrapper',body['messages'][0]['content'])
            self.assertIn('Set argument_sources to null',body['messages'][0]['content'])
            return response

        p1, p2, p3 = self.eligible()
        with p1, p2, p3, patch("modules.smart_router.run", side_effect=through_router), \
                patch("modules.llm.user_groq_key", return_value="test-only"), \
                patch("modules.llm.groq_model", return_value="openai/gpt-oss-120b"), \
                patch("modules.smart_router.settings", return_value={}), \
                patch("modules.llm._fallback_states", {}), \
                patch("modules.llm._limited", return_value=None), \
                patch("modules.llm._timed", side_effect=lambda name, fn: fn()), \
                patch("modules.usage_meter.record"), patch("modules.usage_meter.observe_limits"), \
                patch("modules.llm.requests.post", side_effect=accept_request) as post:
            result = model.propose(owner=OWNER, text="rapor dosyasını özetle",
                                   current=current(), arguments=current().arguments)
        self.assertIsNotNone(result)
        post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
