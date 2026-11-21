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
    "chat": ("chat", "", "Sohbet"),
    "team": ("team", "", "Ekip Merkezi"),
    "files": ("files", "", "Dosyalar"), "messages": ("tools", "mesaj", "Mesajlar"),
    "tasks": ("tools", "takvim", "Görevler"),
}


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
    if kind == "setting_read":
        current = load_settings()
        key = action.get("key")
        if key == "wake_sensitivity":
            return f"Uyanma hassasiyeti şu an {int(current.get('wake_sensitivity') or 3)} (1 zor uyanır, 5 çok kolay uyanır)."
        return "Bu Jarvis ayarı okunabilir değil."
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
    if key in {"wake_beep", "learn_from_chat"}:
        save_settings(**{str(key): bool(value)})
        if key == "wake_beep": return f"Uyanma sesini {'açtım' if value else 'kapattım'}."
        return "Konuşmalarından öğrenmeyi " + ("açtım; öğrendiklerimi önce onayına sunarım." if value else "kapattım.")
    if key == "widget":
        emit("widget", "show" if value else "hide")
        return "Küçük Jarvis'i " + ("gösteriyorum (ana pencere açıkken görünmez)." if value else "gizledim.")
    if key == "window_mode":
        emit("win", "full" if value == "full" else "window")
        return "Tam ekrana alıyorum." if value == "full" else "Pencere moduna alıyorum."
    return "Bu Jarvis ayarı Core tarafından doğrulanmadı."


def _ui(action: Mapping[str, Any], emit: Callable[[str, str], Any]) -> str:
    key, value = action.get("key"), action.get("value")
    if key == "nx_theme" and value in {"light", "dark", "system"}:
        # Same persisted setting used by the existing UI Bridge.
        from modules import nxapi
        nxapi.ui_set("nx_theme", value)
        emit("action", "nx_set")
        return "Temayı " + {"light": "açık", "dark": "koyu", "system": "sisteme göre"}[value] + " yaptım."
    return "Bu arayüz işlemi Core tarafından doğrulanmadı."
