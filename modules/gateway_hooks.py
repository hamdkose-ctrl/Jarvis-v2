"""Fail-closed gateway event hooks.

Hooks observe validated gateway events; they do not dispatch workers or mutate
GoalState. The caller remains responsible for any canonical RuntimeEvent path.
"""
from __future__ import annotations

from dataclasses import dataclass
import copy
import json
from typing import Callable


@dataclass(frozen=True)
class GatewayEvent:
    name: str
    payload: dict
    request_id: str | None = None

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Gateway olay adı geçersiz.")
        if not isinstance(self.payload, dict):
            raise ValueError("Gateway olay yükü nesne olmalı.")
        if self.request_id is not None and (
            not isinstance(self.request_id, str) or not self.request_id.strip()
        ):
            raise ValueError("Gateway istek kimliği geçersiz.")
        try:
            json.dumps(self.payload, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            raise ValueError("Gateway olay yükü JSON uyumlu olmalı.") from None

    def snapshot(self) -> "GatewayEvent":
        return GatewayEvent(self.name, copy.deepcopy(self.payload), self.request_id)


class GatewayHooks:
    """Small observation boundary with no execution authority."""

    def __init__(self):
        self._hooks: dict[str, list[Callable[[GatewayEvent], object]]] = {}

    def subscribe(self, event_name: str, callback: Callable[[GatewayEvent], object]) -> None:
        if not isinstance(event_name, str) or not event_name.strip():
            raise ValueError("Gateway hook olay adı geçersiz.")
        if not callable(callback):
            raise ValueError("Gateway hook callable olmalı.")
        self._hooks.setdefault(event_name, []).append(callback)

    def publish(self, event: GatewayEvent) -> dict:
        if not isinstance(event, GatewayEvent):
            raise ValueError("Gateway yalnız doğrulanmış GatewayEvent kabul eder.")
        delivered = 0
        errors = []
        for callback in tuple(self._hooks.get(event.name, ())):
            try:
                callback(event.snapshot())
                delivered += 1
            except Exception:
                errors.append({"reason_code": "HOOK_FAILED", "event": event.name})
        return {
            "schema": "gateway_hook_result.v1",
            "event": event.name,
            "request_id": event.request_id,
            "delivered": delivered,
            "errors": errors,
        }
