"""Tarayıcı destekli görevler: web'de arama, site açma ve bir web sayfasını özetleme."""
from __future__ import annotations

import re
from urllib.parse import quote_plus

import requests

from modules import desktop, privacy
from modules.llm import ask

_URL = re.compile(r"((?:https?://)?(?:[\w-]+\.)+(?:com|net|org|edu|gov|io|tr|co|dev|app|info|me)(?:/[^\s]*)?)", re.I)
_UA = {"User-Agent": "Mozilla/5.0 (Jarvis)"}


def page_text(url: str, limit: int = 12000) -> str:
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    r = requests.get(url, headers=_UA, timeout=15)
    r.raise_for_status()
    html = r.text
    try:
        from bs4 import BeautifulSoup
        from modules.public_sources import readable_text
        soup = BeautifulSoup(html, "html.parser")
        text = readable_text(soup)
    except ImportError:
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text)[:limit]


def summarize(url: str) -> str:
    try:
        text = page_text(url)
    except requests.RequestException as e:
        privacy.audit("sayfa özeti", url, ok=False)
        return f"Sayfaya ulaşamadım: {type(e).__name__}."
    if len(text) < 80:
        return "Sayfada okunabilir metin bulamadım (içeriği betikle yükleniyor olabilir)."
    privacy.audit("sayfa özeti", url)
    return ask("Aşağıdaki web sayfası metnini Türkçe, 4-6 cümleyle özetle. Reklam ve menü metnini yok say.\n\n" + text,
               max_tokens=700)


def handle(cmd_lower: str) -> str | None:
    wants_sum = re.search(r"özetle|özet(?:ini)? çıkar|ne anlatıyor", cmd_lower)
    m = _URL.search(cmd_lower)
    if wants_sum and m and re.search(r"sayfa|site|link|bağlantı|http|www|\.", cmd_lower):
        if (msg := privacy.blocked("web")):
            return msg
        return summarize(m.group(1))
    s = re.match(r"^(?:tarayıcıda|internette|web'?de)\s+(.{2,}?)\s+ara$", cmd_lower.strip())
    if s:
        if (msg := privacy.blocked("web")):
            return msg
        desktop.open_url(f"https://www.google.com/search?q={quote_plus(s.group(1))}")
        privacy.audit("web araması", s.group(1))
        return f"“{s.group(1)}” için tarayıcıda arama açtım."
    o = re.match(r"^(.+?)\s+(?:sitesini|sayfasını|adresini)\s+aç$", cmd_lower.strip())
    if o and (u := _URL.search(o.group(1))):
        if (msg := privacy.blocked("web")):
            return msg
        url = u.group(1) if u.group(1).startswith("http") else "https://" + u.group(1)
        desktop.open_url(url)
        privacy.audit("site açma", url)
        return f"{u.group(1)} sitesini açtım."
    return None
