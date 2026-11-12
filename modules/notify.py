"""Telefona bildirim (ntfy.sh). Konu adı tahmin edilemez uzun bir rastgele addır; kimseyle paylaşma."""
from __future__ import annotations

import re
import secrets

import requests

SERVER = "https://ntfy.sh"


def new_topic() -> str:
    return "jarvis-" + secrets.token_hex(10)


def send(topic: str, title: str, message: str, timeout: float = 8) -> bool:
    """Bildirimi gönderir; başarılıysa True."""
    try:
        r = requests.post(SERVER, json={"topic": topic, "title": title, "message": message, "priority": 4,
                                        "tags": ["bell"]}, timeout=timeout)
        return r.status_code == 200
    except requests.RequestException:
        return False


def execute_typed(operation: str, prefs: dict, save) -> str:
    """Closed operation owned by existing notification profile and transport."""
    if operation == "enable":
        topic = prefs.get("ntfy_topic") or new_topic()
        prefs["ntfy_topic"] = topic
        save()
        send(topic, "Jarvis", "Telefon bildirimleri açık. Hatırlatmalar buraya gelecek.")
        return ("Telefon bildirimlerini açtım. Telefonuna ücretsiz “ntfy” uygulamasını kur, “Konuya abone ol” "
                f"diyerek şu konu adını yaz: {topic}  Bu ad bir şifre gibidir, başkasıyla paylaşma. "
                "Aboneliği yapınca bir deneme bildirimi gelmiş olacak.")
    if operation == "disable":
        prefs.pop("ntfy_topic", None)
        save()
        return "Telefon bildirimlerini kapattım."
    if operation == "test":
        topic = prefs.get("ntfy_topic")
        if not topic:
            return "Telefon bildirimi kapalı. “telefon bildirimini aç” de."
        return ("Deneme bildirimini gönderdim." if send(topic, "Jarvis", "Bu bir deneme bildirimidir.")
                else "Bildirimi gönderemedim; internet bağlantını kontrol et.")
    raise ValueError("Bilinmeyen bildirim işlemi.")


def handle(cmd_lower: str, prefs: dict, save) -> str | None:
    """Legacy intent recognition only when model unavailable."""
    t = cmd_lower.strip(" .!?")
    if re.search(r"\b(?:açma|acma|kurma|başlatma|etkinleştirme|kapatma|durdurma|gönderme)\b", t):
        return None
    if re.search(r"telefon\w*\s+bildirim\w*\s+(aç|kur|başlat|etkinleştir)|bildirimleri telefona", t):
        return execute_typed("enable", prefs, save)
    if re.search(r"telefon\w*\s+bildirim\w*\s+(kapat|durdur|iptal)", t):
        return execute_typed("disable", prefs, save)
    if re.search(r"telefon\w*\s+bildirim\w*\s+(dene|test|gönder)|telefona (bildirim|mesaj) (gönder|yolla)", t):
        return execute_typed("test", prefs, save)
    return None
