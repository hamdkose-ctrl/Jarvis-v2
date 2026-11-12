"""Read-only adapters from existing Jarvis state into canonical ActiveContext.

This module owns no state. It never creates request identities, grants authority,
or writes back to SessionStore, history, GoalState, Profile, or Hoca state.
"""
from __future__ import annotations

from contextlib import nullcontext
import math
import hashlib
import json
import time
from typing import Any, Callable, Iterable, Mapping

from modules.brain_contracts import ActiveContext, ContextReference
from modules.diagnostics import record_failure as _record_failure

_HISTORY_LIMIT = 12
_MAX_HISTORY_LIMIT = 50
# BRAIN-05 hedef kartları: modelin bir turda görebileceği aktif hedef sayısı ve kart başlığının
# üst sınırı. Her iki değer de brain_model_understanding'in zarf sınırıyla aynıdır (MAX_TARGET_GOALS,
# goal.title maxLength); bağlam buradan fazla sunarsa zarf onu yine reddeder, sessizce kesmez.
_MAX_GOAL_CARDS = 8
_GOAL_TITLE_MAX = 200
_PENDING_FIELDS = (
    "pending_weather_location",
    "pending_confirm",
    "pending_action",
    "pending_organize",
    "pending_msg",
    "pending_level",
    "pending_voice",
    "pending_event_title",
    "pending_app",
    "pending_desktop",
    "pending_visual",
)
_DROP = object()


def _required(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} boş olamaz.")
    return value


def _present(value: Any) -> bool:
    if value is None or value is False or value == "":
        return False
    if isinstance(value, (tuple, list, dict, set)) and not value:
        return False
    return True


def _safe_json(value: Any) -> Any:
    """Return detached JSON-safe observation data; silently drop executable values."""
    if callable(value):
        return _DROP
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _DROP
    if isinstance(value, Mapping):
        result = {}
        for key in sorted(value, key=lambda item: str(item)):
            if not isinstance(key, str):
                continue
            item = _safe_json(value[key])
            if item is not _DROP:
                result[key] = item
        return result
    if isinstance(value, (tuple, list)):
        result = []
        for raw in value:
            item = _safe_json(raw)
            if item is not _DROP:
                result.append(item)
        return result
    return _DROP


def _ref(*, owner: str, ident: str, kind: str, source: str, provenance: Mapping[str, Any]) -> ContextReference:
    safe = _safe_json(provenance)
    return ContextReference(
        id=_required("ContextReference.id", ident),
        kind=kind,
        source=source,
        owner=owner,
        provenance={} if safe is _DROP else safe,
    )


def _status(owner: str, source: str, reason_code: str = "SOURCE_UNAVAILABLE") -> ContextReference:
    return _ref(
        owner=owner,
        ident=source,
        kind="source_status",
        source=source,
        provenance={"reason_code": reason_code},
    )


def _default_history_reader(owner: str, *, limit: int) -> Iterable[Mapping[str, Any]]:
    """Read history only when its domain-owned storage root already exists."""
    from modules import history

    if not history.DIR.is_dir():
        return []
    return history.read(owner, limit=limit)


def _default_goal_reader(owner: str) -> Any:
    """Read the latest goal only when domain-owned owner state already exists.

    Bu kart çıplak kontrollerin duran hedefidir (`latest.json`): BRAIN-05 onu değiştirmez.
    Çoklu hedef gözlemi ayrı bir kanaldan (`_default_goal_candidate_reader`) gelir."""
    from modules import goal_executor

    if not goal_executor.STORE.is_dir():
        return None
    owner_root = goal_executor.STORE / owner
    if not owner_root.is_dir() or not (owner_root / "latest.json").exists():
        return None
    return goal_executor.latest(owner)


def _default_goal_candidate_reader(owner: str) -> Any:
    """BRAIN-05: bu turda modele sunulacak owner'ın kendi açık hedef kayıtları (salt okunur).

    `latest()` seçici değildir: bir hedef duraklatıldığında diğeri duran hedef olsa bile
    duraklatılan hedef kimliğiyle adreslenebilir kalmalıdır."""
    from modules import goal_executor

    if not goal_executor.STORE.is_dir():
        return []
    return goal_executor.open_jobs(owner, limit=_MAX_GOAL_CARDS)


def _session_state(owner: str, store: Any) -> tuple[Any | None, ContextReference | None]:
    if store is None:
        return None, None
    states = getattr(store, "_states", None)
    if not isinstance(states, dict):
        return None, _status(owner, "session_state")
    lock = getattr(store, "_lock", None)
    try:
        with (lock if lock is not None else nullcontext()):
            state = states.get(owner)
    except Exception:
        _record_failure("modules/brain_context.py:session_state")
        return None, _status(owner, "session_state")
    explicit_owner = getattr(state, "owner", owner) if state is not None else owner
    if explicit_owner != owner:
        raise ValueError("Session state başka owner'a ait.")
    return state, None


