"""Canonical production entry for the non-authoritative Brain foundation.

This module composes the already-merged Brain context/gates/reference/understanding
layers. It never grants permission, runs an effect, selects a worker, or marks
work complete. Existing Core/domain handlers remain the only execution path.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any, Mapping

from modules import brain_actions, brain_context, brain_core_map, brain_precedence, capability_manifest
from modules.brain_understanding import (
    ACTION_REQUEST_CODE,
    EXECUTION_REQUEST_CODE,
    LEVEL_CAPABILITY,
    PHOTO_FOLLOWUP_CODE,
)
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
from modules.diagnostics import record_failure as _record_failure

_CURRENT: ContextVar["EntryResult | None"] = ContextVar("jarvis_brain_entry", default=None)
_RESERVED = frozenset({
    "allowed", "permission", "permission_granted", "approved", "authorized",
    "completed", "done", "effect_allowed", "execute",
})
_FAST_ENGINE_PROTOCOLS = frozenset({"fast.engine.close", "fast.engine.sleep", "fast.engine.wake"})


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


def _append_pending(active: ActiveContext, pending: ContextReference | None) -> ActiveContext:
    if pending is None:
        return active
    if not isinstance(pending, ContextReference) or pending.owner != active.owner:
        raise ValueError("Pending state owner eşleşmiyor.")
    refs = active.pending_references
    if not any(row is pending or (row.source, row.kind, row.id) == (pending.source, pending.kind, pending.id)
               for row in refs):
        refs = refs + (pending,)
    return ActiveContext(
        owner=active.owner,
        request_id=active.request_id,
        topic=active.topic,
        active_goal_references=active.active_goal_references,
        active_task_references=active.active_task_references,
        recent_references=active.recent_references,
        active_artifacts=active.active_artifacts,
        pending_references=refs,
        memory_references=active.memory_references,
    )


_PENDING_PHOTO_STATE = ("pending_photo", "pending_state", "engine_commands")


def _app_clarify_reference(reference: ContextReference) -> bool:
    value = reference.provenance.get("value")
    proposal = value.get("proposal") if isinstance(value, Mapping) else None
    return (
        reference.id == "pending_action"
        and reference.source == "session_state"
        and reference.provenance.get("active") is True
        and isinstance(value, Mapping)
        and value.get("stage") == "clarify"
        and isinstance(proposal, Mapping)
        and proposal.get("kind") == "app.open"
    )


def _with_app_target_evidence(active: ActiveContext, runtime: Any) -> ActiveContext:
    """Attach the canonical app alias catalog while a typed app-open question is open.

    Understanding never discovers apps; the caller supplies the bounded evidence it may accept."""
    if not any(_app_clarify_reference(ref) for ref in active.pending_references):
        return active
    try:
        aliases = tuple(sorted(
            name for name in runtime.system_control.APPS
            if isinstance(name, str) and name.strip()
        ))
    except Exception:
        _record_failure("modules/brain_entry.py:app_target_evidence")
        return active
    if not aliases:
        return active
    rows = tuple(
        replace(ref, provenance={**ref.provenance, "targets": aliases})
        if _app_clarify_reference(ref) else ref
        for ref in active.pending_references
    )
    return replace(active, pending_references=rows)


def _pending_photo_state(active: ActiveContext) -> ContextReference | None:
    """The one canonical pending-photo representation, shared by ActiveContext and the gate."""
    return next(
        (row for row in active.pending_references
         if (row.id, row.kind, row.source) == _PENDING_PHOTO_STATE),
        None,
    )


def _pending_photo_reference(runtime: Any, owner: str) -> ContextReference | None:
    row = getattr(runtime, "_pending_photo", {}).get(owner)
    if not isinstance(row, dict) or not row.get("path"):
        return None
    return ContextReference(
        id="pending_photo", kind="pending_state", source="engine_commands", owner=owner,
        provenance={
            "path": str(row.get("path")),
            "t": row.get("t"),
            "origin_request_id": row.get("origin_request_id"),
        },
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
    active = _with_app_target_evidence(active, runtime)
    active = _append_artifact(active, _pending_photo_artifact(runtime, owner))
    active = _append_pending(active, _pending_photo_reference(runtime, owner))
    return _append_artifact(active, artifact)


def _state_refs(runtime: Any, owner: str, request_id: str, active: ActiveContext) -> tuple[ContextReference, ...]:
    rows: list[ContextReference] = []
    try:
        from modules import job_front
        job = job_front.observe(owner)
    except Exception:
        _record_failure("modules/brain_entry.py:job_front_observe")
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
        _record_failure("modules/brain_entry.py:desktop_consent_observe")
        desktop = None
    if isinstance(desktop, dict) and desktop.get("status") == "consent":
        rows.append(ContextReference(
            id="consent", kind="pending_state", source="desktop_agent", owner=owner,
            provenance={"status": "consent"},
        ))

    photo = _pending_photo_state(active)
    if photo is not None:
        # Aynı nesne ActiveContext'te de taşınıyor: gate ile Understanding tek canonical
        # pending-photo temsilini paylaşır.
        rows.append(photo)
    return tuple(rows)


def _semantic_pass(
    runtime: Any,
    *,
    owner: str,
    request_id: str,
    text: str,
    active: ActiveContext,
    allow_file_scan: bool,
):
    candidates = build_candidates(
        owner=owner,
        request_id=request_id,
        text=text,
        active_context=active,
        profile=getattr(runtime, "profile", None),
        allow_file_scan=allow_file_scan,
    )
    references = resolve_references(
        owner=owner,
        request_id=request_id,
        text=text,
        active_context=active,
        candidates=candidates,
    )
    semantic = understand(
        owner=owner,
        request_id=request_id,
        text=text,
        active_context=active,
        candidates=candidates,
        references=references,
    )
    if semantic.owner != owner or semantic.request_id != request_id:
        raise ValueError("Understanding owner/request fence eşleşmiyor.")
    return candidates, references, semantic


def _needs_file_discovery(references: tuple[ContextReference, ...], semantic: Any) -> bool:
    """Use resolved Understanding evidence to decide whether cold file discovery is needed."""
    return bool(
        semantic is not None
        and semantic.capability_hint == "files.read"
        and not any(reference.kind == "file" for reference in references)
    )


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
    if artifact is not None:
        if not isinstance(artifact, ContextReference) or artifact.owner != owner:
            raise ValueError("Photo artifact başka owner'a ait olamaz.")
        origin_request_id = artifact.provenance.get("origin_request_id")
        if origin_request_id is not None and str(origin_request_id) != request_id:
            raise ValueError("Current photo artifact request_id eşleşmiyor.")
    _verify_activation(runtime, owner, request_id)

    active = _build_context(runtime, owner, request_id, artifact)
    if active.owner != owner or active.request_id != request_id:
        raise ValueError("ActiveContext owner/request fence eşleşmiyor.")
    state_refs = _state_refs(runtime, owner, request_id, active)
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

    candidates, references, semantic = _semantic_pass(
        runtime,
        owner=owner,
        request_id=request_id,
        text=text,
        active=active,
        allow_file_scan=False,
    )
    if _needs_file_discovery(references, semantic):
        candidates, references, semantic = _semantic_pass(
            runtime,
            owner=owner,
            request_id=request_id,
            text=text,
            active=active,
            allow_file_scan=True,
        )
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
            _record_failure("modules/brain_entry.py:capability_manifest")
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
    specific = brain_core_map.clarification_question(semantic.ambiguities, semantic.arguments)
    if specific is not None:
        return specific
    if "multiple target references" in semantic.ambiguities:
        return "Birden fazla hedef eşleşti; hangisini kastettiğini netleştir."
    return "İsteğini güvenli biçimde sürdürebilmem için neyi kastettiğini netleştir."


def _feedback_clarification(entry: EntryResult) -> tuple[bool, tuple[str, ...], str | None]:
    if entry.state_gate.reason_code == "MULTIPLE_BOUNDED_STATE_MATCHES":
        return True, ("multiple bounded state matches",), "MULTIPLE_BOUNDED_STATE_MATCHES"
    semantic = entry.understanding
    if semantic is not None and (semantic.needs_input or semantic.request_kind is RequestKind.CLARIFY):
        return True, tuple(semantic.ambiguities), "BRAIN_CLARIFICATION_REQUIRED"
    return False, (), None


def feedback(entry: EntryResult, *, result_status: str,
             reason_code: str | None = None, recovery_class: str | None = None,
             core_ambiguities: tuple[str, ...] = ()) -> BrainFeedback:
    requested_status = _required("result_status", result_status)
    needs_input, ambiguities, clarification_reason = _feedback_clarification(entry)
    if not needs_input and core_ambiguities:
        needs_input, ambiguities, clarification_reason = True, tuple(core_ambiguities), reason_code
    return BrainFeedback(
        owner=entry.owner,
        request_id=entry.request_id,
        result_status="needs_input" if needs_input else requested_status,
        reason_code=clarification_reason if needs_input else reason_code,
        recovery_class=None if needs_input else recovery_class,
        needs_input=needs_input,
        ambiguities=ambiguities,
    )


def photo_feedback(entry: EntryResult, *, awaiting_question: bool = False,
                   error: BaseException | None = None) -> BrainFeedback:
    """Real outcome of the photo path: question pending -> needs_input, exception -> failed, cancel -> cancelled."""
    if error is not None:
        from modules import failure_policy, requests_state
        cancelled = isinstance(error, requests_state.Cancelled)
        structured = None if cancelled else failure_policy.structured_outcome(error)
        row = feedback(entry, result_status="cancelled" if cancelled else "failed",
                       reason_code="PHOTO_CANCELLED" if cancelled else (
                           structured["reason_code"] if structured else "PHOTO_HANDLER_FAILED"),
                       recovery_class=structured["recovery_class"] if structured else None)
    elif awaiting_question:
        row = feedback(entry, result_status="needs_input", reason_code="PHOTO_AWAITING_QUESTION",
                       core_ambiguities=("core pending: pending_photo",))
    else:
        row = feedback(entry, result_status="handled", reason_code="PHOTO_CORE_HANDOFF_RETURNED")
    _LAST_FEEDBACK.set(row)
    return row


_LAST_FEEDBACK: ContextVar["BrainFeedback | None"] = ContextVar("jarvis_brain_feedback", default=None)


def last_feedback() -> BrainFeedback | None:
    """BrainFeedback of the most recent handoff in this request context (also set when Core raised)."""
    return _LAST_FEEDBACK.get()


def _open_core_pending(runtime: Any) -> frozenset[str]:
    try:
        state = runtime._session()
    except Exception:
        _record_failure("modules/brain_entry.py:core_pending_snapshot")
        return frozenset()
    return frozenset(
        field for field in brain_context._PENDING_FIELDS
        if getattr(state, field, None) not in (None, False, "", (), [], {})
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


def _correlated_job_id(entry: EntryResult) -> str | None:
    try:
        from modules import goal_executor
        row = goal_executor.latest(entry.owner)
    except Exception:
        _record_failure("modules/brain_entry.py:goal_correlation")
        return None
    if not isinstance(row, dict):
        return None
    meta = row.get("brain")
    if not isinstance(meta, dict) or meta.get("request_id") != entry.request_id:
        return None
    ident = row.get("id")
    return str(ident) if ident else None


def _legacy_route_projection(entry: EntryResult) -> dict[str, object]:
    """Build a legacy-dispatch-shaped result without invoking the legacy classifier."""
    question = clarification(entry)
    if question is not None:
        return {"intent": "clarify", "args": {"question": question}}
    if entry.state_gate.matched or (entry.fast_gate is not None and entry.fast_gate.matched):
        return {"intent": "clarify", "args": {"question": "Bounded komut Core handler tarafından işlenemedi; işlem başlatılmadı."}}
    semantic = entry.understanding
    if semantic is None:
        return {"intent": "clarify", "args": {"question": "Canonical Brain sonucu üretilemedi; işlem başlatılmadı."}}
    if semantic.request_kind is RequestKind.CAPABILITY:
        plan = core_plan(entry)
        if plan is not None:
            return {"intent": plan[0], "args": dict(plan[1])}
        proposal = core_proposal(entry)
        if proposal["manifest_capability_id"] is None:
            if proposal["capability_hint"] is None and EXECUTION_REQUEST_CODE in semantic.reason_codes:
                # Tek canonical yakalama kuralı: Understanding bu cümleyi icra isteği saydı ama hiçbiri
                # doğrulanmış bir yetenekte karşılık bulmadı. Kaldırılan legacy catch-all'un successor'ı
                # olarak hedef yürütücüsü cümlenin tamamını devralır; niyet burada yeniden üretilmez.
                # Çıplak deiktik ("onu sil") yalnız Resolver bu tur için hedef bağlamadıysa hedefsizdir:
                # bağlanmış referans varsa kapı kendi başına hedef sorusu üretmez, ikinci yetki olmaz.
                if brain_actions.ambiguous_reference(entry.text) and not semantic.references:
                    return {"intent": "clarify", "args": {"question": "Hangi hedef üzerinde ne yapmamı istiyorsun?"}}
                return {"intent": "task", "args": {"request": entry.text}}
            return {"intent": "clarify", "args": {"question": "Capability önerisi mevcut Core manifestinde doğrulanamadı; işlem başlatılmadı."}}
        return {"intent": "task", "args": {}}
    return {"intent": "chat", "args": {}}


def nested_step(command: str, runtime: Any = None) -> bool:
    """True when a canonical entry is bound but this text is a different request: a sequence or macro step.

    The bound entry's decision belongs to the whole utterance, never to one of its steps.
    `handle_request`'s single typo-corrected re-run is the SAME request (same request id), so it is
    not a step; every other text that arrives while an entry is bound is."""
    entry = current()
    if entry is None or str(command).strip() == entry.text.strip():
        return False
    text = entry.text.strip()
    if text and runtime is not None and getattr(runtime, "_typo_pass", ""):
        return str(getattr(runtime, "_typo_orig", "")).strip() != text
    return True


_NESTED_STEP_QUESTION = ("Bu metin bir adımlar zincirinin adımı; cümlenin canonical kararı ona devredilmez. "
                         "Adımı ikinci kez kendim yorumlamam: adımı tek başına bir istek olarak söyle.")


def route_command(runtime: Any, command: str) -> dict[str, object]:
    """Core handler'ın tek sınıflandırılmış-istek kapısı; kendisi sınıflandırmaz.

    Bu turn'de Brain'in zaten vermiş olduğu kararın izdüşümünü verir. Bağlı bir Brain girişi
    yoksa cümle burada hiç yorumlanmaz ve istek fail-closed netleştirmeyle durur."""
    if nested_step(command, runtime):
        return {"intent": "clarify", "args": {"question": _NESTED_STEP_QUESTION}}
    entry = current()
    if entry is None:
        return {"intent": "clarify",
                "args": {"question": "Bu cümle Brain turunda yorumlanmadı; işlem başlatılmadı."}}
    return _legacy_route_projection(entry)


def _install_job_guard() -> None:
    from modules import job_front
    if getattr(job_front, "_brain_gate_guard_installed", False):
        return
    original = job_front.route

    def guarded(owner, emit, cmd_lower, session, *, photo_pending=False, bounded=False):
        canonical = matched_protocol("job.resume", "job.cancel")
        return original(owner, emit, cmd_lower, session, photo_pending=photo_pending, bounded=bounded or canonical)

    job_front._brain_legacy_route = original
    job_front.route = guarded
    job_front._brain_gate_guard_installed = True


def _install_goal_save_guard() -> None:
    """Attach metadata only to ExecutionRecord payloads; GoalState remains lean."""
    from modules import goal_executor
    if getattr(goal_executor, "_brain_save_guard_installed", False):
        return
    original = goal_executor._save

    def guarded(job):
        entry = current()
        if entry is not None and isinstance(job, dict) and job.get("owner") == entry.owner:
            job["brain"] = execution_metadata(entry.owner)
        return original(job)

    goal_executor._brain_legacy_save = original
    goal_executor._save = guarded
    goal_executor._brain_save_guard_installed = True


def allow_legacy_engine_control(entry: EntryResult | None = None) -> bool:
    """Allow legacy close/sleep/wake effects only after an exact canonical Fast match.

    Unmigrated callers remain unchanged. A canonical request that missed Fast Gate
    must never regain the broader legacy engine-control grammar later in handle().
    """
    row = current() if entry is None else entry
    if row is None:
        return True
    if not isinstance(row, EntryResult):
        raise ValueError("entry EntryResult olmalı.")
    return bool(
        row.fast_gate is not None
        and row.fast_gate.matched
        and row.fast_gate.protocol in _FAST_ENGINE_PROTOCOLS
    )


def _install_engine_control_guard() -> None:
    from modules import command_manager
    if getattr(command_manager, "_brain_engine_control_guard_installed", False):
        return
    original = command_manager.engine_control

    def guarded(normalized, *, source, sleeping, close, set_sleep):
        if not allow_legacy_engine_control():
            return None
        return original(normalized, source=source, sleeping=sleeping, close=close, set_sleep=set_sleep)

    command_manager._brain_legacy_engine_control = original
    command_manager.engine_control = guarded
    command_manager._brain_engine_control_guard_installed = True


def _install_core_guards(runtime: Any) -> None:
    _install_job_guard()
    _install_goal_save_guard()
    _install_engine_control_guard()


def _has_pending(entry: EntryResult, field: str) -> bool:
    return any(ref.source == "session_state" and ref.id == field for ref in entry.active_context.pending_references)


def _is_clarify_pending(ref: ContextReference) -> bool:
    value = ref.provenance.get("value")
    return ref.source == "session_state" and ref.id == "pending_action" and isinstance(value, Mapping) and value.get("stage") == "clarify"


def _relation_supersedes_clarify(entry: EntryResult) -> bool:
    """Does this canonical turn answer the open clarify? Only its own protocols keep it.

    The answer relation is decided by whichever canonical entry produced the turn: the state
    gate's offered-choice protocol or Understanding's ANSWER_TO_PENDING. A Fast Gate read or a
    new semantic request is not an answer, so the stale question must not survive the turn."""
    gate = entry.state_gate
    if gate.matched:
        return gate.protocol != "session.pending_action.clarify_select"
    fast = entry.fast_gate
    if fast is not None and fast.matched:
        return True
    semantic = entry.understanding
    return (semantic is not None
            and semantic.conversation_relation is not ConversationRelation.ANSWER_TO_PENDING)


def _has_open_pending(entry: EntryResult, *, ignore: frozenset[str] = frozenset()) -> bool:
    # A clarify question never blocks a new request: only an exact offered-choice answer is
    # consumed (state gate protocol session.pending_action.clarify_select); anything else is a new request.
    if any(ref.id not in ignore and not _is_clarify_pending(ref) for ref in entry.active_context.pending_references):
        return True
    return any(
        ref.kind == "photo" and ref.source == "engine_queue.photo"
        for ref in entry.active_context.active_artifacts
    )


# Protocols that may be answered before the (possibly busy) command loop: read-only,
# context-independent, exact. Anything else must go through the full canonical entry.
QUEUE_SAFE_PROTOCOLS = frozenset({"fast.goal.status"})


def fast_lane(owner: str, request_id: str, text: str, source: str = "yazı") -> GateObservation | None:
    """Pre-queue Brain lane: run only the deterministic Fast Gate on an empty context.

    Returns the observation when the exact text is a queue-safe protocol, else None
    (the caller then enqueues normally). No history, state, model or worker is touched,
    so it stays answerable while the command loop is blocked on a long goal.
    """
    context = ActiveContext(owner=owner, request_id=request_id)
    observation = deterministic_fast_gate(
        owner=owner, request_id=request_id, text=text, active_context=context, source=source,
    )
    if observation.matched and observation.protocol in QUEUE_SAFE_PROTOCOLS:
        return observation
    return None


_STEP_MARKER = re.compile(r"(?:^\s*önce\s)|(?:\s(?:ardından|akabinde)\s)|(?:\bönce\b.+\bsonra\b)", re.I)


def _multi_step(text: str) -> bool:
    """Same marker rule as engine_sequence._split_steps: a sequenced request belongs to the step runner."""
    return _STEP_MARKER.search(text.replace("İ", "i").replace("I", "ı")) is not None


def core_plan(entry: EntryResult) -> tuple[str, dict[str, object]] | None:
    """Core-validated intent for a mapped capability hint; None keeps the existing handler path."""
    if entry.state_gate.matched or (entry.fast_gate is not None and entry.fast_gate.matched):
        return None
    semantic = entry.understanding
    if semantic is None or semantic.request_kind is not RequestKind.CAPABILITY:
        return None
    if _multi_step(entry.text):
        return None
    # A fresh, explicit level request supersedes the open "ses mi parlaklık mı?" question;
    # every other open pending state still blocks the plan.
    ignore = frozenset({"pending_level"}) if semantic.capability_hint == LEVEL_CAPABILITY else frozenset()
    if _has_open_pending(entry, ignore=ignore):
        return None
    plan = brain_core_map.core_plan(semantic.capability_hint, semantic.arguments)
    if plan is not None and plan[0] in {"notes_read", "notes_write"}:
        ident = plan[1].get("id")
        # A note effect/read may target only an id Brain resolved for THIS request, never an arbitrary string.
        if ident is not None and ident not in {ref.id for ref in semantic.references if ref.kind == "note"}:
            return None
    if plan is not None and plan[0] == "file_action":
        allowed = {str(ref.provenance.get("path")) for ref in semantic.references
                   if ref.kind == "file" and isinstance(ref.provenance.get("path"), str)}
        path = plan[1].get("path")
        paths = plan[1].get("paths")
        if path is not None and path not in allowed:
            return None
        if paths is not None and (not isinstance(paths, (list, tuple)) or any(value not in allowed for value in paths)):
            return None
    if plan is not None and plan[0] == "translate" and not _translate_source_is_brains(entry, plan[1]):
        return None
    return plan


def _translate_source_is_brains(entry: EntryResult, args: Mapping[str, Any]) -> bool:
    """The text to translate must be the user's own inline text or a turn from THIS request's candidates."""
    text = str(args.get("text") or "")
    if args.get("origin") == "inline":
        return text in entry.text
    turn_id = args.get("turn_id")
    return any(ref.kind == "conversation_turn" and ref.id == turn_id
               and str(ref.provenance.get("text") or "").strip() == text for ref in entry.candidates)


def _use_existing_handler(entry: EntryResult) -> bool:
    if entry.state_gate.matched or (entry.fast_gate is not None and entry.fast_gate.matched):
        return True
    semantic = entry.understanding
    if semantic is None:
        return False
    if semantic.conversation_relation is ConversationRelation.ANSWER_TO_PENDING:
        return True
    if semantic.conversation_relation is ConversationRelation.CONTINUE_ACTIVE and any(row.kind == "photo" for row in semantic.references):
        return True
    if semantic.request_kind in {RequestKind.CAPABILITY, RequestKind.CHAT}:
        return not _has_open_pending(entry)
    return False


def _drop_stale_clarify(runtime: Any, entry: EntryResult) -> None:
    """Core-owned: a request that bypasses the legacy handler supersedes an unanswered clarify question.

    When the handler runs, ``app_actions.continue_voice`` consumes or clears it itself."""
    if any(_is_clarify_pending(ref) for ref in entry.active_context.pending_references):
        try:
            state = runtime._session()
            pending = getattr(state, "pending_action", None)
            if isinstance(pending, dict) and pending.get("stage") == "clarify":
                state.pending_action = None
        except Exception:
            _record_failure("modules/brain_entry.py:drop_stale_clarify")


def _file_access_refusal(entry: EntryResult) -> str | None:
    """A resolved file proposal rejected by Core/fence fails closed instead of legacy target guessing."""
    if entry.state_gate.matched or (entry.fast_gate is not None and entry.fast_gate.matched):
        return None
    semantic = entry.understanding
    if semantic is None or semantic.request_kind is not RequestKind.CAPABILITY or semantic.capability_hint != "files.read":
        return None
    operation = semantic.arguments.get("operation")
    if operation in (None, "list"):
        return None
    if "path" not in semantic.arguments and "paths" not in semantic.arguments:
        return None
    if core_plan(entry) is not None:
        return None
    return "Bu dosyaya erişemiyorum (izinli klasörlerin dışında, bulunamıyor veya hedef doğrulanamadı); işlem başlatılmadı."


def handoff(runtime: Any, entry: EntryResult, handler: Any, command: str):
    """Hand the proposal to existing Core/domain code and correlate BrainFeedback."""
    if _runtime_owner(runtime) != entry.owner:
        raise ValueError("Core handoff owner eşleşmiyor.")
    question = clarification(entry)
    if question is not None:
        if entry.understanding is not None:
            brain_core_map.clarification_effect(runtime, entry.understanding.ambiguities, entry.understanding.arguments)
        return question, feedback(entry, result_status="needs_input", reason_code="BRAIN_CLARIFICATION_REQUIRED"), None
    refusal = _file_access_refusal(entry)
    if refusal is not None:
        row = feedback(entry, result_status="failed", reason_code="FILE_TARGET_NOT_ACCESSIBLE")
        _LAST_FEEDBACK.set(row)
        return refusal, row, None
    if not callable(handler):
        raise ValueError("Core handler callable olmalı.")
    _install_core_guards(runtime)
    _LAST_FEEDBACK.set(None)
    before = _open_core_pending(runtime)
    try:
        with bind(entry):
            plan = core_plan(entry)
            if plan is not None or not _use_existing_handler(entry) or _relation_supersedes_clarify(entry):
                _drop_stale_clarify(runtime, entry)
            claimed = brain_precedence.claim(runtime, command, plan) if plan is not None else None
            if claimed is not None:
                output = claimed[1]
            elif plan is not None:
                from modules.engine_intents import dispatch
                output = dispatch(runtime, plan[0], dict(plan[1]), command, command.casefold())
            elif _use_existing_handler(entry):
                output = handler(command)
            elif entry.understanding is not None and entry.understanding.request_kind is RequestKind.CONTEXT_CONTROL:
                output = "Tamam. Yeni isteğini mevcut business state'i değiştirmeden ayrı bağlamda ele alacağım."
            else:
                from modules.engine_intents import dispatch
                output = dispatch(runtime, "chat", {}, command, command.casefold())
    except BaseException as exc:
        from modules import failure_policy, requests_state
        cancelled = isinstance(exc, requests_state.Cancelled)
        structured = None if cancelled else failure_policy.structured_outcome(exc)
        _LAST_FEEDBACK.set(feedback(
            entry,
            result_status="cancelled" if cancelled else "failed",
            reason_code="CORE_CANCELLED" if cancelled else (
                structured["reason_code"] if structured else "CORE_HANDLER_FAILED"),
            recovery_class=structured["recovery_class"] if structured else None,
        ))
        raise
    opened = tuple(sorted(_open_core_pending(runtime) - before))
    if opened:
        result = feedback(entry, result_status="needs_input", reason_code="CORE_AWAITING_INPUT",
                          core_ambiguities=tuple(f"core pending: {field}" for field in opened))
    else:
        result = feedback(entry, result_status="handled", reason_code="CORE_HANDOFF_RETURNED")
    _LAST_FEEDBACK.set(result)
    job_id = _correlated_job_id(entry)
    return output, result, job_id


def _active_request_id(runtime: Any, owner: str) -> str:
    rid = str(getattr(runtime, "_cur_rid", "") or "")
    if rid:
        return rid
    state = getattr(runtime, "requests_state", None)
    token = getattr(state, "_current", None)
    active = token.get() if hasattr(token, "get") else None
    return str(active[1]) if active and str(active[0]) == owner else ""


def run_step(runtime: Any, text: str) -> tuple[Any, Any]:
    """Run ONE step of an already-canonical turn with its OWN semantic decision.

    Only a nested step (multi-step sentence, macro action) uses this: the caller must already be
    inside a bound canonical entry. The step shares the turn's owner/request identity but never
    borrows the outer utterance's UnderstandingResult — `prepare` + `handoff` decide it once, and
    the raw step text never re-enters the legacy interpretation chain.

    Returns (raw Core/legacy output, BrainFeedback)."""
    outer = current()
    if outer is None:
        raise ValueError("Adım yalnız bağlı bir canonical isteğin içinde çalıştırılabilir.")
    owner = _runtime_owner(runtime)
    if owner != outer.owner:
        raise ValueError("Adım owner'ı bağlı istekle eşleşmiyor.")
    request_id = _active_request_id(runtime, owner)
    if not request_id:
        raise ValueError("Adım için etkin istek kimliği yok.")
    step = str(text).strip()
    if not step:
        raise ValueError("Adım metni boş olamaz.")
    if step == outer.text.strip():
        raise ValueError("Outer cümlenin kendi kararı adım olarak yeniden çalıştırılamaz.")
    source = str(getattr(runtime, "_cur_source", "") or "") or outer.source
    entry = prepare(runtime, owner=owner, request_id=request_id, text=step, source=source)
    return handoff(runtime, entry, getattr(runtime, "handle", None), step)[:2]


def goal_question_superseded(runtime: Any = None) -> bool | None:
    """Brain's decision whether this request replaces a goal's open question instead of answering it.

    None when the request did not come through the canonical entry (Live) or when this call is a
    nested step (``önce X sonra Y`` / macro action): a step is not a standalone user turn, so the
    caller keeps its legacy rule until PR9. Otherwise a new capability, a context-control request,
    a topic change or an utterance ending with an action verb
    (``ENDS_WITH_ACTION``, rule owned by brain_actions) supersedes the question."""
    entry = current()
    if entry is None:
        return None
    if runtime is not None:
        try:
            state = runtime._session()
            if getattr(state, "_in_multi", False) or getattr(state, "_in_macro", False):
                return None
        except Exception:
            _record_failure("modules/brain_entry.py:goal_question_nested")
    semantic = entry.understanding
    if semantic is None:
        return False
    return (semantic.request_kind in {RequestKind.CAPABILITY, RequestKind.CONTEXT_CONTROL}
            or semantic.conversation_relation is ConversationRelation.TOPIC_CHANGE
            or ACTION_REQUEST_CODE in semantic.reason_codes)


def matched_protocol(*protocols: str) -> bool:
    entry = current()
    return bool(entry is not None and entry.state_gate.matched and entry.state_gate.protocol in protocols)


def open_pending_answer(entry: EntryResult, field: str) -> bool:
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
        # Tek authority: Understanding relation'ı seçer; pending photo canonical state'i
        # ActiveContext'teki tek temsil ile doğrulanır.
        return (semantic.conversation_relation is ConversationRelation.CONTINUE_ACTIVE
                and PHOTO_FOLLOWUP_CODE in semantic.reason_codes
                and _pending_photo_state(entry.active_context) is not None)
    return False


def relation_decided(entry: Any) -> bool:
    """True when Brain reached a single relation/protocol decision the surface may act on."""
    if not isinstance(entry, EntryResult):
        return False
    if entry.state_gate.matched:
        return True
    if entry.state_gate.reason_code == "MULTIPLE_BOUNDED_STATE_MATCHES":
        return False
    if entry.understanding is not None:
        return True
    return entry.fast_gate is not None and entry.fast_gate.matched
