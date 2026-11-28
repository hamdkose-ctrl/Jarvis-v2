"""Durum satırı: ekranın üstünde tek satırda "şu an neyle konuşuyorum, bugün ne oldu".

Ekran bugüne kadar yalnız "Hazır / Düşünüyor" diyordu. Faz 1 kapanışı, ekranın **gerçek bağlantı
sonucunu** ve **son yanıtı veren modeli** göstermesini istiyor. Bu modül o satırı tek yerde kurar:
sağlayıcı + model, bugünün tur/hata sayısı ve telefon erişiminin durumu.

Kaynaklar: anlık görüntüdeki `llm` (sağlayıcı, model, anahtar) ve `phone`, ayrıca
`modules.turn_metrics` (bugünün turları). Metin **uydurulmaz**: veri yoksa eksik parçayı atlar.
Tur sayacı 30 saniye önbelleklenir; anlık görüntü saniyeler içinde tekrar tekrar istese de dosya
her seferinde okunmaz.
"""
from __future__ import annotations

import time

from modules.diagnostics import record_failure as _record_failure

_CACHE: dict[str, tuple[float, tuple[int, int]]] = {}
_CACHE_SECONDS = 30.0

_LABELS = {'auto': 'Otomatik', 'gemini': 'Gemini', 'groq': 'Groq', 'cloudflare': 'Cloudflare', 'ollama': 'Yerel',
           'custom': 'Özel API', 'lmstudio': 'LM Studio', 'llamacpp': 'llama.cpp'}


def _model(llm: dict, provider: str) -> str:
    if provider == 'ollama':
        return str(llm.get('local_model') or '').strip()
    if provider == 'groq':
        return str((llm.get('groq') or {}).get('model') or '').strip()
    names = llm.get('models') or []
    index = llm.get('active')
    if isinstance(index, int) and 0 <= index < len(names):
        return str(names[index])
    return ''


def _has_key(llm: dict, provider: str) -> bool:
    if provider == 'groq':
        return bool((llm.get('groq') or {}).get('key'))
    if provider in ('ollama', 'lmstudio', 'llamacpp'):
        return True
    if provider == 'custom':
        return bool(llm.get('custom_connections'))
    return bool(llm.get('key'))


def build(llm: dict, phone: dict, turns: tuple[int, int] | None = None) -> str:
    """Durum satırını kurar. `turns` = (bugünkü tur, bugünkü hata); bilinmiyorsa None."""
    llm = llm or {}
    provider = str(llm.get('provider') or '').strip()
    label = _LABELS.get(provider, provider or 'Model')
    if provider and not _has_key(llm, provider):
        head = f'{label} anahtarı yok'
    else:
        model = _model(llm, provider)
        head = f'{label} · {model}' if model else label
    phone = phone or {}
    phone_txt = 'telefon açık' if phone.get('running') else 'telefon kapalı'
    parts = [head]
    if turns:
        total, fails = turns
        parts.append(f'bugün {total} tur' + (f' ({fails} hata)' if fails else ''))
    parts.append(phone_txt)
    return ' · '.join(parts)


def today(owner: str) -> tuple[int, int]:
    """Bugünün (tur, hata) sayısı; 30 saniye önbellekli."""
    now = time.time()
    hit = _CACHE.get(owner)
    if hit and now - hit[0] < _CACHE_SECONDS:
        return hit[1]
    value = (0, 0)
    try:
        from modules import turn_metrics
        data = turn_metrics.rows(owner)
        value = (len(data), sum(1 for row in data if row.get('r') == 'hata'))
    except Exception:
        _record_failure('modules/status_line.py:today')
    _CACHE[owner] = (now, value)
    return value


def for_snapshot(snapshot: dict, owner: str) -> str:
    """Anlık görüntüden durum satırı; hata olursa boş metin döner (ekran bozulmaz)."""
    try:
        snap = snapshot or {}
        return build(snap.get('llm') or {}, snap.get('phone') or {}, today(owner))
    except Exception:
        _record_failure('modules/status_line.py:for_snapshot')
        return ''