def _clarify_active(owner: str, value: Any) -> bool | None:
    """Observation-layer validity of an open clarify: owner match and clock expiry.

    ``None`` means the value is not a clarify, so Understanding ignores it."""
    if not isinstance(value, Mapping) or value.get("stage") != "clarify":
        return None
    if str(value.get("owner") or "") != owner:
        return False
    expires = value.get("expires")
    if not isinstance(expires, (int, float)) or isinstance(expires, bool):
        return False
    return expires >= time.time()


def document_fingerprint(document: Any) -> str | None:
    """Identity of an existing session result; no document content leaves this adapter."""
    if not isinstance(document, (tuple, list)) or len(document) != 3:
        return None
    text, source, label = document
    if not isinstance(text, str) or not text.strip() or not isinstance(label, str):
        return None
    if source is not None and not isinstance(source, str):
        return None
    return hashlib.sha256(json.dumps([text, source, label], ensure_ascii=False).encode('utf-8')).hexdigest()


def _session_refs(owner: str, state: Any) -> tuple[list[ContextReference], list[ContextReference], list[ContextReference]]:
    pending: list[ContextReference] = []
    artifacts: list[ContextReference] = []
    recent: list[ContextReference] = []
    if state is None:
        return pending, artifacts, recent

    for field in _PENDING_FIELDS:
        value = getattr(state, field, None)
        if not _present(value):
            continue
        safe = _safe_json(value)
        provenance: dict[str, Any] = {"field": field}
        if safe is not _DROP:
            provenance["value"] = safe
            if field == "pending_action":
                active = _clarify_active(owner, safe)
                if active is not None:
                    provenance["active"] = active
        else:
            provenance["reason_code"] = "VALUE_NOT_JSON"
        pending.append(_ref(owner=owner, ident=field, kind="pending_state", source="session_state", provenance=provenance))

    last_doc = getattr(state, "last_doc", None)
    if isinstance(last_doc, (tuple, list)) and len(last_doc) >= 3:
        artifacts.append(_ref(
            owner=owner,
            ident="last_doc",
            kind="artifact",
            source="session_state",
            provenance={"field": "last_doc", "path": last_doc[1], "label": last_doc[2],
                        "document_digest": document_fingerprint(last_doc)},
        ))

    last_visual = getattr(state, "last_visual", None)
    if isinstance(last_visual, Mapping) and last_visual:
        artifacts.append(_ref(
            owner=owner,
            ident="last_visual",
            kind="artifact",
            source="session_state",
            provenance={"field": "last_visual", "kind": last_visual.get("kind"), "text": last_visual.get("text")},
        ))

    from modules import session_state
    last_property = session_state.fresh_property(state)
    if last_property is not None:
        recent.append(_ref(
            owner=owner,
            ident="last_property",
            kind="conversation_state",
            source="session_state",
            provenance={"field": "last_property", "value": last_property},
        ))

    last_command = getattr(state, "last_command", "")
    if isinstance(last_command, str) and last_command.strip():
        recent.append(_ref(
            owner=owner,
            ident="last_command",
            kind="conversation_state",
            source="session_state",
            provenance={"field": "last_command", "text": last_command},
        ))
    return pending, artifacts, recent


def _history_refs(
    owner: str,
    reader: Callable[[str, int], Iterable[Mapping[str, Any]]],
    reset_filter: Callable[[str, Iterable[Mapping[str, Any]]], Iterable[Mapping[str, Any]]],
    limit: int,
) -> tuple[list[ContextReference], ContextReference | None]:
    try:
        rows = list(reader(owner, limit=limit))
        rows = list(reset_filter(owner, rows))
    except Exception:
        _record_failure("modules/brain_context.py:history")
        return [], _status(owner, "history")
    refs = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        row_owner = row.get("owner")
        if row_owner is not None and str(row_owner) != owner:
            raise ValueError("History satırı başka owner'a ait.")
        ident = str(row.get("id") or "").strip()
        if not ident:
            continue
        refs.append(_ref(
            owner=owner,
            ident=ident,
            kind="conversation_turn",
            source="history",
            provenance={
                "ts": row.get("ts"),
                "role": row.get("role"),
                "text": row.get("text"),
                "transport_source": row.get("source"),
            },
        ))
    return refs, None


def _goal_title(request: Any) -> str:
    """Kart başlığı: kullanıcının kendi hedef cümlesinin sınırlı, tek satıra katlanmış görünümü."""
    return ' '.join(str(request or '').split())[:_GOAL_TITLE_MAX]


