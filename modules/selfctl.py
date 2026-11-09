"""Typed adapter for Jarvis' own navigation, settings, UI and maintenance actions.

Natural-language ownership is deliberately absent from this module. Understanding
proposes a closed action, Core validates it, and this adapter applies only that
validated payload.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Callable, Mapping

from config import DATA_DIR, load_settings, save_settings


# Product identifiers, not utterance patterns. Core validates the same closed keys.
PAGES: dict[str, tuple[str, str, str]] = {
    "home": ("home", "", "Ana Sayfa"), "ai": ("settings", "ai", "Yapay zekâ"),
    "connections": ("settings", "baglanti", "Bağlantılar"), "sound": ("settings", "ses", "Ses ayarları"),
    "knowledge": ("tools", "kb", "Bilgi tabanı"), "memory": ("settings", "hafiza", "Hafıza"),
    "phone": ("tools", "telefon", "Telefon"), "github": ("settings", "github", "GitHub ve güncelleme"),
    "communication": ("settings", "iletisim", "Telefon ve mesajlar"),
    "screen_files": ("settings", "ekran", "Ekran ve dosyalar"),
    "account": ("settings", "kullanici", "Hesap ve gizlilik"), "settings": ("settings", "genel", "Ayarlar"),
    "security": ("settings", "guvenlik", "Güvenlik"), "users": ("settings", "kullanici", "Kullanıcı"),
    "vision": ("vision", "", "Görsel Analiz"), "tools": ("tools", "", "Araçlar"),
    "study": ("study", "", "Çalışma"), "notes": ("tools", "takvim", "Notlar"),
    "calendar": ("tools", "takvim", "Takvim"), "scan": ("tools", "tarama", "Sistem Taraması"),
    "report": ("tools", "rapor", "Gelişim Raporu"), "about": ("settings", "hakkinda", "Hakkında"),
    "menu": ("menu", "", "Menü"), "chat": ("chat", "", "Sohbet"),
    "files": ("files", "", "Dosyalar"), "messages": ("tools", "mesaj", "Mesajlar"),
    "tasks": ("tools", "takvim", "Görevler"),
}
TONES = {"blue": "Mavi", "turquoise": "Turkuaz", "yellow": "Sarı"}
SPEEDS = {"fast": (600, "hızlı"), "balanced": (1100, "dengeli"), "patient": (1700, "sabırlı")}


def execute(action: Mapping[str, Any], emit: Callable[[str, str], Any]) -> str:
    """Apply a Core-validated closed action; never inspect the original utterance."""
    kind = action.get("kind")
    if kind == "navigate":
        page = PAGES.get(str(action.get("page") or ""))
        if page is None:
            return "Bu Jarvis sayfası Core tarafından doğrulanmadı."
        top, sub, name = page
        emit("nav", f"{top}|{sub}")
        return f"{name} sayfasını açıyorum."
    if kind == "restart":
        emit("restart", "")
        return "Yeniden başlatıyorum, birkaç saniye içinde geri döneceğim."
    if kind == "open_data":
        target = DATA_DIR / "jarvis.log" if action.get("target") == "log" else DATA_DIR
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(target))  # type: ignore[attr-defined]  # noqa: S606
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(target)])
        except OSError:
            return "Jarvis veri yolunu açamadım."
        return "Log dosyasını açtım." if target.suffix else "Jarvis veri klasörünü açtım."
    if kind == "setting":
        return _setting(action, emit)
    if kind == "ui":
        return _ui(action, emit)
    return "Bu Jarvis işlemi Core tarafından doğrulanmadı."


def _setting(action: Mapping[str, Any], emit: Callable[[str, str], Any]) -> str:
    key, value = action.get("key"), action.get("value")
    settings = load_settings()
    if key == "wake_sensitivity":
        current = int(settings.get("wake_sensitivity") or 3)
        new = value if isinstance(value, int) else min(5, current + 1) if value == "increase" else max(1, current - 1)
        save_settings(wake_sensitivity=new)
        return (f"Uyanma hassasiyeti zaten {current} (1 zor uyanır, 5 çok kolay uyanır)." if new == current
                else f"Uyanma hassasiyetini {current} seviyesinden {new} seviyesine aldım (1 zor uyanır, 5 çok kolay uyanır).")
    if key == "response_speed":
        ms, name = SPEEDS[str(value)]
        save_settings(live_silence_ms=ms)
        return f"Cevap hızını {name} yaptım; bir sonraki konuşmada geçerli olur."
    if key in {"wake_beep", "learn_from_chat", "live_mode"}:
        setting = {"wake_beep": "live_beep", "learn_from_chat": "learn_from_chat", "live_mode": "live_mode"}[str(key)]
        save_settings(**{setting: bool(value)})
        if key == "wake_beep": return f"Uyanma sesini {'açtım' if value else 'kapattım'}."
        if key == "learn_from_chat": return "Konuşmalarından öğrenmeyi " + ("açtım; öğrendiklerimi önce onayına sunarım." if value else "kapattım.")
        return f"Canlı konuşmayı {'açtım' if value else 'kapattım'}. Geçerli olması için “kendini yeniden başlat” de."
    if key == "idle_seconds":
        save_settings(live_idle_seconds=value)
        return f"Konuşma bittikten sonra {value} saniye açık kalacağım."
    if key == "widget":
        emit("widget", "show" if value else "hide")
        return "Küçük Jarvis'i " + ("gösteriyorum (ana pencere açıkken görünmez)." if value else "gizledim.")
    if key == "window_mode":
        emit("win", "full" if value == "full" else "window")
        return "Tam ekrana alıyorum." if value == "full" else "Pencere moduna alıyorum."
    return "Bu Jarvis ayarı Core tarafından doğrulanmadı."


def _ui(action: Mapping[str, Any], emit: Callable[[str, str], Any]) -> str:
    key, value = action.get("key"), action.get("value")
    if key == "hologram_tone" and value in TONES:
        emit("ui", f"hologramtone|{value}")
        return f"Hologram rengini {TONES[value].lower()} yaptım."
    if key == "hologram_background" and value in {"lava", "mountains"}:
        emit("ui", f"hologrambg|{value}")
        return "Arka planı lav dağları yaptım." if value == "lava" else "Arka planı mavi dağlar yaptım."
    if key == "replay":
        emit("ui", "bustreplay|")
        return "Açılış animasyonunu baştan oynatıyorum."
    if key == "home_animation" and isinstance(value, bool):
        emit("ui", f"nxbust|{1 if value else 0}")
        return "Ana ekran animasyonunu " + ("açtım." if value else "kapattım; durağan görünüm kullanılacak.")
    return "Bu arayüz işlemi Core tarafından doğrulanmadı."
