"""Signed generic event webhooks beyond WhatsApp (loopback receiver, opt-in).

Local configuration lives next to the other connector files:
``connector_users/<owner>/event_webhook.json`` ->
``{"enabled": true, "sources": {"github": {"secret": "<en az 16 karakter>"}}}``.
Callers sign the raw body with HMAC-SHA256 and send ``X-Jarvis-Signature: sha256=<hex>``.
Secrets never pass through chat or the model.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re

from modules import privacy, publish_services

MAX_BODY = 64 * 1024
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


def ingest(owner: str, source: str, body: bytes, signature: str) -> dict:
    """Verify signature first, then accept only one JSON object."""
    if not isinstance(source, str) or not _SOURCE.fullmatch(source):
        raise ValueError('Olay kaynağı geçersiz.')
    item = config(owner)['sources'].get(source)
    if item is None:
        raise PermissionError('Bu olay kaynağı kayıtlı değil.')
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_BODY:
        raise ValueError('Olay gövdesi geçersiz.')
    expected = 'sha256=' + hmac.new(item['secret'].encode('utf-8'), body, hashlib.sha256).hexdigest()
    if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
        raise PermissionError('Olay imzası doğrulanamadı.')
    try:
        payload = json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise ValueError('Olay gövdesi JSON olmalı.') from None
    if not isinstance(payload, dict):
        raise ValueError('Olay gövdesi JSON nesnesi olmalı.')
    return payload