def _goal_progress(row: Mapping[str, Any]) -> str | None:
    steps = row.get("steps")
    if not isinstance(steps, (tuple, list)) or not steps:
        return None
    done = sum(isinstance(step, Mapping) and step.get("state") == "done" for step in steps)
    return f"{done}/{len(steps)}"


def _goal_card(owner: str, row: Mapping[str, Any]) -> ContextReference | None:
    ident = str(row.get("id") or row.get("job_id") or row.get("goal_id") or "").strip()
    if not ident:
        return None
    provenance: dict[str, Any] = {
        "state": row.get("state") or row.get("status"),
        "updated": row.get("updated"),
        "created": row.get("created"),
        "title": _goal_title(row.get("request")),
    }
    if '_execution_snapshot' in row:
        from modules import goal_executor
        provenance['execution_snapshot'] = row['_execution_snapshot']
        provenance['canonical_version'] = row.get('_canonical_version')
        provenance['control_key'] = goal_executor.control_key(row)
    progress = _goal_progress(row)
    if progress is not None:
        provenance["progress"] = progress
    if isinstance(row.get("priority"), int) and not isinstance(row.get("priority"), bool):
        provenance["priority"] = row["priority"]
    return _ref(owner=owner, ident=ident, kind="goal", source="goal_state", provenance=provenance)


def _goal_cards(
    owner: str,
    rows: list[Any],
    is_open: Callable[[Any], bool],
    *,
    failure_label: str,
) -> tuple[list[ContextReference], ContextReference | None]:
    """Durable satırlar → kartlar. Yalnız owner'ın kendi açık kayıtları kart olur."""
    refs: list[ContextReference] = []
    missing_id = False
    for row in rows:
        if not isinstance(row, Mapping):
            return [], _status(owner, "goal_state", "GOAL_ROW_INVALID")
        row_owner = row.get("owner")
        if row_owner is not None and str(row_owner) != owner:
            raise ValueError("GoalState başka owner'a ait.")
        try:
            open_now = bool(is_open(row))
        except Exception:
            _record_failure("modules/brain_context.py:" + failure_label)
            return [], _status(owner, "goal_state")
        if not open_now:
            continue
        card = _goal_card(owner, row)
        if card is None:
            missing_id = True
            continue
        refs.append(card)
    if not refs and missing_id:
        return [], _status(owner, "goal_state", "MISSING_STABLE_ID")
    return refs, None


def _goal_refs(
    owner: str,
    reader: Callable[[str], Any],
    is_open: Callable[[Any], bool],
) -> tuple[list[ContextReference], ContextReference | None]:
    try:
        row = reader(owner)
    except Exception:
        _record_failure("modules/brain_context.py:goal_read")
        return [], _status(owner, "goal_state")
    if not isinstance(row, Mapping):
        return [], None
    return _goal_cards(owner, [row], is_open, failure_label="goal_open")


def _goal_candidate_refs(
    owner: str,
    reader: Callable[[str], Any],
    is_open: Callable[[Any], bool],
) -> tuple[list[ContextReference], ContextReference | None]:
    """BRAIN-05 kart listesi: sayıca sınırlı, kimliği kayıttan gelen açık hedef gözlemi."""
    try:
        rows = reader(owner)
    except Exception:
        _record_failure("modules/brain_context.py:goal_candidate_read")
        return [], _status(owner, "goal_state", "GOAL_CANDIDATE_READ")
    if rows is None:
        # Okuyucu bu turda hiç hedef sunmadı; bu bir hata değil, boş gözlemdir.
        return [], None
    if isinstance(rows, Mapping) or not isinstance(rows, (tuple, list)):
        _record_failure("modules/brain_context.py:goal_candidate_shape")
        return [], _status(owner, "goal_state", "GOAL_CANDIDATE_SHAPE_INVALID")
    refs, status = _goal_cards(owner, list(rows)[:_MAX_GOAL_CARDS], is_open,
                              failure_label="goal_candidate_open")
    return refs, status


