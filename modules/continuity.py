"""Cross-device continuity view over existing Core-owned work.

This module never creates goals, grants permissions, or changes authority. A device
and conversation/session id are metadata only; work identity is always resolved from
the authenticated owner's existing GoalState/task records.
"""
from __future__ import annotations

import re
from typing import Any

from modules.diagnostics import record_failure as _record_failure

_ID = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")


def _metadata_id(value: str | None, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not _ID.fullmatch(text):
        raise ValueError(f"{field} geçersiz.")
    return text


def _work_id(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    for key in ("id", "job_id", "goal_id"):
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return ""


def _goal_view(owner: str) -> dict[str, Any] | None:
    from modules import goal_executor

    try:
        row = goal_executor.latest(owner)
    except Exception:
        _record_failure("modules/continuity.py:_goal_view.latest")
        return None
    if not isinstance(row, dict):
        return None
    try:
        is_open = bool(goal_executor.is_open(row))
    except Exception:
        _record_failure("modules/continuity.py:_goal_view.is_open")
        is_open = False
    return {
        "id": _work_id(row),
        "state": str(row.get("state") or row.get("status") or ""),
        "open": is_open,
    }


def _task_view(owner: str) -> dict[str, Any] | None:
    from modules import task_agents

    try:
        row = task_agents.recent(owner)
    except Exception:
        _record_failure("modules/continuity.py:_task_view.recent")
        return None
    if not isinstance(row, dict):
        return None
    return {
        "id": _work_id(row),
        "state": str(row.get("state") or ""),
        "updated": row.get("updated"),
    }


def snapshot(owner: str, *, device_id: str = "", session_id: str = "") -> dict[str, Any]:
    """Return the authenticated owner's current work view for any client device.

    `device_id` and `session_id` are presentation/continuity metadata. They cannot
    select another owner, approve work, or create authority. The caller must derive
    `owner` from an already authenticated channel (for example the phone X-Token).
    """
    owner = str(owner or "").strip()
    if not owner:
        raise ValueError("owner gerekli.")
    return {
        "owner": owner,
        "device_id": _metadata_id(device_id, "device_id"),
        "session_id": _metadata_id(session_id, "session_id"),
        "goal": _goal_view(owner),
        "task": _task_view(owner),
        "authority": "core",
        "permission_granted": False,
    }
