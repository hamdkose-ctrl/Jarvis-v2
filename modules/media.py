"""YouTube, Spotify ve oynatma komutları (LLM'e gitmeden çalışır)."""
from __future__ import annotations

import os
import re
import webbrowser
from urllib.parse import quote_plus, quote

from modules import requests_state
import requests

from modules import system_control

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
       "Accept-Language": "tr-TR,tr;q=0.9"}
_VERB = r"(?:aç|ara|çal|izle|oynat|dinle|göster|açar mısın)"


def spotify_installed() -> bool:
    """Windows'ta 'spotify:' bağlantısını karşılayan bir uygulama kayıtlı mı? (Yoksa Windows 'uygulama ara' penceresi açar.)"""
    if os.name != "nt":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"spotify\shell\open\command"):
            return True
    except OSError:
        return False


class BrowserOpenResult(str):
    """Launcher acceptance, not a claim that the remote website loaded."""

    def __new__(cls, message: str, *, ok: bool):
        value = super().__new__(cls, message)
        value.ok = ok
        return value


def youtube(query: str, *, browser: str = "default") -> str:
    """Use the existing YouTube worker; explicit browser never falls back silently."""
    query = query.strip()
    if not query:
        if browser not in {"default", "chrome", "firefox"}:
            return BrowserOpenResult("Tarayıcı tercihi doğrulanamadı; işlem başlatılmadı.", ok=False)
        requests_state.check()
        try:
            if browser == "default":
                accepted = bool(webbrowser.open("https://www.youtube.com", new=2))
            else:
                # A requested browser is a closed selector, never a command
                # line or executable path provided by the semantic model.
                accepted = bool(webbrowser.get(browser).open("https://www.youtube.com", new=2))
        except (webbrowser.Error, OSError, ValueError):
            accepted = False
        if not accepted:
            name = "varsayılan tarayıcı" if browser == "default" else browser.capitalize()
            return BrowserOpenResult(
                f"YouTube için {name} açma isteği kabul edilmedi; sayfayı açtığımı söyleyemem.",
                ok=False)
        name = "varsayılan tarayıcı" if browser == "default" else browser.capitalize()
        return BrowserOpenResult(
            f"YouTube'u {name} ile açma isteğini ilettim; sayfanın yüklendiğini doğrulamadım.",
            ok=True)
    try:
        html = requests.get("https://www.youtube.com/results", params={"search_query": query},
                            headers=_UA, timeout=6).text
        m = re.search(r'"videoId":"([\w-]{11})"', html)
        if m:
            requests_state.check()
            webbrowser.open(f"https://www.youtube.com/watch?v={m.group(1)}")
            return f"YouTube'da “{query}” için ilk sonucu açıyorum."
    except requests.RequestException:
        pass
    requests_state.check()
    webbrowser.open(f"https://www.youtube.com/results?search_query={quote_plus(query)}")
    return f"YouTube'da “{query}” aramasını açıyorum."


def spotify(query: str) -> str:
    """Spotify masaüstünde aramayı açar (otomatik çalma Spotify tarafında kısıtlıdır)."""
    try:
        if spotify_installed():
            requests_state.check()
            os.startfile(f"spotify:search:{quote(query)}")      # type: ignore[attr-defined]
        else:
            requests_state.check()
            webbrowser.open(f"https://open.spotify.com/search/{quote(query)}")
    except OSError:
        requests_state.check()
        webbrowser.open(f"https://open.spotify.com/search/{quote(query)}")
    return f"Spotify'da “{query}” aramasını açtım. Çalmak için ilk sonuca çift tıklaman yeterli."


def open_music() -> str:
    """'Müzik aç': Spotify kuruluysa onu, değilse YouTube Music'i açar (medya tuşu hiçbir şey açmaz)."""
    if spotify_installed():
        try:
            requests_state.check()
            os.startfile("spotify:")                               # type: ignore[attr-defined]
            return "Spotify'ı açtım. Çalmak istediğin şarkıyı seçebilirsin."
        except OSError:
            pass
    requests_state.check()
    webbrowser.open("https://music.youtube.com")
    return "YouTube Music'i açtım. Dinlemek istediğin şarkıyı seçebilirsin."


def handle(cmd_lower: str) -> str | None:
    """Komut bu modüle aitse yanıt döndürür, değilse None."""
    t = cmd_lower.strip(" .!?")         # canlı konuşmadan "YouTube'u aç." gibi noktalı gelir
    m = re.match(rf"^youtube(?:['’]?\s*(?:da|de|ta|te))?\s+(.+?)\s+{_VERB}$", t) \
        or re.match(rf"^(.+?)\s+youtube(?:['’]?\s*(?:da|de|ta|te))?\s*{_VERB}$", t)
    if m:
        return youtube(m.group(1))
    if re.match(r"^youtube(?:['’]?\s*[ıiuü])?\s+(?:aç|başlat|çalıştır)$", t):
        return youtube("")
    m = re.match(rf"^spotify(?:['’]?\s*(?:da|de|ta|te))?\s+(.+?)\s+{_VERB}$", t) \
        or re.match(rf"^(.+?)\s+spotify(?:['’]?\s*(?:da|de|ta|te))?\s*{_VERB}$", t)
    if m and not re.fullmatch(r"(?:uygulama\w*|program\w*)", m.group(1)):
        return spotify(m.group(1))
    if re.fullmatch(r"(?:bana\s+)?(?:bir\s+|biraz\s+)?(?:müzi[kğ]\w*|şarkı\w*)\s+(?:aç|açar mısın|çal|dinle)\w*", t):
        return open_music()
    if re.search(r"(müzi[kğ]\w*|şarkı\w*|videoyu|oynatmayı)\s+(durdur|duraklat|dur\b|başlat|devam|oynat|çal)|"
                 r"\b(müzik|şarkı)\s+(dursun|durdur)|devam ettir", t):
        system_control.media_control("play_pause")
        return "Tamam."
    if re.search(r"sonraki (şarkı|parça)|şarkıyı geç|parçayı geç|sonrakine geç|bir sonraki", t):
        system_control.media_control("next")
        return "Sonraki şarkıya geçtim."
    if re.search(r"önceki (şarkı|parça)|bir önceki|öncekine dön|geri al şarkı", t):
        system_control.media_control("prev")
        return "Önceki şarkıya döndüm."
    return None
