"""Canonical production entry for the non-authoritative Brain foundation.

This module composes the already-merged Brain context/gates/reference/understanding
layers. It never grants permission, runs an effect, selects a worker, or marks
work complete. Existing Core/domain handlers remain the only execution path.
"""
from __future__ import annotations

import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any, Mapping

from modules import brain_actions, brain_context, brain_core_map, brain_precedence, capability_manifest, typo
from modules.brain_understanding import (
    ACTION_REQUEST_CODE,
    APP_CLOSE_CAPABILITY,
    APP_OPEN_CAPABILITY,
    EXECUTION_REQUEST_CODE,
    EXPLANATION_REQUEST_CODE,
    PHOTO_CAPABILITY,
    PHOTO_FOLLOWUP_CODE,
)
from modules.brain_candidates import build_candidates
from modules.brain_contracts import (
    ActiveContext,
    BrainFeedback,
    ContextReference,
    ConversationRelation,
    PendingOwner,
    RequestKind,
)
from modules.brain_gates import GateObservation, deterministic_fast_gate, exact_state_gate
from modules.brain_reference import resolve_references
from modules.brain_understanding import is_sequenced, sequence_steps, understand
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
PENDING_PHOTO_TTL = 600
# Cevabı fotoğrafın kendi bounded tüketicisi yazan state protokolü (PR3B'de Core'a taşınacak).
PHOTO_CANCEL_PROTOCOL = "phone_photo.cancel"


def _pending_photo_row(runtime: Any, owner: str) -> dict[str, Any] | None:
    """The fresh owner-scoped pending-photo row; expiry is lifecycle, never semantic authority."""
    row = getattr(runtime, "_pending_photo", {}).get(owner)
    if not isinstance(row, dict) or not row.get("path"):
        return None
    started = row.get("t")
    if not isinstance(started, (int, float)) or time.time() - float(started) > PENDING_PHOTO_TTL:
        return None
    return row


_APP_CLARIFY_KINDS = frozenset({APP_OPEN_CAPABILITY, APP_CLOSE_CAPABILITY})


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
        and proposal.get("kind") in _APP_CLARIFY_KINDS
    )


def _with_app_target_evidence(active: ActiveContext, runtime: Any) -> ActiveContext:
    """Attach the canonical app alias catalog while a typed app open/close question is open.

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


def _recipient_pending_reference(reference: ContextReference) -> bool:
    value = reference.provenance.get("value")
    return (
        reference.id == "pending_msg"
        and reference.kind == "pending_state"
        and reference.source == "session_state"
        and isinstance(value, Mapping)
        and value.get("stage") == "to"
    )


def _with_recipient_evidence(active: ActiveContext, runtime: Any) -> ActiveContext:
    """Attach registered contact names while the recipient question is open.

    Understanding never reads the profile: it only consumes the names the caller supplies, so
    phone numbers never leave the profile."""
    if not any(_recipient_pending_reference(ref) for ref in active.pending_references):
        return active
    try:
        data = getattr(getattr(runtime, "profile", None), "data", None)
        contacts = data.get("contacts") if isinstance(data, Mapping) else None
        names = tuple(sorted(
            name for name in contacts if isinstance(name, str) and name.strip()
        )) if isinstance(contacts, Mapping) else ()
    except Exception:
        _record_failure("modules/brain_entry.py:recipient_evidence")
        return active
    if not names:
        return active
    rows = tuple(
        replace(ref, provenance={**ref.provenance, "recipient_candidates": names})
        if _recipient_pending_reference(ref) else ref
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
    row = _pending_photo_row(runtime, owner)
    if row is None:
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
    row = _pending_photo_row(runtime, owner)
    if row is None:
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
    active = _with_recipient_evidence(active, runtime)
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


_TYPO_UNVERIFIED_QUESTION = ("Cümlenin Türkçe karakterleri tamamlanmış hâli doğrulanmış bir yetenekte karşılık "
                             "bulmadı; genel hedef yürütmesi başlatılmadı, işlem başlatılmadı. İsteği tek tek de söyleyebilirsin.")


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
                if typo.diacritic_correction(entry.text.casefold()):
                    # Kaldırılan ikinci `handle()` geçişi düzeltilmiş metni ham kapılara tekrar
                    # sokuyordu; o geçiş geri gelmez (BRAIN-MIG-042). Yalnız Türkçe karakteri
                    # geri getirilen — kelime kimliği değişmemiş — bir cümle doğrulanmış hiçbir
                    # yetenekte karşılık bulmadıysa Goal/Task yetkisi olamaz: bu yolla yeni
                    # GoalState kaydı, model planlayıcısı veya dosya efekti başlamaz. Düzeltici
                    # doğru kelimeyi de bozabildiği için ("hazırla" -> "hatırla") kapı bilinçli
                    # olarak bu dar sınıfla sınırlandı; doğru yazılmış cümleler yetkisini kaybetmez.
                    return {"intent": "clarify", "args": {"question": _TYPO_UNVERIFIED_QUESTION}}
                return {"intent": "task", "args": {"request": entry.text}}
            return {"intent": "clarify", "args": {"question": "Capability önerisi mevcut Core manifestinde doğrulanamadı; işlem başlatılmadı."}}
        return {"intent": "task", "args": {}}
    return {"intent": "chat", "args": {}}


def nested_step(command: str) -> bool:
    """True when a canonical entry is bound but this text is a different request: a sequence or macro step.

    The bound entry's decision belongs to the whole utterance, never to one of its steps.
    A request never runs a second pass (§25 A, BRAIN-MIG-042), so any text that arrives while an
    entry is bound and differs from that entry's own sentence is a step."""
    entry = current()
    return entry is not None and str(command).strip() != entry.text.strip()


