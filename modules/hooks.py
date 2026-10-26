"""Observer-only lifecycle hooks for Jarvis execution telemetry."""
from __future__ import annotations

import copy
import threading
import time
from collections import defaultdict
from collections.abc import Callable

from modules.diagnostics import record_failure as _record_failure


HOOK_NAMES = (
    "agent",
    "tool",
    "model",
    "approval",
    "session",
    "sub_agent",
    "kanban",
)

_LOCK = threading.RLock()
_HOOKS: dict[tuple[str | None, str], list[Callable]] = defaultdict(list)


def _check_name(name: str) -> str:
    if name not in HOOK_NAMES:
        raise ValueError("Hook adı desteklenmiyor.")
    return name


def register(name: str, callback: Callable, *, owner: str | None = None) -> None:
    """Register an observer. Its return value can never affect execution."""
    _check_name(name)
    if not callable(callback):
        raise ValueError("Hook gözlemcisi callable olmalı.")
    if owner is not None and (not isinstance(owner, str) or not owner):
        raise ValueError("Hook sahibi geçersiz.")
    with _LOCK:
        _HOOKS[(owner, name)].append(callback)


def clear(*, owner: str | None = None) -> None:
    with _LOCK:
        if owner is None:
            _HOOKS.clear()
        else:
            for key in tuple(_HOOKS):
                if key[0] == owner:
                    _HOOKS.pop(key, None)


def emit(name: str, payload: dict, *, owner: str | None = None) -> list[str]:
    """Notify global and owner-scoped observers with an immutable event copy."""
    _check_name(name)
    if not isinstance(payload, dict):
        raise ValueError("Hook yükü sözlük olmalı.")
    with _LOCK:
        callbacks = tuple(_HOOKS.get((None, name), ())) + tuple(_HOOKS.get((owner, name), ()))
    event = {
        "name": name,
        "owner": owner,
        "occurred_at": time.time(),
        "payload": copy.deepcopy(payload),
    }
    result = []
    for callback in callbacks:
        try:
            callback(copy.deepcopy(event))
        except Exception as exc:  # observer failure never changes execution
            _record_failure('modules/hooks.py:emit')
            result.append("failed:" + type(exc).__name__)
        else:
            result.append("delivered")
    return result
