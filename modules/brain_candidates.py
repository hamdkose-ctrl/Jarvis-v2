"""Bounded, read-only candidate providers for the canonical Jarvis Brain.

Candidate discovery is observation only. This module does not resolve targets,
grant permission, run effects, call models, or own durable state.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import replace
from typing import Any, Callable, Iterable, Mapping

from modules.brain_contracts import ActiveContext, ContextReference
from modules.diagnostics import record_failure as _record_failure

_DEFAULT_PROVIDER_LIMIT = 40
_MAX_PROVIDER_LIMIT = 100


class _OwnerMismatch(ValueError):
    pass


def _required(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} boş olamaz.")
    return value


def _limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= _MAX_PROVIDER_LIMIT:
        raise ValueError(f"provider_limit 1-{_MAX_PROVIDER_LIMIT} arasında int olmalı.")
    return value


def _stable_id(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _safe_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    return None


def _profile_row_ref(
    *, owner: str, row: Mapping[str, Any], collection: str, kind: str, fields: tuple[str, ...]
) -> ContextReference | None:
    ident = _stable_id(row.get("id"))
    if ident is None:
        return None
    provenance: dict[str, Any] = {"collection": collection}
    for key in fields:
        if key not in row:
            continue
        value = _safe_scalar(row.get(key))
        if value is not None:
            provenance[key] = value
    return ContextReference(id=ident, kind=kind, source=f"profile.{collection}", owner=owner, provenance=provenance)


def _profile_refs(owner: str, profile: Any, limit: int) -> list[ContextReference]:
    if profile is None:
        return []
    profile_owner = str(getattr(profile, "slug", "") or "")
    if profile_owner and profile_owner != owner:
        raise _OwnerMismatch("Profile başka owner'a ait.")
    data = getattr(profile, "data", None)
    if not isinstance(data, Mapping):
        return []

    specs = (
        ("tasks", "task", ("text", "done", "when", "ts")),
        ("items", "note", ("title", "text", "ts", "photo")),
        ("events", "event", ("title", "when", "repeat", "notified")),
    )
    refs: list[ContextReference] = []
    for collection, kind, fields in specs:
        rows = data.get(collection)
        if not isinstance(rows, (list, tuple)):
            continue
        collected = 0
        for position, row in enumerate(rows, 1):
            if collected >= limit:
                break
            if not isinstance(row, Mapping):
                continue
            ref = _profile_row_ref(owner=owner, row=row, collection=collection, kind=kind, fields=fields)
            if ref is not None:
                if kind == "note":
                    ref = replace(ref, provenance={**ref.provenance,
                                  "list_position": position, "list_count": len(rows)})
                refs.append(ref)
                collected += 1
    # goals/facts/rules are intentionally absent: current Profile stores them as
    # strings/index-addressed lists, not stable target identities.
    return refs


def _active_context_refs(owner: str, context: ActiveContext, limit: int) -> list[ContextReference]:
    ordered = (
        context.active_artifacts,
        context.active_task_references,
        context.active_goal_references,
        context.recent_references,
        context.memory_references,
    )
    refs: list[ContextReference] = []
    for group in ordered:
        for ref in group:
            if ref.owner != owner:
                raise ValueError("ActiveContext başka owner referansı taşıyor.")
            if ref.kind == "source_status":
                continue
            if ref.kind == "note":
                # List positions belong to this turn's Profile observation,
                # never to an earlier conversation's stored reference.
                ref = replace(ref, provenance={key: value for key, value in ref.provenance.items()
                                               if key not in {"list_position", "list_count"}})
            refs.append(ref)
            if len(refs) >= limit:
                return refs
    return refs


def _fresh_cached_file_rows() -> list[Mapping[str, Any]] | None:
    """Return a snapshot only when nxapi's existing file cache is fresh."""
    from modules import nxapi

    lock = getattr(nxapi, "_FILE_CACHE_LOCK", None)
    cache = getattr(nxapi, "_FILE_CACHE", None)
    ttl = getattr(nxapi, "_FILE_TTL", 0.0)
    if lock is None or not isinstance(cache, dict):
        return None
    with lock:
        cached = cache.get("rows")
        cached_at = cache.get("ts")
        fresh = (
            isinstance(cached, list)
            and isinstance(cached_at, (int, float))
            and not isinstance(cached_at, bool)
            and isinstance(ttl, (int, float))
            and not isinstance(ttl, bool)
            and ttl > 0
            and (time.monotonic() - cached_at) < ttl
        )
        return list(cached) if fresh else None


def _sorted_file_rows(rows: Iterable[Mapping[str, Any]], limit: int) -> list[Mapping[str, Any]]:
    out = list(rows)
    out.sort(key=lambda row: (-float(row.get("mtime") or 0), str(row.get("path") or "").casefold()))
    return out[:limit]


