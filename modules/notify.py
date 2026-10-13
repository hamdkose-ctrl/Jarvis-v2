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


def handle(cmd_lower: str, prefs: dict, save) -> str | None:
    """Telefon bildirimi komutları. prefs: profil tercihleri sözlüğü, save: kaydetme işlevi."""
    t = cmd_lower
    if re.search(r"telefon\w*\s+bildirim\w*\s+(aç|kur|başlat|etkinleştir)|bildirimleri telefona", t):
        topic = prefs.get("ntfy_topic") or new_topic()
        prefs["ntfy_topic"] = topic
        save()
        send(topic, "Jarvis", "Telefon bildirimleri açık. Hatırlatmalar buraya gelecek.")
        return ("Telefon bildirimlerini açtım. Telefonuna ücretsiz “ntfy” uygulamasını kur, “Konuya abone ol” "
                f"diyerek şu konu adını yaz: {topic}  Bu ad bir şifre gibidir, başkasıyla paylaşma. "
                "Aboneliği yapınca bir deneme bildirimi gelmiş olacak.")
    if re.search(r"telefon\w*\s+bildirim\w*\s+(kapat|durdur|iptal)", t):
        prefs.pop("ntfy_topic", None)
        save()
        return "Telefon bildirimlerini kapattım."
    if re.search(r"telefon\w*\s+bildirim\w*\s+(dene|test|gönder)|telefona (bildirim|mesaj) (gönder|yolla)", t):
        topic = prefs.get("ntfy_topic")
        if not topic:
            return "Telefon bildirimi kapalı. “telefon bildirimini aç” de."
        return "Deneme bildirimini gönderdim." if send(topic, "Jarvis", "Bu bir deneme bildirimidir.") \
            else "Bildirimi gönderemedim; internet bağlantını kontrol et."
    return None
