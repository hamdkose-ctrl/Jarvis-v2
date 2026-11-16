"""Versioned JSON-only Brain -> Core handoff boundary.

The outer API accepts and returns serialized JSON TEXT.  EntryResult,
ContextReference, GateObservation and other Python objects are never accepted
as wire input.  Core constructs fresh, validated local values after decoding;
the Brain's original object identity and references cannot cross the boundary.
No permission, execution or completion authority is conferred by a message.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import json
from typing import Any

from modules.brain_contracts import (
    ActiveContext, BrainFeedback, ContextReference, EchoPreview,
    UnderstandingResult,
)
from modules.brain_gates import GateObservation

SCHEMA = "jarvis.brain-core.handoff"
RESULT_SCHEMA = "jarvis.brain-core.result"
VERSION = 1
MAX_WIRE_BYTES = 2 * 1024 * 1024
_ENTRY_KEYS = frozenset({
    "schema", "version", "owner", "request_id", "source", "text", "stage",
    "active_context", "state_gate", "fast_gate", "candidates", "references",
    "state_references", "understanding", "batch_child",
})
_REF_FIELDS = (
    "active_goal_references", "goal_candidates", "active_task_references",
    "recent_references", "active_artifacts", "pending_references", "memory_references",
)
_AUTHORITY = frozenset({
    "allowed", "permission", "permission_granted", "approved", "authorized",
    "completed", "done", "effect_allowed", "execute",
})


@dataclass(frozen=True)
class EntryResult:
    owner: str
    request_id: str
    source: str
    text: str
    active_context: ActiveContext
    state_gate: GateObservation
    fast_gate: GateObservation | None = None
    candidates: tuple[ContextReference, ...] = ()
    references: tuple[ContextReference, ...] = ()
    understanding: Any = None
    batch_child: bool = False
    state_references: tuple[ContextReference, ...] = ()

    @property
    def stage(self) -> str:
        if self.state_gate.reason_code == "MULTIPLE_BOUNDED_STATE_MATCHES":
            return "clarify"
        if self.state_gate.matched:
            return "state"
        if self.fast_gate is not None and self.fast_gate.matched:
            return "fast"
        return "understanding"

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "owner": self.owner,
            "request_id": self.request_id,
            "source": self.source,
            "text": self.text,
            "stage": self.stage,
            "state_gate": self.state_gate.to_dict(),
            "fast_gate": self.fast_gate.to_dict() if self.fast_gate is not None else None,
        }
        if self.understanding is not None:
            result["understanding"] = self.understanding.to_dict()
        if _AUTHORITY.intersection(result):
            raise ValueError("Brain entry authority alanı taşıyamaz.")
        return result

    def to_handoff_json(self) -> str:
        """Serialize the complete observation before the Brain/Core boundary.

        Unlike to_dict (a small display projection), this is the only
        complete, versioned input for the Core wire adapter.
        """
        return encode_entry(self)


def _only(value: Any, keys: frozenset[str], name: str) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise ValueError(f"{name} JSON şeması geçersiz.")
    return value


def _fields(cls: type) -> frozenset[str]:
    return frozenset(field.name for field in fields(cls))


def _pairs(rows: list[tuple[str, Any]]) -> dict:
    value = {}
    for key, item in rows:
        if key in value:
            raise ValueError("JSON yinelenen alan içeriyor.")
        value[key] = item
    return value


def _bad_constant(value: str) -> None:
    raise ValueError("JSON NaN/Infinity içeremez.")


def _dump(value: dict) -> str:
    result = json.dumps(value, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":"), allow_nan=False)
    if len(result.encode("utf-8")) > MAX_WIRE_BYTES:
        raise ValueError("Brain/Core JSON boyutu sınırı aşıldı.")
    return result


def _load(text: str) -> dict:
    if type(text) is not str or len(text.encode("utf-8")) > MAX_WIRE_BYTES:
        raise ValueError("Brain/Core sınırı yalnız sınırlı JSON metni kabul eder.")
    try:
        parsed = json.loads(text, object_pairs_hook=_pairs,
                            parse_constant=_bad_constant)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Brain/Core JSON geçersiz.") from exc
    if type(parsed) is not dict:
        raise ValueError("Brain/Core JSON nesnesi gerekli.")
    return parsed


def _refs(rows: Any, owner: str, name: str) -> tuple[ContextReference, ...]:
    if type(rows) is not list:
        raise ValueError(f"{name} JSON listesi olmalı.")
    result = []
    for row in rows:
        raw = _only(row, _fields(ContextReference), name + ".reference")
        ref = ContextReference(**raw)
        if ref.owner != owner:
            raise ValueError("Brain/Core JSON başka sahibin referansını taşıyamaz.")
        result.append(ref)
    return tuple(result)


def _gate(row: Any, owner: str, rid: str, gate: str) -> GateObservation:
    raw = _only(row, _fields(GateObservation), gate)
    if (raw["owner"], raw["request_id"], raw["gate"]) != (owner, rid, gate):
        raise ValueError("Brain/Core geçit owner/request uyuşmuyor.")
    if (type(raw["matched"]) is not bool or
            not isinstance(raw["reason_code"], str) or not raw["reason_code"] or
            (raw["protocol"] is not None and type(raw["protocol"]) is not str) or
            (raw["selection"] is not None and type(raw["selection"]) not in (str, int))):
        raise ValueError("Brain/Core geçit gözlemi geçersiz.")
    return GateObservation(**raw)


def encode_entry(entry: Any, *, _core_internal: bool = False) -> str:
    """Brain-owned immutable observation -> a standalone, inert JSON string."""
    from modules.brain_entry import EntryResult
    if type(entry) is not EntryResult or (entry.batch_child and not _core_internal):
        raise ValueError("Handoff yalnız kök Brain gözlemi kabul eder.")
    value = {
        "schema": SCHEMA, "version": VERSION,
        "owner": entry.owner, "request_id": entry.request_id,
        "source": entry.source, "text": entry.text, "stage": entry.stage,
        "active_context": entry.active_context.to_dict(),
        "state_gate": entry.state_gate.to_dict(),
        "fast_gate": entry.fast_gate.to_dict() if entry.fast_gate is not None else None,
        "candidates": [row.to_dict() for row in entry.candidates],
        "references": [row.to_dict() for row in entry.references],
        "state_references": [row.to_dict() for row in entry.state_references],
        "understanding": (
            entry.understanding.to_dict() if entry.understanding is not None else None
        ),
        "batch_child": entry.batch_child,
    }
    return _dump(value)


def decode_entry(message: str, *, _core_internal: bool = False):
    """Core input validation; builds a NEW local value, never borrows Brain state."""
    from modules.brain_entry import EntryResult
    row = _only(_load(message), _ENTRY_KEYS, "Handoff")
    if row["schema"] != SCHEMA or type(row["version"]) is not int or row["version"] != VERSION:
        raise ValueError("Brain/Core bilinmeyen JSON kontrat sürümü.")
    owner, rid = row["owner"], row["request_id"]
    if (type(owner) is not str or not owner or len(owner) > 100
            or type(rid) is not str or not rid or len(rid) > 128
            or type(row["source"]) is not str or not row["source"]
            or type(row["text"]) is not str or not row["text"].strip()
            or (row["batch_child"] is not False
                and not (_core_internal and row["batch_child"] is True))):
        raise ValueError("Handoff owner/request/text sınırı geçersiz.")
    ctx = dict(_only(row["active_context"], _fields(ActiveContext), "ActiveContext"))
    if (ctx["owner"], ctx["request_id"]) != (owner, rid):
        raise ValueError("Handoff ActiveContext owner/request uyuşmuyor.")
    for field in _REF_FIELDS:
        ctx[field] = _refs(ctx[field], owner, "active_context." + field)
    active = ActiveContext(**ctx)
    semantic = None
    if row["understanding"] is not None:
        raw = dict(_only(row["understanding"], _fields(UnderstandingResult),
                         "UnderstandingResult"))
        if (raw["owner"], raw["request_id"]) != (owner, rid):
            raise ValueError("Handoff Understanding owner/request uyuşmuyor.")
        raw["references"] = _refs(raw["references"], owner, "understanding.references")
        if raw["preview"] is not None:
            raw["preview"] = EchoPreview(**_only(
                raw["preview"], _fields(EchoPreview), "understanding.preview",
            ))
        semantic = UnderstandingResult(**raw)
    entry = EntryResult(
        owner=owner, request_id=rid, source=row["source"], text=row["text"],
        active_context=active,
        state_gate=_gate(row["state_gate"], owner, rid, "state"),
        fast_gate=(_gate(row["fast_gate"], owner, rid, "fast")
                   if row["fast_gate"] is not None else None),
        candidates=_refs(row["candidates"], owner, "candidates"),
        references=_refs(row["references"], owner, "references"),
        state_references=_refs(row["state_references"], owner, "state_references"),
        understanding=semantic, batch_child=row["batch_child"],
    )
    if row["stage"] != entry.stage or type(row["stage"]) is not str:
        raise ValueError("Handoff aşama/gate uyuşmuyor.")
    return entry


def _restore_feedback(value: Any) -> BrainFeedback:
    raw = dict(_only(value, _fields(BrainFeedback), "CoreFeedback"))
    owner = raw["owner"]
    raw["candidates"] = _refs(raw["candidates"], owner, "feedback.candidates")
    raw["evidence"] = _refs(raw["evidence"], owner, "feedback.evidence")
    return BrainFeedback(**raw)


def encode_feedback(feedback: BrainFeedback | None) -> str | None:
    """Store only an inert JSON snapshot for legacy error reporting."""
    if feedback is None:
        return None
    if type(feedback) is not BrainFeedback:
        raise ValueError("Feedback yalnız doğrulanmış taşıyıcı olmalı.")
    return _dump({
        "schema": "jarvis.brain-core.feedback",
        "version": VERSION, "feedback": feedback.to_dict(),
    })


def decode_feedback(message: str | None) -> BrainFeedback | None:
    if message is None:
        return None
    row = _only(_load(message), frozenset({"schema", "version", "feedback"}),
                "LegacyFeedback")
    if row["schema"] != "jarvis.brain-core.feedback" or type(row["version"]) is not int or row["version"] != VERSION:
        raise ValueError("Feedback JSON sürümü geçersiz.")
    return _restore_feedback(row["feedback"])


def encode_result(output: Any, feedback: BrainFeedback, job_id: str | None,
                  *, owner: str, request_id: str) -> str:
    """Only JSON text leaves Core, never ActionOutcome or BrainFeedback objects."""
    if (type(feedback) is not BrainFeedback or feedback.owner != owner
            or feedback.request_id != request_id):
        raise ValueError("Core yanıtı owner/request uyuşmuyor.")
    if job_id is not None and type(job_id) is not str:
        raise ValueError("Core job kimliği JSON metni olmalı.")
    return _dump({
        "schema": RESULT_SCHEMA, "version": VERSION, "owner": owner,
        "request_id": request_id,
        "output": None if output is None else str(output),
        "feedback": feedback.to_dict(), "job_id": job_id,
    })


def decode_result(message: str, *, owner: str, request_id: str) -> dict:
    """Read a verified Core JSON result at a UI surface; no Python DTO returns."""
    row = _only(_load(message), frozenset({
        "schema", "version", "owner", "request_id", "output", "feedback", "job_id",
    }), "CoreResult")
    if (row["schema"] != RESULT_SCHEMA or type(row["version"]) is not int
            or row["version"] != VERSION or row["owner"] != owner
            or row["request_id"] != request_id or
            (row["output"] is not None and type(row["output"]) is not str) or
            (row["job_id"] is not None and type(row["job_id"]) is not str)):
        raise ValueError("Core JSON sonucu owner/request/sürüm uyuşmuyor.")
    fb = _restore_feedback(row["feedback"])
    if fb.owner != owner or fb.request_id != request_id:
        raise ValueError("Core feedback kimliği uyuşmuyor.")
    return row
