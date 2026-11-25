"""Dünya olay akışı (A5 / GDELT): kamuya açık, ücretsiz, anahtarsız.

Kullanıcı kararı: ücretli servis yok, uydurma yok. Bu modül yalnız **okur**:
GDELT doküman API'sinden son haber başlıklarını çeker, tekrarları atar, ilgi
alanlarına göre sıralar. Ağ yoksa/başarısızsa `offline` döner — tahmin üretmez.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from modules.diagnostics import record_failure as _record_failure

API = "https://api.gdeltproject.org/api/v2/doc/doc"
TIMEOUT = 8.0
MAX_ITEMS = 20


def build_url(query: str = "sourcecountry:turkey", limit: int = MAX_ITEMS) -> str:
    params = {"query": query, "mode": "artlist", "format": "json",
              "maxrecords": str(min(limit, MAX_ITEMS)), "sort": "datedesc"}
    return f"{API}?{urllib.parse.urlencode(params)}"


def fetch(query: str = "sourcecountry:turkey", limit: int = MAX_ITEMS,
          opener=None) -> dict:
    """Başlıkları getirir: {'status': 'ok'|'offline', 'items': [...]}."""
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(build_url(query, limit), timeout=TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except FileNotFoundError:
        raise
    except Exception:
        _record_failure("modules/world_events.py:fetch")
        return {"status": "offline", "items": [], "text": "Dünya olay akışına ulaşamadım."}
    items = _parse(payload)
    return {"status": "ok" if items else "empty", "items": items,
            "text": _text(items)}


def fold(text: str) -> str:
    table = str.maketrans("ıİşŞçÇğĞüÜöÖ", "iissccgguuoo")
    return " ".join(str(text or "").translate(table).casefold().split())


def _parse(payload) -> list[dict]:
    raw = payload.get("articles") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    items: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        title = " ".join(str(entry.get("title") or "").split())
        url = str(entry.get("url") or "")
        key = fold(title)
        if not title or not url or key in seen:
            continue
        seen.add(key)
        items.append({"title": title[:200], "url": url,
                      "domain": str(entry.get("domain") or ""),
                      "seen": str(entry.get("seendate") or "")})
    return items[:MAX_ITEMS]


def rank(items: list[dict], interests: list[str] | tuple = ()) -> list[dict]:
    """İlgi alanlarına göre sırala; ilgisizleri atmaz (kutuplaşma koruması)."""
    words = [fold(str(word)) for word in interests if str(word).strip()]
    if not words:
        return list(items)
    def score(item: dict) -> int:
        title = fold(str(item.get("title") or ""))
        return sum(1 for word in words if word in title)
    return sorted(items, key=score, reverse=True)


def _text(items: list[dict], limit: int = 5) -> str:
    if not items:
        return "Dünya olay akışında yeni başlık yok."
    lines = [f"• {item['title']} ({item['domain']})" for item in items[:limit]]
    return "Dünya olayları:\n" + "\n".join(lines)