_NESTED_STEP_QUESTION = ("Bu metin bir adımlar zincirinin adımı; cümlenin canonical kararı ona devredilmez. "
                         "Adımı ikinci kez kendim yorumlamam: adımı tek başına bir istek olarak söyle.")


def route_command(runtime: Any, command: str) -> dict[str, object]:
    """Core handler'ın tek sınıflandırılmış-istek kapısı; kendisi sınıflandırmaz.

    Bu turn'de Brain'in zaten vermiş olduğu kararın izdüşümünü verir. Bağlı bir Brain girişi
    yoksa cümle burada hiç yorumlanmaz ve istek fail-closed netleştirmeyle durur."""
    if nested_step(command):
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
        entry = current()
        if entry is not None:
            if entry.state_gate.reason_code == "MULTIPLE_BOUNDED_STATE_MATCHES":
                return None
            if entry.state_gate.matched and not matched_protocol("job.resume", "job.cancel"):
                return None
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


def _has_open_pending(entry: EntryResult) -> bool:
    """Slot inventory only: is another interaction still open?

    Presence alone grants no relation authority; ``_pending_owns_turn`` decides whether this
    turn belongs to that interaction."""
    # A clarify question never blocks a new request: only an exact offered-choice answer is
    # consumed (state gate protocol session.pending_action.clarify_select); anything else is a new request.
    if any(not _is_clarify_pending(ref) for ref in entry.active_context.pending_references):
        return True
    # A photo artifact belonging to THIS request is the turn's own input, not another open slot.
    return any(
        ref.kind == "photo" and ref.source == "engine_queue.photo"
        and str(ref.provenance.get("origin_request_id") or "") != entry.request_id
        for ref in entry.active_context.active_artifacts
    )


def photo_followup_owned(entry: EntryResult | None) -> bool:
    """True when the canonical relation points at the still-open pending photo.

    This is a relation check only: it grants no execution authority and never reads raw text."""
    if not isinstance(entry, EntryResult):
        return False
    semantic = entry.understanding
    if semantic is None:
        return False
    return (semantic.conversation_relation is ConversationRelation.CONTINUE_ACTIVE
            and PHOTO_FOLLOWUP_CODE in semantic.reason_codes
            and _pending_photo_state(entry.active_context) is not None)


def _photo_lifecycle(runtime: Any, entry: EntryResult) -> None:
    """Düşme kuralının tek sahibi: fotoğrafa bağlı olmayan, kararı verilmiş turn pending'ı kapatır.

    Kural yüzeyde (`engine_commands`) yaşıyordu ve legacy handler'a ulaşan turlerde çalışıyordu;
    Fast/State lane'ları handler'ı dolaşınca hiç uygulanmaz oldu. Karar yine yalnız canonical
    relation/protocol gözleminden gelir — burada ham cümle hiçbir fotoğraf işlemi seçmez.
    İptal turn'ü fotoğrafın kendi sahibidir: mesajını bounded tüketici yazar, düşürülmez."""
    try:
        if getattr(runtime._session(), "_in_multi", False):
            return
    except Exception:
        _record_failure("modules/brain_entry.py:photo_lifecycle_session")
        return
    photos = getattr(runtime, "_pending_photo", None)
    if not isinstance(photos, dict):
        return
    row = photos.get(entry.owner)
    if not isinstance(row, dict):
        return
    started = row.get("t")
    # Süre sınırı lifecycle gözlemidir; `_pending_photo_row` ile aynı saati okur.
    if not isinstance(started, (int, float)) or time.time() - started > PENDING_PHOTO_TTL:
        photos.pop(entry.owner, None)
        return
    if photo_followup_owned(entry):
        return
    if entry.state_gate.matched and entry.state_gate.protocol == PHOTO_CANCEL_PROTOCOL:
        return
    if relation_decided(entry):
        photos.pop(entry.owner, None)


