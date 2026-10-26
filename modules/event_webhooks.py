"""Signed generic event webhooks beyond WhatsApp (loopback receiver, opt-in).

Local configuration lives next to the other connector files:
``connector_users/<owner>/event_webhook.json`` ->
``{"enabled": true, "sources": {"github": {"secret": "<en az 16 karakter>"}}}``.
Callers sign ``<unix timestamp>.<raw body>`` with HMAC-SHA256 and send
``X-Jarvis-Timestamp: <unix timestamp>`` and ``X-Jarvis-Signature: sha256=<hex>``.
Requests older/newer than ``MAX_SKEW`` seconds, or a signature already accepted
inside that window, are rejected (replay protection).
Secrets never pass through chat or the model.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
import threading
import time

from modules import privacy, publish_services

MAX_BODY = 64 * 1024
MAX_SKEW = 300
_SEEN: dict[str, float] = {}
_SEEN_LOCK = threading.Lock()
_SOURCE = re.compile(r"[a-z0-9_-]{1,40}\Z")


def config(owner: str) -> dict:
    if privacy.blocked('web'):
        raise PermissionError('Gizlilik modu webhook alımını kapatıyor.')
    data = publish_services.configuration(owner, 'event_webhook')
    if data.get('enabled') is not True:
        raise PermissionError('Olay webhook\'u bu kullanıcıda kapalı.')
    sources = data.get('sources')
    if not isinstance(sources, dict) or not sources:
        raise PermissionError('Olay webhook kaynağı tanımlı değil.')
    for name, item in sources.items():
        if not isinstance(name, str) or not _SOURCE.fullmatch(name):
            raise ValueError('Olay webhook kaynak adı geçersiz.')
        if not isinstance(item, dict) or not isinstance(item.get('secret'), str) or len(item['secret']) < 16:
            raise PermissionError('Olay webhook imza anahtarı gerekli.')
    return data


def _accept_once(owner: str, source: str, signature: str, now: float) -> None:
    """Atomically persist one verified signature so a restart cannot reaccept it."""
    # Keep only a SHA-256 fingerprint of the already-verified signature in the
    # per-owner journal; raw request bodies and secrets are never persisted.
    fingerprint = hashlib.sha256(signature.encode('ascii')).hexdigest()
    key = owner + '/' + source + '/' + fingerprint
    with _SEEN_LOCK:
        for old in [item for item, seen in _SEEN.items() if now - seen > 2 * MAX_SKEW]:
            del _SEEN[old]
        if key in _SEEN:
            raise PermissionError('Olay isteği daha önce alındı (tekrar).')
        from modules import service_store
        with service_store.database(owner) as db:
            db.execute(
                'CREATE TABLE IF NOT EXISTS event_webhook_seen('
                'source TEXT, fingerprint TEXT, seen REAL, '
                'PRIMARY KEY(source, fingerprint))'
            )
            db.execute('DELETE FROM event_webhook_seen WHERE seen < ?', (now - 2 * MAX_SKEW,))
            try:
                db.execute(
                    'INSERT INTO event_webhook_seen(source,fingerprint,seen) VALUES(?,?,?)',
                    (source, fingerprint, now),
                )
            except sqlite3.IntegrityError:
                raise PermissionError('Olay isteği daha önce alındı (tekrar).') from None
        _SEEN[key] = now


def ingest(owner: str, source: str, body: bytes, signature: str, timestamp: str = '', *, now: float | None = None) -> dict:
    """Verify timestamp and signature first, then accept only one JSON object."""
    if not isinstance(source, str) or not _SOURCE.fullmatch(source):
        raise ValueError('Olay kaynağı geçersiz.')
    item = config(owner)['sources'].get(source)
    if item is None:
        raise PermissionError('Bu olay kaynağı kayıtlı değil.')
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_BODY:
        raise ValueError('Olay gövdesi geçersiz.')
    if not isinstance(timestamp, str) or not timestamp.isdigit() or len(timestamp) > 12:
        raise PermissionError('Olay zaman damgası gerekli.')
    now = time.time() if now is None else now
    if abs(now - int(timestamp)) > MAX_SKEW:
        raise PermissionError('Olay zaman damgası süresi dolmuş.')
    signed = timestamp.encode('ascii') + b'.' + body
    expected = 'sha256=' + hmac.new(item['secret'].encode('utf-8'), signed, hashlib.sha256).hexdigest()
    if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
        raise PermissionError('Olay imzası doğrulanamadı.')
    _accept_once(owner, source, signature, now)
    try:
        payload = json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise ValueError('Olay gövdesi JSON olmalı.') from None
    if not isinstance(payload, dict):
        raise ValueError('Olay gövdesi JSON nesnesi olmalı.')
    return payload