def _profile_refs(owner: str, profile: Any) -> tuple[list[ContextReference], list[ContextReference], list[ContextReference]]:
    memory: list[ContextReference] = []
    tasks: list[ContextReference] = []
    pending: list[ContextReference] = []
    if profile is None:
        return memory, tasks, pending
    profile_owner = str(getattr(profile, "slug", "") or "")
    if profile_owner and profile_owner != owner:
        raise ValueError("Profile başka owner'a ait.")
    data = getattr(profile, "data", None)
    if not isinstance(data, Mapping):
        return memory, tasks, [_status(owner, "profile")]

    prefs = data.get("prefs")
    if isinstance(prefs, Mapping):
        city = prefs.get("city")
        if isinstance(city, str) and city.strip():
            memory.append(_ref(
                owner=owner,
                ident="city",
                kind="preference",
                source="profile.prefs",
                provenance={"key": "city", "value": city},
            ))

    hoca = data.get("hoca")
    lesson = hoca.get("lesson") if isinstance(hoca, Mapping) else None
    if not isinstance(lesson, Mapping) or lesson.get("done"):
        return memory, tasks, pending
    active = lesson.get("active", 0)
    steps = lesson.get("steps")
    if isinstance(active, bool) or not isinstance(active, int) or not isinstance(steps, list) or not 0 <= active < len(steps):
        return memory, tasks, pending
    step = steps[active]
    if not isinstance(step, Mapping):
        return memory, tasks, pending
    tasks.append(_ref(
        owner=owner,
        ident="lesson",
        kind="lesson",
        source="profile.hoca",
        provenance={
            "topic": lesson.get("topic"),
            "active": active,
            "course_id": lesson.get("course_id"),
            "started": lesson.get("started"),
            "step_title": step.get("title"),
            "step_goal": step.get("goal"),
            "has_pending": bool(isinstance(lesson.get("pending"), Mapping)
                                and lesson["pending"].get("step") == active
                                and lesson["pending"].get("question")),
        },
    ))
    hoca_pending = lesson.get("pending")
    if isinstance(hoca_pending, Mapping) and hoca_pending.get("step") == active and hoca_pending.get("question"):
        pending.append(_ref(
            owner=owner,
            ident="lesson.pending",
            kind="pending_state",
            source="profile.hoca",
            provenance={"step": hoca_pending.get("step"), "question": hoca_pending.get("question")},
        ))
    return memory, tasks, pending


def build_active_context(
    *,
    owner: str,
    request_id: str,
    session_store: Any = None,
    profile: Any = None,
    history_reader: Callable[[str, int], Iterable[Mapping[str, Any]]] | None = None,
    history_filter: Callable[[str, Iterable[Mapping[str, Any]]], Iterable[Mapping[str, Any]]] | None = None,
    goal_reader: Callable[[str], Any] | None = None,
    goal_candidate_reader: Callable[[str], Any] | None = None,
    goal_is_open: Callable[[Any], bool] | None = None,
    history_limit: int = _HISTORY_LIMIT,
) -> ActiveContext:
    """Build one immutable observation snapshot without taking state authority."""
    owner = _required("owner", owner)
    request_id = _required("request_id", request_id)
    if not isinstance(history_limit, int) or isinstance(history_limit, bool) or history_limit <= 0:
        raise ValueError("history_limit pozitif int olmalı.")
    if history_limit > _MAX_HISTORY_LIMIT:
        raise ValueError(f"history_limit en çok {_MAX_HISTORY_LIMIT} olabilir.")

    if history_reader is None:
        history_reader = _default_history_reader
    if history_filter is None:
        from modules import conversation_reset
        history_filter = conversation_reset.recent
    if goal_reader is None:
        goal_reader = _default_goal_reader
    if goal_candidate_reader is None:
        goal_candidate_reader = _default_goal_candidate_reader
    if goal_is_open is None:
        from modules import goal_executor
        goal_is_open = goal_executor.is_open

    pending: list[ContextReference] = []
    artifacts: list[ContextReference] = []
    recent: list[ContextReference] = []
    goals: list[ContextReference] = []
    tasks: list[ContextReference] = []
    memory: list[ContextReference] = []

    state, session_status = _session_state(owner, session_store)
    session_pending, session_artifacts, session_recent = _session_refs(owner, state)
    pending.extend(session_pending)
    artifacts.extend(session_artifacts)
    recent.extend(session_recent)
    if session_status is not None:
        recent.append(session_status)

    history_refs, history_status = _history_refs(owner, history_reader, history_filter, history_limit)
    recent.extend(history_refs)
    if history_status is not None:
        recent.append(history_status)

    goal_refs, goal_status = _goal_refs(owner, goal_reader, goal_is_open)
    goals.extend(goal_refs)
    if goal_status is not None:
        recent.append(goal_status)

    # BRAIN-05: modelin bu turda görebileceği açık hedef kartları. State/Fast gate'leri bu
    # kanalı hiç okumaz — çıplak kontrollerin duran hedefi yukarıdaki tek karttır.
    candidates, candidate_status = _goal_candidate_refs(owner, goal_candidate_reader, goal_is_open)
    if candidate_status is not None:
        recent.append(candidate_status)

    profile_memory, profile_tasks, profile_pending = _profile_refs(owner, profile)
    memory.extend(profile_memory)
    tasks.extend(profile_tasks)
    pending.extend(profile_pending)

    return ActiveContext(
        owner=owner,
        request_id=request_id,
        active_goal_references=tuple(goals),
        goal_candidates=tuple(candidates),
        active_task_references=tuple(tasks),
        recent_references=tuple(recent),
        active_artifacts=tuple(artifacts),
        pending_references=tuple(pending),
        memory_references=tuple(memory),
    )
