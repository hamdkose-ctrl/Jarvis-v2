"""Narrow compatibility hook for legacy goal_executor atomic saves.

The legacy executor still owns its JSON journal during migration. This hook
recognizes only legacy goal-job records and synchronizes canonical GoalState
before the legacy atomic write. Canonical writes and unrelated JSON writes are
left untouched.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import release_guard

_JOB_FILE = re.compile(r'([a-f0-9]{16})\.json\Z')
_REQUIRED = frozenset({'id', 'owner', 'request', 'state', 'goals', 'steps', 'outputs'})
_ORIGINAL_ATOMIC = release_guard.atomic
_INSTALLED = False


def _legacy_job(path: Path, data) -> dict | None:
    match = _JOB_FILE.fullmatch(path.name)
    if not match or not isinstance(data, (bytes, bytearray)):
        return None
    try:
        value = json.loads(bytes(data).decode('utf-8'))
    except (UnicodeDecodeError, ValueError, TypeError):
        return None
    if not isinstance(value, dict) or not _REQUIRED.issubset(value):
        return None
    if value.get('id') != match.group(1):
        return None
    if not isinstance(value.get('owner'), str) or not value['owner']:
        return None
    return value


def _atomic(path, data):
    path = Path(path)
    job = _legacy_job(path, data)
    if job is not None:
        from modules import goal_state_compat
        canonical = path.with_name(job['id'] + '.goalstate.json')
        goal_state_compat.sync(job, canonical)
    return _ORIGINAL_ATOMIC(path, data)


def install():
    global _INSTALLED
    if _INSTALLED:
        return
    release_guard.atomic = _atomic
    _INSTALLED = True
