"""Cloudflare Workers AI text chat adapter (Provider Routing Policy v1, P0-2).

A transport only: one request, one answer, typed errors. It never chooses a provider, retries across
providers or falls back; the Router (P0-3) is the only authority. Credentials are the same per-user
Cloudflare account id and token already used by ``image_gen`` (no shared/default key).
"""
from __future__ import annotations

import json

from modules import failure_policy, requests_state, usage_meter
from modules.diagnostics import record_failure as _record_failure
from modules.image_gen import user_cloudflare_account, user_cloudflare_token

MODEL = "@cf/meta/llama-3.1-8b-instruct"
_TIMEOUT = (5, 30)


def _bounded_timeouts():
    """Cap socket timeouts by the request's remaining budget, not a new deadline."""
    remaining = requests_state.budget_remaining()
    if remaining is None:
        return _TIMEOUT
    ceiling = max(.05, remaining)
    return tuple(min(t, ceiling) for t in _TIMEOUT)


class CloudflareChatError(RuntimeError):
    def __init__(self, message: str, reason_code: str):
        super().__init__(message)
        self.reason_code = reason_code


class _HttpStatusError(RuntimeError):
    def __init__(self, status_code: int, text: str = ""):
        super().__init__(text or f"HTTP {status_code}")
        self.status_code = status_code


def configured(slug: str | None) -> bool:
    return bool(user_cloudflare_account(slug) and user_cloudflare_token(slug))


def chat(messages: list[dict], system: str = "", max_tokens: int = 512, *, slug: str,
         model: str = MODEL, _session=None) -> str:
    if not slug:
        raise CloudflareChatError("Kullanıcı bağlamı olmadan Cloudflare çağrılamaz.", "NO_USER")
    if not isinstance(messages, list) or not messages:
        raise CloudflareChatError("Boş istek gönderilemez.", "EMPTY_PROMPT")
    account, token = user_cloudflare_account(slug), user_cloudflare_token(slug)
    if not account or not token:
        raise CloudflareChatError("Bu kullanıcı için Cloudflare hesap kimliği/API token tanımlı değil.", "NO_KEY")
    rows = ([{"role": "system", "content": system}] if system else []) + [dict(m) for m in messages]
    chars_in = usage_meter.size(rows)
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"messages": rows, "max_tokens": max(1, min(int(max_tokens), 4096))}
    session = _session
    if session is None:
        import requests
        session = requests
    requests_state.check()
    try:
        resp = session.post(url, headers=headers, data=json.dumps(body), timeout=_bounded_timeouts())
    except Exception as exc:
        _record_failure('modules/cloudflare_chat.py:chat:request')
        category = failure_policy.classify(exc)
        network = category in {failure_policy.DNS, failure_policy.NETWORK, failure_policy.TIMEOUT}
        usage_meter.record('cloudflare', model, chars_in, 0,
                           'baglanti' if network else 'hata', owner=slug)
        raise CloudflareChatError("Cloudflare'e ulaşılamadı." if network else "Cloudflare isteği başarısız oldu.",
                                  "NETWORK_ERROR" if network else "PROVIDER_ERROR") from exc
    if resp.status_code != 200:
        usage_meter.record('cloudflare', model, chars_in, 0, str(resp.status_code), owner=slug)
        category = failure_policy.classify(_HttpStatusError(resp.status_code, getattr(resp, "text", "")))
        if category == failure_policy.AUTH:
            raise CloudflareChatError("Cloudflare kimlik doğrulaması başarısız (token/hesap kontrolü).", "AUTH_FAILED")
        if category in (failure_policy.RATE_LIMIT, failure_policy.QUOTA_EXHAUSTED):
            raise CloudflareChatError("Günlük ücretsiz Neuron kotası dolmuş olabilir.", "QUOTA_EXCEEDED")
        raise CloudflareChatError(f"Cloudflare hata döndürdü (HTTP {resp.status_code}).", "PROVIDER_ERROR")
    try:
        payload = resp.json()
        text = payload["result"]["response"]
    except (KeyError, TypeError, ValueError, AttributeError):
        usage_meter.record('cloudflare', model, chars_in, 0, 'bozuk', owner=slug)
        raise CloudflareChatError("Beklenmeyen yanıt biçimi.", "UNEXPECTED_FORMAT")
    if not isinstance(text, str) or not text.strip():
        usage_meter.record('cloudflare', model, chars_in, 0, 'bos', owner=slug)
        raise CloudflareChatError("Cloudflare boş yanıt döndürdü.", "EMPTY_RESPONSE")
    usage_meter.record('cloudflare', model, chars_in, len(text), 'ok', owner=slug)
    requests_state.check()  # late replies are metered but never adopted
    return text