def _pending_owns_turn(entry: EntryResult) -> bool:
    """Does another open interaction canonically own this turn?

    Relation authority is the canonical chain, not slot presence: an exact State protocol, a
    fail-closed multiple match, or Understanding's ANSWER_TO_PENDING/CONTINUE_ACTIVE decision.
    A NEW_REQUEST/TOPIC_CHANGE/CORRECTION/CONTEXT_CONTROL turn stays independent while the
    other interaction remains open; preserving or dropping that state is a separate lifecycle.
    """
    if not _has_open_pending(entry):
        return False
    if entry.state_gate.matched or entry.state_gate.reason_code == "MULTIPLE_BOUNDED_STATE_MATCHES":
        return True
    if entry.fast_gate is not None and entry.fast_gate.matched:
        return False
    semantic = entry.understanding
    if semantic is None:
        return True
    if semantic.conversation_relation is ConversationRelation.ANSWER_TO_PENDING:
        # The typed clarify answer is itself the Core plan's turn: another still-open slot
        # must not veto the plan that consumes this bound target.
        return semantic.pending_owner is not PendingOwner.APP_CLARIFY
    return semantic.conversation_relation is ConversationRelation.CONTINUE_ACTIVE


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


def step_plan(command: str) -> tuple[str, ...]:
    """Bu turn'ün kanonical sıralı adım planı; ham motor yüzeyi cümleyi kendi başına bölmez.

    Karar bağlı request'e aittir: giriş bu turn'ün cümlesiyle birebir aynı olmalıdır. Böylece
    düzeltilmiş/geçmiş bir metin görüşü ikinci bir adım planı üretemez. Sıra gramerinin tek sahibi
    Understanding'dir (`sequence_steps`); plan boşsa yüzey tek isteğe sahip normal akışına devam
    eder, adım yürütmesi typed adaptörde (`engine_sequence._run_steps`) kalır."""
    entry = current()
    if entry is None or entry.text.strip() != command:
        return ()
    return sequence_steps(command)


def _canonical_photo_path(entry: EntryResult) -> tuple[str | None, bool]:
    """Re-derive the one photo artifact this request may act on; Core does not trust the proposal.

    A current-request artifact wins; otherwise the still-open pending photo is the target.
    More than one candidate is ambiguous and yields no plan."""
    rows = [
        ref for ref in entry.active_context.active_artifacts
        if ref.kind == "photo" and ref.source == "engine_queue.photo"
        and isinstance(ref.provenance.get("path"), str) and ref.provenance.get("path")
    ]
    current = {
        str(ref.provenance["path"]) for ref in rows
        if str(ref.provenance.get("origin_request_id") or "") == entry.request_id
    }
    if current:
        return (next(iter(current)), False) if len(current) == 1 else (None, True)
    pending = _pending_photo_state(entry.active_context)
    if pending is None:
        return None, False
    pending_path = pending.provenance.get("path")
    if not isinstance(pending_path, str) or not pending_path:
        return None, True
    matching = {str(ref.provenance["path"]) for ref in rows
                if str(ref.provenance["path"]) == pending_path}
    return (pending_path, False) if len(matching) == 1 else (None, True)


def core_plan(entry: EntryResult) -> tuple[str, dict[str, object]] | None:
    """Core-validated intent for a mapped capability hint; None keeps the existing handler path."""
    if entry.state_gate.matched or (entry.fast_gate is not None and entry.fast_gate.matched):
        return None
    semantic = entry.understanding
    if semantic is None or semantic.request_kind is not RequestKind.CAPABILITY:
        return None
    if is_sequenced(entry.text):
        return None
    plan = brain_core_map.core_plan(semantic.capability_hint, semantic.arguments)
    photo_plan = plan is not None and plan[0] == "photo_action"
    if photo_plan:
        selected, ambiguous = _canonical_photo_path(entry)
        if ambiguous or selected is None or plan[1].get("photo") != selected:
            return None
    # Slot presence is not relation authority: only a turn the canonical chain assigned to an
    # open interaction (exact state/answer/continuation) blocks the plan. The single exception is
    # a validated photo plan that consumes exactly the open pending photo it was built from.
    if _pending_owns_turn(entry):
        consumes_pending = (photo_plan and photo_followup_owned(entry)
                            and not semantic.ambiguities)
        if not consumes_pending:
            return None
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
    if semantic.request_kind is RequestKind.CAPABILITY:
        # An independent new capability keeps its Core plan/handler while another interaction
        # stays open; a capability never silently falls through to chat because of a slot.
        return not _pending_owns_turn(entry)
    if semantic.request_kind is RequestKind.CHAT:
        # Chat is never an open slot's answer. An independent chat-shaped request keeps the
        # existing handler path (Brain-unmapped phrases such as "hava durumuna bak" still have a
        # legacy owner); slot consumers are fenced by pending_answer_owned, so the slot survives.
        return not _pending_owns_turn(entry)
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


