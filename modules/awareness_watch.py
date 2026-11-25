"""Uyanıklık (A8): boştayken neyi fark eder, neyi görmezden gelir.

Kullanıcı kararı: sessiz sürekli bildirim yok. Bu modül yalnız **aday** üretir;
gösterip göstermeme kararı çağıranın (mevcut bildirim sahibi) işidir.

Kurallar:
- Varsayılan **kapalı** (`watch_enabled`).
- Sessiz saatler (22:00–08:00) haber üretmez.
- Aynı olay tekrar bildirilmez (parmak izi) ve 10 dakikada en fazla 1 bildirim.
- Bilinmeyen/okunamayan durum sessizce atlanır; uydurma haber yok.
"""
from __future__ import annotations

import hashlib
import time

MAX_PER_TICK = 1
COOLDOWN_SECONDS = 600
QUIET_START, QUIET_END = 22, 8
WINDOW_KEYS = ("window", "unread_mail", "next_event_minutes")


def enabled(settings: dict | None = None) -> bool:
    value = (settings or {}).get("watch_enabled")
    return bool(value)


def in_quiet_hours(hour: int) -> bool:
    return hour >= QUIET_START or hour < QUIET_END


def candidates(state: dict, *, seen: set[str], now: float | None = None,
               hour: int | None = None) -> list[dict]:
    """Durumdan bildirilebilir adaylar; gürültü süzülmüş."""
    now = time.time() if now is None else now
    hour = time.localtime(now).tm_hour if hour is None else hour
    items: list[dict] = []
    window = str(state.get("window") or "")
    if window and window != str(state.get("previous_window") or ""):
        items.append(_item("window", f"Pencere değişti: {window[:60]}", window))
    unread = int(state.get("unread_mail") or 0)
    if unread > 0:
        items.append(_item("mail", f"{unread} okunmamış mail var.", str(unread)))
    minutes = state.get("next_event_minutes")
    if isinstance(minutes, (int, float)) and 0 <= minutes <= 30:
        items.append(_item("calendar", f"{int(minutes)} dakika sonra takvimde bir iş var.", str(minutes)))
    if in_quiet_hours(hour):
        return []
    fresh = [item for item in items if item["key"] not in seen]
    return fresh[:MAX_PER_TICK]


def mark_seen(items: list[dict], seen: set[str]) -> set[str]:
    for item in items:
        seen.add(item["key"])
    return seen


def _item(kind: str, text: str, marker: str) -> dict:
    digest = hashlib.sha1(f"{kind}:{marker}".encode("utf-8")).hexdigest()[:12]
    return {"key": digest, "kind": kind, "text": text}
