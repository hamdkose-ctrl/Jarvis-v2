"""Canonical production entry for the non-authoritative Brain foundation.

This module composes the already-merged Brain context/gates/reference/understanding
layers. It never grants permission, runs an effect, selects a worker, or marks
work complete. Existing Core/domain handlers remain the only execution path.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from modules import brain_context, capability_manifest
from modules.brain_candidates import build_candidates
from modules.brain_contracts import (
    ActiveContext,
    BrainFeedback,
    ContextReference,
    ConversationRelation,
    RequestKind,
)
from modules.brain_gates import GateObservation, deterministic_fast_gate, exact_state_gate
from modules.brain_reference import resolve_references
from modules.brain_understanding import understand

_CURRENT: ContextVar["EntryResult | None"] = ContextVar("jarvis_brain_entry", default=None)
_RESERVED = frozenset({
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
        if _RESERVED.intersection(result):
            raise ValueError("Brain entry authority alanı taşıyamaz.")
        return result


def _required(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} boş olamaz.")
    return value


def _runtime_owner(runtime: Any) -> str:
    profile = getattr(runtime, "profile", None)
    return str(getattr(profile, "slug", "") or "").strip()


def _verify_activation(runtime: Any, owner: str, request_id: str) -> None:
    requests = getattr(runtime, "requests_state", None)
    current_request = getattr(requests, "_current", None)
    if current_request is None or not hasattr(current_request, "get"):
        return
    active = current_request.get()
    if active != (owner, request_id):
        raise ValueError("Canonical Brain yalnız aktif owner/request içinde çalışabilir.")


def photo_artifact(*, owner: str, request_id: str, path: str) -> ContextReference:
    owner = _required("owner", owner)
    request_id = _required("request_id", request_id)
    path = _required("path", path)
    return ContextReference(
        id="photo:" + path,
        kind="photo",
        source="engine_queue.photo",
        owner=owner,
        provenance={"path": path, "origin_request_id": request_id},
    )


def _append_artifact(active: ActiveContext, artifact: ContextReference | None) -> ActiveContext:
    if artifact is None:
        return active
    if not isinstance(artifact, ContextReference):
        raise ValueError("artifact ContextReference olmalı.")
    if artifact.owner != active.owner:
        raise ValueError("Photo artifact başka owner'a ait olamaz.")
    artifacts = active.active_artifacts
    if not any(row is artifact or (row.kind, row.id) == (artifact.kind, artifact.id) for row in artifacts):
        artifacts = artifacts + (artifact,)
    return ActiveContext(
        owner=active.owner,
        request_id=active.request_id,
        topic=active.topic,
        active_goal_references=active.active_goal_references,
        active_task_references=active.active_task_references,
        recent_references=active.recent_references,
        active_artifacts=artifacts,
        pending_references=active.pending_references,
        memory_references=active.memory_references,
    )


def _pending_photo_artifact(runtime: Any, owner: str) -> ContextReference | None:
    row = getattr(runtime, "_pending_photo", {}).get(owner)
    if not isinstance(row, dict) or not row.get("path"):
        return None
    origin = str(row.get("origin_request_id") or "legacy-photo")
    return photo_artifact(owner=owner, request_id=origin, path=str(row["path"]))


def _build_context(runtime: Any, owner: str, request_id: str,
                   artifact: ContextReference | None = None) -> ActiveContext:
    active = brain_context.build_active_context(
        owner=owner,
        request_id=request_id,
        session_store=getattr(runtime, "_sessions", None),
        profile=getattr(runtime, "profile", None),
    )
    if active.owner != owner or active.request_id != request_id:
        raise ValueError("ActiveContext owner/request fence eşleşmiyor.")
    active = _append_artifact(active, _pending_photo_artifact(runtime, owner))
    return _append_artifact(active, artifact)


def _state_refs(runtime: Any, owner: str, request_id: str) -> tuple[ContextReference, ...]:
    rows: list[ContextReference] = []
    try:
        from modules import job_front
        job = job_front.observe(owner)
    except Exception:
        job = None
    if isinstance(job, dict) and job.get("id"):
        rows.append(ContextReference(
            id=str(job["id"]), kind="task_job", source="task_agents", owner=owner,
            provenance={
                "state": str(job.get("state") or ""),
                "updated": job.get("updated"),
                "stale": bool(job.get("stale")),
            },
        ))

    profile = getattr(runtime, "profile", None)
    data = getattr(profile, "data", None)
    pending_facts = data.get("pending_facts") if isinstance(data, dict) else None
    if isinstance(pending_facts, list) and pending_facts:
        rows.append(ContextReference(
            id="pending_facts", kind="pending_state", source="learning", owner=owner,
            provenance={"value": list(pending_facts)},
        ))

    try:
        from modules import desktop_agent
        desktop = desktop_agent._load(owner)
    except Exception:
        desktop = None
    if isinstance(desktop, dict) and desktop.get("status") == "consent":
        rows.append(ContextReference(
            id="consent", kind="pending_state", source="desktop_agent", owner=owner,
            provenance={"status": "consent"},
        ))

    photo = getattr(runtime, "_pending_photo", {}).get(owner)
    if isinstance(photo, dict) and photo.get("path"):
        rows.append(ContextReference(
            id="pending_photo", kind="pending_state", source="engine_commands", owner=owner,
            provenance={
                "path": str(photo.get("path")),
                "t": photo.get("t"),
                "origin_request_id": photo.get("origin_request_id"),
            },
        ))
    return tuple(rows)


def prepare(runtime: Any, *, owner: str, request_id: str, text: str, source: str,
            artifact: ContextReference | None = None) -> EntryResult:
    """Build one canonical Brain observation/proposal for the already-active request."""
    owner = _required("owner", owner)
    request_id = _required("request_id", request_id)
    if not isinstance(text, str):
        raise ValueError("text string olmalı.")
    source = _required("source", source)
    if _runtime_owner(runtime) != owner:
        raise ValueError("Brain request owner aktif profile ile eşleşmiyor.")
    _verify_activation(runtime, owner, request_id)

    active = _build_context(runtime, owner, request_id, artifact)
    if active.owner != owner or active.request_id != request_id:
        raise ValueError("ActiveContext owner/request fence eşleşmiyor.")
    state_refs = _state_refs(runtime, owner, request_id)
    state = exact_state_gate(
        owner=owner, request_id=request_id, text=text,
        active_context=active, state_references=state_refs,
    )
    if state.matched or state.reason_code == "MULTIPLE_BOUNDED_STATE_MATCHES":
        return EntryResult(owner, request_id, source, text, active, state)

    fast = deterministic_fast_gate(
        owner=owner, request_id=request_id, text=text, active_context=active,
        sleeping=bool(getattr(runtime, "flags", {}).get("sleep")), source=source,
    )
    if fast.matched:
        return EntryResult(owner, request_id, source, text, active, state, fast)

    candidates = build_candidates(
        owner=owner, request_id=request_id, text=text,
        active_context=active, profile=getattr(runtime, "profile", None),
    )
    references = resolve_references(
        owner=owner, request_id=request_id, text=text,
        active_context=active, candidates=candidates,
    )
    semantic = understand(
        owner=owner, request_id=request_id, text=text,
        active_context=active, candidates=candidates, references=references,
    )
    if semantic.owner != owner or semantic.request_id != request_id:
        raise ValueError("Understanding owner/request fence eşleşmiyor.")
    return EntryResult(owner, request_id, source, text, active, state, fast, candidates, references, semantic)


def core_proposal(entry: EntryResult) -> dict[str, object]:
    """Return metadata for Core validation; never return an execution decision."""
    if not isinstance(entry, EntryResult):
        raise ValueError("entry EntryResult olmalı.")
    hint = entry.understanding.capability_hint if entry.understanding is not None else None
    manifest_id = None
    if hint:
        try:
            ids = {str(row.get("id")) for row in capability_manifest.catalog().get("capabilities", [])}
        except Exception:
            ids = set()
        if hint in ids:
            manifest_id = hint
    proposal = {
        "owner": entry.owner,
        "request_id": entry.request_id,
        "stage": entry.stage,
        "protocol": entry.state_gate.protocol if entry.state_gate.matched else (
            entry.fast_gate.protocol if entry.fast_gate is not None and entry.fast_gate.matched else None
        ),
        "request_kind": entry.understanding.request_kind.value if entry.understanding is not None else None,
        "capability_hint": hint,
        "manifest_capability_id": manifest_id,
    }
    if _RESERVED.intersection(proposal):
        raise ValueError("Core proposal authority alanı taşıyamaz.")
    return proposal


def clarification(entry: EntryResult) -> str | None:
    if entry.state_gate.reason_code == "MULTIPLE_BOUNDED_STATE_MATCHES":
        return "Birden fazla bekleyen kesin işlem aynı cevaba uyuyor; hangisini kastettiğini netleştir."
    semantic = entry.understanding
    if semantic is None or (not semantic.needs_input and semantic.request_kind is not RequestKind.CLARIFY):
        return None
    if "multiple target references" in semantic.ambiguities:
        return "Birden fazla hedef eşleşti; hangisini kastettiğini netleştir."
    return "İsteğini güvenli biçimde sürdürebilmem için neyi kastettiğini netleştir."


def feedback(entry: EntryResult, *, result_status: str,
             reason_code: str | None = None) -> BrainFeedback:
    return BrainFeedback(
        owner=entry.owner,
        request_id=entry.request_id,
        result_status=_required("result_status", result_status),
        reason_code=reason_code,
    )


@contextmanager
def bind(entry: EntryResult):
    if not isinstance(entry, EntryResult):
        raise ValueError("entry EntryResult olmalı.")
    token = _CURRENT.set(entry)
    try:
        yield entry
    finally:
        _CURRENT.reset(token)


def current() -> EntryResult | None:
    return _CURRENT.get()


def _correlated_job_id(entry: EntryResult) -> str | None:
    try:
        from modules import goal_executor
        row = goal_executor.latest(entry.owner)
    except Exception:
        return None
    if not isinstance(row, dict):
        return None
    meta = row.get("brain")
    if not isinstance(meta, dict) or meta.get("request_id") != entry.request_id:
        return None
    ident = row.get("id")
    return str(ident) if ident else None


def _legacy_route_projection(entry: EntryResult) -> dict[str, object]:
    """Legacy-dispatch compatible output built only from the canonical result.

    It never calls the old classifier. Unsupported capability hints fail closed as
    a no-effect clarification instead of being reinterpreted by a second brain.
    """
    question = clarification(entry)
    if question is not None:
        return {"intent": "clarify", "args": {"question": question}}
    if entry.state_gate.matched or (entry.fast_gate is not None and entry.fast_gate.matched):
        return {"intent": "clarify", "args": {"question": "Bounded komut Core handler tarafından işlenemedi; işlem başlatılmadı."}}
    semantic = entry.understanding
    if semantic is None:
        return {"intent": "clarify", "args": {"question": "Canonical Brain sonucu üretilemedi; işlem başlatılmadı."}}
    if semantic.request_kind is RequestKind.CAPABILITY:
        proposal = core_proposal(entry)
        if proposal["manifest_capability_id"] is None:
            return {"intent": "clarify", "args": {"question": "Capability önerisi mevcut Core manifestinde doğrulanamadı; işlem başlatılmadı."}}
        return {"intent": "task", "args": {}}
    if semantic.request_kind is RequestKind.CONTEXT_CONTROL:
        return {"intent": "chat", "args": {}}
    return {"intent": "chat", "args": {}}


def _install_route_guard(runtime: Any) -> None:
    """Wrap runtime.route once; bound requests never invoke the legacy classifier."""
    if getattr(runtime, "_brain_route_guard_installed", False):
        return
    original = getattr(runtime, "route", None)
    if not callable(original):
        return

    def guarded(command: str):
        entry = current()
        if entry is None:
            return original(command)
        return _legacy_route_projection(entry)

    runtime._brain_legacy_route = original
    runtime.route = guarded
    runtime._brain_route_guard_installed = True


def _has_pending(entry: EntryResult, field: str) -> bool:
    return any(
        ref.source == "session_state" and ref.id == field
        for ref in entry.active_context.pending_references
    )


def _use_existing_handler(entry: EntryResult) -> bool:
    if entry.state_gate.matched or (entry.fast_gate is not None and entry.fast_gate.matched):
        return True
    semantic = entry.understanding
    if semantic is None:
        return False
    if semantic.conversation_relation is ConversationRelation.ANSWER_TO_PENDING:
        return True
    if semantic.conversation_relation is ConversationRelation.CONTINUE_ACTIVE and any(
        row.kind == "photo" for row in semantic.references
    ):
        return True
    if semantic.request_kind is RequestKind.CAPABILITY:
        # An unrelated open-ended pending pocket must never steal a new capability request.
        if any(_has_pending(entry, field) for field in ("pending_weather_location", "pending_request", "pending_msg")):
            return False
        return True
    return False


def handoff(runtime: Any, entry: EntryResult, handler: Any, command: str):
    """Hand the proposal to existing Core/domain code and correlate BrainFeedback."""
    if _runtime_owner(runtime) != entry.owner:
        raise ValueError("Core handoff owner eşleşmiyor.")
    question = clarification(entry)
    if question is not None:
        return question, feedback(entry, result_status="needs_input", reason_code="BRAIN_CLARIFICATION_REQUIRED"), None
    if not callable(handler):
        raise ValueError("Core handler callable olmalı.")
    _install_route_guard(runtime)
    with bind(entry):
        if _use_existing_handler(entry):
            output = handler(command)
        else:
            semantic = entry.understanding
            if semantic is not None and semantic.request_kind is RequestKind.CONTEXT_CONTROL:
                output = "Tamam. Yeni isteğini mevcut business state'i değiştirmeden ayrı bağlamda ele alacağım."
            else:
                from modules.engine_intents import dispatch
                output = dispatch(runtime, "chat", {}, command, command.casefold())
    job_id = _correlated_job_id(entry)
    return output, feedback(entry, result_status="handled", reason_code="CORE_HANDOFF_RETURNED"), job_id


def execution_metadata(owner: str) -> dict[str, object] | None:
    entry = current()
    if entry is None:
        return None
    if entry.owner != owner:
        raise ValueError("Brain/Core execution owner eşleşmiyor.")
    proposal = core_proposal(entry)
    return {
        "request_id": entry.request_id,
        "stage": entry.stage,
        "request_kind": proposal.get("request_kind"),
        "capability_hint": proposal.get("capability_hint"),
        "manifest_capability_id": proposal.get("manifest_capability_id"),
    }


def matched_protocol(*protocols: str) -> bool:
    entry = current()
    return bool(entry is not None and entry.state_gate.matched and entry.state_gate.protocol in protocols)


def open_pending_answer(entry: EntryResult, field: str) -> bool:
    """Only let legacy open-ended pockets consume when canonical semantics supports it."""
    if not isinstance(entry, EntryResult):
        return False
    if entry.state_gate.matched:
        if field == "pending_photo" and entry.state_gate.protocol == "phone_photo.cancel":
            return True
        if field == "pending_msg" and entry.state_gate.protocol == "session.pending_msg.confirm":
            return True
        return False
    semantic = entry.understanding
    if semantic is None:
        return False
    if semantic.conversation_relation in {ConversationRelation.TOPIC_CHANGE, ConversationRelation.CORRECTION}:
        return False
    if semantic.request_kind in {RequestKind.CAPABILITY, RequestKind.CONTEXT_CONTROL, RequestKind.CLARIFY}:
        return False
    if field == "pending_weather_location":
        return semantic.conversation_relation is ConversationRelation.ANSWER_TO_PENDING
    if field == "pending_photo":
        return semantic.conversation_relation is ConversationRelation.CONTINUE_ACTIVE and any(
            row.kind == "photo" for row in semantic.references
        )
    return False


def canonical_fallback(runtime: Any, command: str, cmd_lower: str) -> str:
    """Explicit no-second-classifier fallback for callers that need a string result."""
    entry = current()
    if entry is None:
        raise RuntimeError("Canonical fallback yalnız bound Brain request için kullanılabilir.")
    route = _legacy_route_projection(entry)
    if route["intent"] == "clarify":
        return str(route["args"]["question"])
    from modules.engine_intents import dispatch
    return dispatch(runtime, str(route["intent"]), dict(route["args"]), command, cmd_lower)