def _lane_plan(runtime: Any, entry: EntryResult) -> tuple[str, dict[str, object]] | None:
    """Bounded State/Fast turn'un tek Core planı: cümle yeniden sınıflandırılmaz.

    Yalnız seçili protokol bilinir bir niyete bağlanır; diğer state/fast turları (engine control,
    goal, job, onay, mesaj) eski sahiplerinde kalır. Bu plan front gate'leri dolaşır: tek bir
    sınırlı cevabı vardır ve başka bir yüzeyin onu yeniden yorumlaması söz konusu değildir."""
    gate = entry.state_gate
    if gate.matched:
        level: Any = None
        if gate.protocol == brain_core_map.LEVEL_SELECT_PROTOCOL:
            try:
                level = runtime._session().pending_level
            except Exception:
                _record_failure("modules/brain_entry.py:pending_level_snapshot")
                return None
        return brain_core_map.state_plan(gate.protocol, gate.selection, level)
    fast = entry.fast_gate
    if fast is not None and fast.matched:
        return brain_core_map.fast_plan(fast.protocol, fast.selection)
    return None


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
    plan = core_plan(entry)
    lane_plan = None if plan is not None else _lane_plan(runtime, entry)
    if (plan is None and entry.understanding is not None
            and entry.understanding.capability_hint == PHOTO_CAPABILITY):
        # No validated Core photo plan means no photo effect, and no legacy raw-text fallback.
        message = "Bu fotoğraf isteğini güvenli biçimde doğrulayamadım; işlem başlatılmadı."
        row = feedback(entry, result_status="failed", reason_code="PHOTO_TARGET_NOT_VALIDATED")
        _LAST_FEEDBACK.set(row)
        return message, row, None
    if not callable(handler):
        raise ValueError("Core handler callable olmalı.")
    _install_core_guards(runtime)
    _LAST_FEEDBACK.set(None)
    before = _open_core_pending(runtime)
    try:
        with bind(entry):
            if plan is not None or not _use_existing_handler(entry) or _relation_supersedes_clarify(entry):
                _drop_stale_clarify(runtime, entry)
            _photo_lifecycle(runtime, entry)
            claimed = brain_precedence.claim(runtime, command, plan) if plan is not None else None
            if claimed is not None:
                output = claimed[1]
            elif plan is not None:
                from modules.engine_intents import dispatch
                output = dispatch(runtime, plan[0], dict(plan[1]), command, command.casefold())
            elif lane_plan is not None:
                # Protokol cevapları tek sahibine gider: cümlenin kendisi hiçbir yerde yeniden sınıflandırılmaz.
                from modules.engine_intents import dispatch
                output = dispatch(runtime, lane_plan[0], dict(lane_plan[1]), command, command.casefold())
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


def explanation_turn() -> bool:
    """Bu kanonical tur bir açıklama/sohbet isteğidir; hiçbir ham cephe ona etki yürütemez.

    Hüküm Understanding'in `EXPLANATION_REQUEST` kaydından okunur; yüzey cümleyi ham metinden
    ikinci kez sınıflandırmaz. Bounded sahiplik korunur: bir State/Fast protokolü turu aldığında,
    tur açık bir alanın cevabı olduğunda, typed bir yetenek önerisi ya da typed pending sahibi
    taşıdığında kapılar kendi akışına devam eder. Doğrulanmış Core planı olan tur zaten buraya
    inmez (handoff planı yürütür)."""
    entry = current()
    if entry is None or entry.state_gate.matched:
        return False
    if entry.fast_gate is not None and entry.fast_gate.matched:
        return False
    semantic = entry.understanding
    if semantic is None or semantic.capability_hint or semantic.pending_owner is not None:
        return False
    if semantic.conversation_relation is not ConversationRelation.NEW_REQUEST:
        return False
    if semantic.request_kind not in {RequestKind.CHAT, RequestKind.CAPABILITY}:
        return False
    return EXPLANATION_REQUEST_CODE in semantic.reason_codes