def _cached_file_reader(*, limit: int) -> Iterable[Mapping[str, Any]]:
    """Observe only an already-fresh nxapi cache; never start synchronous discovery."""
    rows = _fresh_cached_file_rows()
    return _sorted_file_rows(rows or (), limit)


def _default_file_reader(*, limit: int) -> Iterable[Mapping[str, Any]]:
    """Observe nxapi inventory, scanning only when no fresh cache exists."""
    from modules import nxapi

    rows = _fresh_cached_file_rows()
    if rows is None:
        # Reuse the inventory owner's generation fence and cache. This call
        # observes metadata only; it does not select an operation or open files.
        nxapi._background_refresh()
        rows = _fresh_cached_file_rows() or []
    return _sorted_file_rows(rows, limit)


def _file_refs(
    owner: str,
    reader: Callable[..., Iterable[Mapping[str, Any]]],
    limit: int,
) -> list[ContextReference]:
    try:
        rows = list(reader(limit=limit))[:limit]
    except Exception:
        _record_failure("modules/brain_candidates.py:file_provider")
        return []
    refs: list[ContextReference] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        path = row.get("path")
        ident = path.strip() if isinstance(path, str) and path.strip() else None
        if ident is None:
            continue
        provenance: dict[str, Any] = {"inventory_scope": "global_pc", "path": ident}
        for key in ("name", "ext", "cat", "size", "mtime", "folder", "where"):
            value = _safe_scalar(row.get(key))
            if value is not None:
                provenance[key] = value
        if isinstance(row.get("mine"), bool):
            provenance["jarvis_files_root"] = row["mine"]
        refs.append(ContextReference(
            id=ident,
            kind="file",
            source="nxapi.file_inventory",
            owner=owner,
            provenance=provenance,
        ))
    return refs


def _dedupe(refs: Iterable[ContextReference]) -> tuple[ContextReference, ...]:
    out: list[ContextReference] = []
    seen: dict[tuple[str, str], int] = {}
    for ref in refs:
        key = (ref.kind, ref.id)
        if key in seen:
            # A current Profile note refreshes its content and list position
            # without changing the priority/order of other active observations.
            if ref.kind == "note" and "list_position" in ref.provenance:
                out[seen[key]] = ref
            continue
        seen[key] = len(out)
        out.append(ref)
    return tuple(out)


def _fair_limit(refs: tuple[ContextReference, ...], limit: int) -> tuple[ContextReference, ...]:
    """Bound the whole observation without letting task/history volume hide notes/files."""
    groups: dict[str, deque] = {}
    for ref in refs:
        groups.setdefault(ref.kind, deque()).append(ref)
    out: list[ContextReference] = []
    while groups and len(out) < limit:
        for kind in tuple(groups):
            out.append(groups[kind].popleft())
            if not groups[kind]:
                del groups[kind]
            if len(out) == limit:
                break
    return tuple(out)


def build_candidates(
    *,
    owner: str,
    request_id: str,
    text: str,
    active_context: ActiveContext,
    profile: Any = None,
    file_reader: Callable[..., Iterable[Mapping[str, Any]]] | None = None,
    provider_limit: int = _DEFAULT_PROVIDER_LIMIT,
    allow_file_scan: bool = True,
) -> tuple[ContextReference, ...]:
    """Build bounded candidate references without resolving or authorizing a target.

    ``text`` is validated as the original request text. V1 providers deliberately
    do not infer intent, resolve references, or invoke a model from that text.
    ``allow_file_scan=False`` keeps Active/Profile/fresh-cache observations while
    preventing a cold or stale cache from synchronously walking the PC filesystem.
    """
    owner = _required("owner", owner)
    request_id = _required("request_id", request_id)
    _required("text", text)
    provider_limit = _limit(provider_limit)
    if not isinstance(allow_file_scan, bool):
        raise ValueError("allow_file_scan bool olmalı.")
    if not isinstance(active_context, ActiveContext):
        raise ValueError("active_context ActiveContext olmalı.")
    if active_context.owner != owner:
        raise ValueError("ActiveContext owner eşleşmiyor.")
    if active_context.request_id != request_id:
        raise ValueError("ActiveContext request_id eşleşmiyor.")

    if file_reader is not None:
        reader = file_reader
    else:
        reader = _default_file_reader if allow_file_scan else _cached_file_reader
    refs: list[ContextReference] = []
    # Current/live observations precede profile inventory and memory observations.
    refs.extend(_active_context_refs(owner, active_context, provider_limit))
    try:
        refs.extend(_profile_refs(owner, profile, provider_limit))
    except _OwnerMismatch:
        raise
    except Exception:
        _record_failure("modules/brain_candidates.py:profile_provider")
    refs.extend(_file_refs(owner, reader, provider_limit))
    return _fair_limit(_dedupe(refs), provider_limit)
