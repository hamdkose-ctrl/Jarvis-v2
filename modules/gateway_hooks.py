"""Gateway event hooks and a sandbox-gated shell stub."""
from __future__ import annotations

import copy
import time


EVENTS = frozenset({"request.accepted", "request.rejected", "gateway.error", "shell.blocked"})


def emit(name: str, payload: dict, observers) -> list[str]:
    if name not in EVENTS:
        raise ValueError("Gateway olayı desteklenmiyor.")
    if not isinstance(payload, dict) or not isinstance(observers, (list, tuple)):
        raise ValueError("Gateway hook girdisi geçersiz.")
    event = {"name": name, "payload": copy.deepcopy(payload), "occurred_at": time.time()}
    result = []
    for observer in observers:
        if not callable(observer):
            result.append("unavailable")
            continue
        try:
            observer(copy.deepcopy(event))
        except Exception as exc:
            result.append("failed:" + type(exc).__name__)
        else:
            result.append("delivered")
    return result


def shell_before(command: str, *, sandbox_ready: bool = False) -> dict:
    if not isinstance(command, str) or not command.strip():
        raise ValueError("Shell komutu boş olamaz.")
    if sandbox_ready is not True:
        return {"allowed": False, "reason_code": "SANDBOX_REQUIRED", "command": command}
    return {"allowed": False, "reason_code": "SHELL_STUB_ONLY", "command": command}
