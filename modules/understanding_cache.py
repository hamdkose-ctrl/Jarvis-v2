"""Anlama sözleşmesinin Gemini bağlam önbelleği (ayarla açılır).

Sorun: anlama isteğinde girdi medyan 13.004 token; bunun ~9-10 bini 68 yeteneğin
argüman şeması (34,6k karakter). Şema her turda aynı; sağlayıcı onu her seferinde
yeniden okuyor. Önbellek, aynı sözleşmeyi bir kez yükleyip sonraki turlarda
referans verir: model yine her alanı bilir (davranış aynı), sadece prefill
tekrarlanmaz.

Kurallar:
- Varsayılan KAPALI (`understanding_cache` ayarı). Açıkken bile herhangi bir
  hata sessizce eski yola düşer: cevapsız tur üretmez.
- Önbellek sağlayıcı/model başına; anahtar sözleşme metninin özetidir.
- Süre (TTL) dolduğunda yeniden kurulur; eski tutamak bırakılır.
"""
from __future__ import annotations

import hashlib
import threading
import time

TTL_SECONDS = 3600
# Kurulamayan bir sözleşme için her turda yeniden denemeyi engelleyen bekleme.
RETRY_SECONDS = 240

_LOCK = threading.Lock()
_HANDLES: dict[tuple[str, str, str], tuple[str, float]] = {}
_BLOCKED: dict[tuple[str, str, str], float] = {}
_STATS = {'hit': 0, 'miss': 0}


def note(hit: bool) -> None:
    with _LOCK:
        _STATS['hit' if hit else 'miss'] += 1


def stats() -> dict[str, int]:
    with _LOCK:
        return dict(_STATS)


def enabled() -> bool:
    """Ayar kapalıysa hiçbir şey değişmez (varsayılan)."""
    try:
        from config import load_settings
        return bool(load_settings().get("understanding_cache", False))
    except Exception:
        return False


def _key(owner: str, model: str, contract: str) -> tuple[str, str, str]:
    return (str(owner), str(model), hashlib.sha256(contract.encode('utf-8')).hexdigest()[:32])


def forget(owner: str | None = None) -> None:
    """Test/geri alma: tutamakları düşür (sağlayıcı tarafındaki kayıt TTL ile ölür)."""
    with _LOCK:
        for key in list(_HANDLES):
            if owner is None or key[0] == owner:
                _HANDLES.pop(key, None)
        for key in list(_BLOCKED):
            if owner is None or key[0] == owner:
                _BLOCKED.pop(key, None)


def acquire(owner: str, model: str, contract: str, system: str) -> str | None:
    """Sözleşme için canlı önbellek tutamacı döndür; kurulamazsa None (eski yol)."""
    if not enabled():
        return None
    if not isinstance(contract, str) or not contract.strip():
        return None
    key = _key(owner, model, contract)
    now = time.monotonic()
    with _LOCK:
        hit = _HANDLES.get(key)
        if hit is not None and hit[1] > now:
            return hit[0]
        if _BLOCKED.get(key, 0.0) > now:
            return None
    try:
        name = _create(owner, model, contract, system)
    except Exception:
        from modules.diagnostics import record_failure as _record_failure
        _record_failure('modules/understanding_cache.py:create')
        with _LOCK:
            _BLOCKED[key] = now + RETRY_SECONDS
        return None
    if not name:
        with _LOCK:
            _BLOCKED[key] = now + RETRY_SECONDS
        return None
    with _LOCK:
        _HANDLES[key] = (name, now + TTL_SECONDS - 60)
        _BLOCKED.pop(key, None)
    return name


def _create(owner: str, model: str, contract: str, system: str) -> str | None:
    """Sağlayıcıda önbellek nesnesi kur; adı döndür."""
    from google.genai import types
    from modules import llm
    with llm.owner_context(owner):
        client = llm._cli()
        if client is None:
            return None
        cached = client.caches.create(
            model=model,
            config=types.CreateCachedContentConfig(
                system_instruction=system or None,
                contents=[types.Content(role='user', parts=[types.Part(text=contract)])],
                ttl=f'{TTL_SECONDS}s',
                display_name='jarvis-understanding',
            ),
        )
        return getattr(cached, 'name', None)
