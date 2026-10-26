"""Validated multi-channel delivery for incoming runtime events."""
from __future__ import annotations

from modules.diagnostics import record_failure as _record_failure


_CHANNELS = frozenset({"ui", "ntfy", "webhook", "telegram", "email", "log"})


def _validate_event(event: dict) -> dict:
    if not isinstance(event, dict) or set(event) != {"source", "kind", "payload"}:
        raise ValueError("Olay şeması geçersiz.")
    if not isinstance(event["source"], str) or not event["source"].strip():
        raise ValueError("Olay kaynağı geçersiz.")
    if not isinstance(event["kind"], str) or not event["kind"].strip():
        raise ValueError("Olay türü geçersiz.")
    if not isinstance(event["payload"], dict):
        raise ValueError("Olay yükü sözlük olmalı.")
    return event


def dispatch(event: dict, sinks: dict, channels) -> dict[str, str]:
    """Deliver one immutable event to every requested channel independently.

    Sinks are injected by the owner of the channel. This module never creates
    credentials, sends arbitrary shell commands, or lets one failed channel
    suppress another channel.
    """
    event = _validate_event(event)
    if not isinstance(sinks, dict):
        raise ValueError("Olay kanalları geçersiz.")
    if not isinstance(channels, (tuple, list)) or not channels:
        raise ValueError("En az bir olay kanalı gerekli.")
    if len(set(channels)) != len(channels):
        raise ValueError("Olay kanalı tekrarlanamaz.")
    result = {}
    for channel in channels:
        if channel not in _CHANNELS:
            raise ValueError("Olay kanalı desteklenmiyor.")
        sink = sinks.get(channel)
        if not callable(sink):
            result[channel] = "unavailable"
            continue
        try:
            sink(event)
        except Exception as exc:  # channel isolation is deliberate
            _record_failure('modules/event_fanout.py:dispatch')
            result[channel] = "failed:" + type(exc).__name__
        else:
            result[channel] = "delivered"
    return result
