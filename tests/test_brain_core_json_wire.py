"""JSON-only Brain/Core wire contract: production-shaped, fail-closed tests."""
from __future__ import annotations

from dataclasses import replace
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import brain_core_wire, brain_entry, core_brain_adapter, requests_state
from modules.brain_contracts import (
    ActiveContext, BrainFeedback, ContextReference, RequestKind, UnderstandingResult,
)
from modules.brain_gates import GateObservation

OWNER = "wire_alice"
RID = "wire-rid-123"


def entry(*, owner=OWNER, rid=RID, text="Show status", with_reference=False):
    refs = (ContextReference(
        id="note-1", kind="note", source="notes", owner=owner,
        provenance={"text": "Only this request", "path": "a.txt"},
    ),) if with_reference else ()
    return brain_entry.EntryResult(
        owner=owner, request_id=rid, source="yazı", text=text,
        active_context=ActiveContext(
            owner=owner, request_id=rid, recent_references=refs,
        ),
        state_gate=GateObservation(owner, rid, "state", False, "NO_BOUNDED_STATE_MATCH"),
        fast_gate=GateObservation(owner, rid, "fast", False, "NO_EXACT_FAST_MATCH"),
        candidates=refs,
        references=refs,
        understanding=UnderstandingResult(
            owner=owner, request_id=rid, request_kind=RequestKind.CHAT,
            arguments={"original_text": text}, references=refs,
        ),
        state_references=refs,
    )


class BrainCoreJsonWireTests(unittest.TestCase):
    def test_roundtrip_never_shares_object_or_memory_reference(self):
        original = entry(with_reference=True)
        payload = original.to_handoff_json()
        self.assertIsInstance(payload, str)
        json.loads(payload)
        cloned = brain_core_wire.decode_entry(payload)
        self.assertEqual(original, cloned)
        self.assertIsNot(original, cloned)
        self.assertIsNot(original.active_context, cloned.active_context)
        self.assertIsNot(original.candidates[0], cloned.candidates[0])
        self.assertIsNot(original.understanding, cloned.understanding)
        self.assertEqual(cloned.state_references[0].provenance["path"], "a.txt")
        self.assertIn('"schema":"jarvis.brain-core.handoff"', payload)
        self.assertNotIn("memory_address", payload)

    def test_binary_object_python_map_and_unknown_version_rejected(self):
        original = entry()
        for bad in (original, {"owner": OWNER}, b"{}", "[]", "not-json", '{"a":1,"a":2}'):
            with self.subTest(bad=type(bad).__name__), self.assertRaises(ValueError):
                brain_core_wire.decode_entry(bad)
        value = json.loads(original.to_handoff_json())
        for key, modification in (
            ("version", 2), ("batch_child", True), ("stage", "state"),
            ("owner", "another_owner"), ("execute", True),
        ):
            forged = dict(value)
            forged[key] = modification
            with self.subTest(key=key), self.assertRaises(ValueError):
                brain_core_wire.decode_entry(json.dumps(forged))
        self.assertRaises(ValueError, brain_core_wire.decode_entry,
                          original.to_handoff_json() + " trailing")

    def test_no_cross_owner_or_request_reference_or_gate_smuggling(self):
        value = json.loads(entry(with_reference=True).to_handoff_json())
        mutants = []
        foreign = json.loads(json.dumps(value))
        foreign["references"][0]["owner"] = "mallory"
        mutants.append(foreign)
        changed_gate = json.loads(json.dumps(value))
        changed_gate["state_gate"]["request_id"] = "other-rid"
        mutants.append(changed_gate)
        changed_semantic = json.loads(json.dumps(value))
        changed_semantic["understanding"]["request_id"] = "other-rid"
        mutants.append(changed_semantic)
        changed_context = json.loads(json.dumps(value))
        changed_context["active_context"]["owner"] = "mallory"
        mutants.append(changed_context)
        authority = json.loads(json.dumps(value))
        authority["understanding"]["arguments"]["approved"] = True
        mutants.append(authority)
        for idx, row in enumerate(mutants):
            with self.subTest(case=idx), self.assertRaises(ValueError):
                brain_core_wire.decode_entry(json.dumps(row))

    def test_handoff_api_accepts_only_json_and_returns_only_json(self):
        original = entry(with_reference=True)
        runtime = SimpleNamespace(
            profile=SimpleNamespace(slug=OWNER), _cur_rid=RID,
        )
        response = BrainFeedback(
            owner=OWNER, request_id=RID, result_status="handled",
            reason_code="CORE_HANDOFF_RETURNED",
        )
        with patch.object(requests_state._current, "get", return_value=(OWNER, RID)), \
             patch.object(core_brain_adapter, "handoff",
                          return_value=("done", response, None)) as core:
            encoded = core_brain_adapter.handoff_json(
                runtime, original.to_handoff_json(), Mock(), original.text,
            )
            output = brain_core_wire.decode_result(encoded, owner=OWNER, request_id=RID)
            self.assertEqual(output["output"], "done")
            self.assertEqual(output["feedback"]["result_status"], "handled")
            self.assertEqual(output["job_id"], None)
            local = core.call_args.args[1]
            self.assertIsNot(original, local)
            self.assertIsNot(original.active_context, local.active_context)
            self.assertIsNot(original.understanding, local.understanding)

            with self.assertRaises(ValueError):
                core_brain_adapter.handoff_json(runtime, original, Mock(), original.text)
            with self.assertRaises(ValueError):
                core_brain_adapter.handoff_json(runtime, original.to_handoff_json(),
                                                Mock(), "different command")
            runtime._cur_rid = "different-rid"
            with self.assertRaises(ValueError):
                core_brain_adapter.handoff_json(runtime, original.to_handoff_json(),
                                                Mock(), original.text)
            core.assert_called_once()

    def test_response_rejects_foreign_identity_or_duplicate_authority_field(self):
        feedback = BrainFeedback(owner=OWNER, request_id=RID, result_status="handled")
        text = brain_core_wire.encode_result("ok", feedback, None, owner=OWNER, request_id=RID)
        row = brain_core_wire.decode_result(text, owner=OWNER, request_id=RID)
        self.assertEqual(row["output"], "ok")
        with self.assertRaises(ValueError):
            brain_core_wire.decode_result(text, owner="mallory", request_id=RID)
        forged = json.loads(text)
        forged["feedback"]["request_id"] = "other-rid"
        with self.assertRaises(ValueError):
            brain_core_wire.decode_result(json.dumps(forged), owner=OWNER, request_id=RID)
        forged = json.loads(text)
        forged["feedback"]["authorized"] = True
        with self.assertRaises(ValueError):
            brain_core_wire.decode_result(json.dumps(forged), owner=OWNER, request_id=RID)
        with self.assertRaises(ValueError):
            brain_core_wire.encode_result("ok", replace(feedback, owner="mallory"), None,
                                         owner=OWNER, request_id=RID)


if __name__ == "__main__":
    unittest.main()
