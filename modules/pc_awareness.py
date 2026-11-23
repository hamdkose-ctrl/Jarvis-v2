"""Ekranda ne olduğunu tek parça söyler: ön plandaki pencere + görünen pencereler.

Neden: kullanıcı "ekranda ne var / hangi program açık" diye sorduğunda cevap
modelden geliyordu; model ekranı görmediği için tahmin ediyordu. Oysa bu bilgi
Windows'tan **kesin** okunabiliyor. Bu modül yalnız OKUR: tıklama, yazma veya
pencere değiştirme yok — bu yüzden Core onay kapısına da girmez.

Kullanılan mevcut sahipler (kopya çıkarılmadı, aynı kaynak):
* `system_control._app_windows()` — görünür üst düzey pencereler (başlık, program).
* `system_control._window_api().GetForegroundWindow()` — ön plandaki pencere.
"""
from __future__ import annotations

import os

from modules.diagnostics import record_failure as _record_failure

# Aynı programın onlarca penceresi olabilir; özet tekrara düşmesin.
MAX_LISTED = 8


def _foreground_handle() -> int | None:
    if os.name != "nt":
        return None
    try:
        from modules import system_control
        return int(system_control._window_api().GetForegroundWindow())
    except Exception:
        _record_failure("modules/pc_awareness.py:foreground")
        return None


def snapshot() -> dict:
    """Ekranın şu anki durumu: ön plan, görünen pencereler, ekran ölçüsü.

    Windows dışında ya da okuma başarısız olursa boş yapı döner; çağıran
    "bilmiyorum" diyebilsin diye hata yutulmaz ama tur da düşürülmez.
    """
    state: dict = {"foreground": None, "windows": [], "screen": None, "platform": os.name}
    if os.name != "nt":
        return state
    try:
        from modules import system_control
        windows = system_control._app_windows()
    except Exception:
        _record_failure("modules/pc_awareness.py:windows")
        return state
    foreground = _foreground_handle()
    rows = [{"hwnd": hwnd, "title": title, "app": app} for hwnd, title, app in windows]
    for row in rows:
        if foreground is not None and row["hwnd"] == foreground:
            state["foreground"] = row
            break
    state["windows"] = rows
    try:
        import pyautogui
        width, height = pyautogui.size()
        state["screen"] = {"width": int(width), "height": int(height)}
    except Exception:
        _record_failure("modules/pc_awareness.py:screen_size")
    return state


def _clean_title(title: str) -> str:
    """Uzun başlıkları kısalt; tırnak içindeki uygulama adını koru."""
    text = " ".join(str(title or "").split())
    return text if len(text) <= 70 else text[:69] + "…"


def summary(state: dict | None = None) -> str:
    """Tek cümlelik, seslenebilir özet. Bilinmeyen durumda dürüst cevap."""
    state = snapshot() if state is None else state
    foreground = state.get("foreground")
    windows = state.get("windows") or []
    if not windows and not foreground:
        return "Ekranı okuyamadım; pencere bilgisi şu an gelmiyor."
    parts = []
    if foreground:
        parts.append(f"Önde {foreground['app']} açık: “{_clean_title(foreground['title'])}”.")
    app_counts: dict[str, int] = {}
    for row in windows:
        app_counts[row["app"]] = app_counts.get(row["app"], 0) + 1
    if app_counts:
        ordered = sorted(app_counts.items(), key=lambda item: (-item[1], item[0]))
        shown = ", ".join(
            f"{app} ({count} pencere)" if count > 1 else app
            for app, count in ordered[:MAX_LISTED])
        extra = len(ordered) - MAX_LISTED
        parts.append(f"Açık programlar: {shown}" + (f" ve {extra} tane daha." if extra > 0 else "."))
    screen = state.get("screen")
    if screen:
        parts.append(f"Ekran {screen['width']}×{screen['height']}.")
    return " ".join(parts)


def titles(state: dict | None = None) -> list[str]:
    """Görünen pencerelerin başlıkları (ön plandaki ilk sırada)."""
    state = snapshot() if state is None else state
    rows = list(state.get("windows") or [])
    foreground = state.get("foreground")
    if foreground:
        rows.sort(key=lambda row: 0 if row["hwnd"] == foreground["hwnd"] else 1)
    return [_clean_title(row["title"]) for row in rows]