def matched_protocol(*protocols: str) -> bool:
    entry = current()
    return bool(entry is not None and entry.state_gate.matched and entry.state_gate.protocol in protocols)


def turn_protocol() -> str | None:
    """The single State/Fast protocol the canonical gate selected for the bound turn, if any.

    Legacy pending consumers read this one observation before touching the raw text: a turn the
    canonical Fast Gate owns is not theirs, even though it has no bounded state protocol.
    Understanding is not a bounded protocol and stays out of this ownership view.
    """
    entry = current()
    if entry is None:
        return None
    if entry.state_gate.matched:
        return entry.state_gate.protocol
    if entry.fast_gate is not None and entry.fast_gate.matched:
        return entry.fast_gate.protocol
    return None


def protocol_owned_by(*prefixes: str) -> bool:
    """Is the bound turn canonically owned by one of *prefixes*?

    Visibility only: the Fast protocol seen here grants no effect, permission or execution
    authority; the existing Fast handler still runs on the canonical path.
    """
    owned = turn_protocol()
    if owned is None:
        return False
    return any(owned == prefix.rstrip(".") or owned.startswith(prefix) for prefix in prefixes if prefix)


# Pending field -> the State protocol prefix that legitimately answers it. Every session field
# is answered by ``session.<field>.``; desktop consent is the one domain-owned exception.
_PENDING_PROTOCOL_PREFIX = {"pending_desktop": "desktop."}

# The single session field each semantic pending owner represents. ``pending_msg`` has two
# stage-scoped owners; a field appears for both, never as a wildcard.
_PENDING_OWNER_FIELDS = {
    PendingOwner.WEATHER_LOCATION: "pending_weather_location",
    PendingOwner.MESSAGE_TO: "pending_msg",
    PendingOwner.MESSAGE_TEXT: "pending_msg",
    PendingOwner.APP_CLARIFY: "pending_action",
}


def pending_owner_matches(field: str, owner: object) -> bool:
    """Is *owner* the single canonical pending slot that *field* represents?

    The owner is Understanding's typed selection in state-protocol vocabulary. Missing,
    ambiguous or foreign owners match nothing, so two open slots cannot both consume the text."""
    if owner is None:
        return False
    try:
        owner = PendingOwner(owner)
    except (TypeError, ValueError):
        return False
    return _PENDING_OWNER_FIELDS.get(owner) == field


def protocol_selection(protocol: str) -> object | None:
    """The State Gate selection for *protocol* on the bound canonical turn.

    Consumers use this instead of re-parsing raw text: the gate's answer vocabulary and the
    consumer's interpretation can never drift apart. Unbound/mismatched turns return None.
    """
    entry = current()
    if entry is None or not entry.state_gate.matched or entry.state_gate.protocol != protocol:
        return None
    return entry.state_gate.selection


def pending_answer_owned(field: str) -> bool:
    """May the legacy consumer of *field* interpret the raw text on this canonical turn?

    Unbound callers keep their old behavior. A State turn belongs to the matching field
    protocol only; a Fast turn belongs to no pending field. An Understanding answer belongs
    only to the one slot its typed owner names; a turn with no single owner (independent
    request or true ambiguity) consumes nothing while every slot stays open.
    """
    entry = current()
    if entry is None:
        return True
    if entry.state_gate.matched:
        return protocol_owned_by(_PENDING_PROTOCOL_PREFIX.get(field, f"session.{field}."))
    if entry.fast_gate is not None and entry.fast_gate.matched:
        return False
    semantic = entry.understanding
    if semantic is None:
        return True
    return pending_owner_matches(field, semantic.pending_owner)


def allow_legacy_goal_control(text: str) -> bool:
    """Can the legacy goal handler interpret *text* inside this canonical turn?

    Explicit goal commands keep their domain state. A bare yes/cancel may reach the legacy
    handler only when the canonical gate selected a goal protocol; when the gate selected a
    foreground/Job owner, a long-lived Goal must not re-decide it. A canonical Fast turn other
    than the goal-status read is likewise not a goal answer (``saat kaç`` must not resume a
    paused goal's question). Unbound callers (Live, nested steps outside a turn) keep their old
    behavior.
    """
    entry = current()
    if entry is None:
        return True
    low = " ".join(str(text or "").casefold().split()).strip(" .!?")
    if low.startswith(("hedef ", "hedef:", "görev:", "görev yap:")):
        return True
    if entry.state_gate.matched:
        return str(entry.state_gate.protocol or "").startswith("goal.")
    if entry.fast_gate is not None and entry.fast_gate.matched:
        return entry.fast_gate.protocol == "fast.goal.status"
    return True


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
