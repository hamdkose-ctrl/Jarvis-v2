"""Signed generic event webhook (non-WhatsApp) and channel sinks for event fanout.

Configuration lives in the owner's private connector file ``event_hook.json``:
``{"enabled": true, "secret": "<32+ chars>", "sources": ["github"], "channels": ["ui", "ntfy"]}``.
The sender signs ``<timestamp>.<raw body>`` with HMAC-SHA256 and sends
``X-Jarvis-Timestamp`` and ``X-Jarvis-Signature: sha256=<hex>``. Events never run commands.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time

from modules import privacy, publish_services as services
from modules.event_fanout import _CHANNELS

MAX_BODY = 65536
MAX_SKEW = 300
DEFAULT_CHANNELS = ("ui", "ntfy")
_SLUG = re.compile(r"[a-z][a-z0-9_-]{0,39}")


def config(owner):
    if privacy.blocked("web"):
        raise PermissionError("Gizlilik modu webhook alımını kapatıyor.")
    data = services.configuration(owner, "event_hook")
    if data.get("enabled") is not True:
        raise PermissionError("Olay webhook'u bu kullanıcıda kapalı.")
    if not isinstance(data.get("secret"), str) or len(data["secret"]) < 32:
        raise PermissionError("Olay webhook sırrı en az 32 karakter olmalı.")
    sources = data.get("sources")
    if sources is not None and (not isinstance(sources, list) or not all(isinstance(s, str) and _SLUG.fullmatch(s) for s in sources)):
        raise PermissionError("Olay kaynak listesi geçersiz.")
    return data


def channels(data) -> tuple:
    """Requested channels from config; unknown or repeated names fail closed to the default."""
    value = data.get("channels") if isinstance(data, dict) else None
    if not isinstance(value, list) or not value or len(set(value)) != len(value) or not all(c in _CHANNELS for c in value):
        return DEFAULT_CHANNELS
    return tuple(value)


def parse(owner, source, raw, timestamp, signature, now=None):
    """Verify one signed request and return a fanout event plus the owner's channels."""
    data = config(owner)
    if not isinstance(source, str) or not _SLUG.fullmatch(source):
        raise ValueError("Olay kaynağı geçersiz.")
    if data.get("sources") is not None and source not in data["sources"]:
        raise PermissionError("Olay kaynağı izinli değil.")
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BODY:
        raise ValueError("Olay gövde sınırı geçersiz.")
    if not isinstance(timestamp, str) or not timestamp.isdigit() or len(timestamp) > 12:
        raise PermissionError("Olay zaman damgası geçersiz.")
    if abs((time.time() if now is None else now) - int(timestamp)) > MAX_SKEW:
        raise PermissionError("Olay zaman damgası süresi dolmuş.")
    expected = "sha256=" + hmac.new(data["secret"].encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
        raise PermissionError("Olay imzası geçersiz.")
    body = json.loads(raw)
    if not isinstance(body, dict) or not set(body) <= {"kind", "payload"}:
        raise ValueError("Olay şeması geçersiz.")
    kind = body.get("kind")
    payload = body.get("payload", {})
    if not isinstance(kind, str) or not _SLUG.fullmatch(kind) or not isinstance(payload, dict):
        raise ValueError("Olay şeması geçersiz.")
    return {"source": "hook:" + source, "kind": kind, "payload": payload}, channels(data)


def summary(event) -> str:
    """Short human text for chat/phone; payload text is clipped, never executed."""
    text = event["payload"].get("text") or event["payload"].get("title") or ""
    text = " ".join(str(text).split())[:300]
    head = f"Olay ({event['source']} · {event['kind']})"
    return head + (": " + text if text else ".")


def sinks(emit, ntfy_topic, send, log):
    """Channel callables for event_fanout.dispatch. Missing setup leaves a channel unavailable."""
    out = {"ui": lambda event: emit(summary(event)), "log": lambda event: log(summary(event))}
    if ntfy_topic:
        def ntfy(event):
            if not send(ntfy_topic, "Jarvis olay", summary(event)):
                raise ConnectionError("ntfy gönderilemedi")
        out["ntfy"] = ntfy
    return out
