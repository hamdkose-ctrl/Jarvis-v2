"""Uyanıklık (A8): boştayken neyi fark eder, neyi görmezden gelir.

Kullanıcı kararı: sessiz sürekli bildirim yok. Bu modül yalnız **aday** üretir;
gösterip göstermeme kararı çağıranın (mevcut bildirim sahibi) işidir.

Kurallar:
- Varsayılan **kapalı** (`watch_enabled`).
- Sessiz saatler (22:00–08:00) haber üretmez.
- Aynı olay tekrar bildirilmez (parmak izi). Bir tikte en fazla `MAX_PER_TICK` (1)
  aday döner; bu bir **hız sınırı değildir**. Farklı olaylar farklı tiklerde hemen
  bildirilir: zaman-kritik takvim uyarısı ("5 dakika sonra toplantı") bekleme
  süresi yüzünden gecikmemeli. (Önceki belge "10 dakikada 1" diyordu; kod bunu
  hiç uygulamıyordu, uygulamak da takvim uyarısını geciktirirdi.)
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


def quiet_bounds(settings: dict | None = None) -> tuple[int, int]:
    """Sessiz saat sınırları ayardan gelir; geçersiz değerde varsayılan (22–08)."""
    settings = settings or {}
    try:
        start = int(settings.get("watch_quiet_start", QUIET_START))
        end = int(settings.get("watch_quiet_end", QUIET_END))
    except (TypeError, ValueError):
        return QUIET_START, QUIET_END
    if not (0 <= start <= 23 and 0 <= end <= 23) or start == end:
        return QUIET_START, QUIET_END
    return start, end


def in_quiet_hours(hour: int, bounds: tuple[int, int] = (QUIET_START, QUIET_END)) -> bool:
    start, end = bounds
    if start > end:                      # gece devreden saat (22 → 08)
        return hour >= start or hour < end
    return start <= hour < end


def candidates(state: dict, *, seen: set[str], now: float | None = None,
               hour: int | None = None,
               quiet: tuple[int, int] = (QUIET_START, QUIET_END)) -> list[dict]:
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
    if in_quiet_hours(hour, quiet):
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
