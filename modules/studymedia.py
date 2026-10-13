"""Çalışma ekranının yan paneli: anlatılan konuyla ilgili görseller ve videolar.

- Görseller: Türkçe Vikipedi makale görselleri + Wikimedia Commons (ücretsiz, anahtar gerekmez).
- Videolar: Ayarlar'da YouTube anahtarı varsa YouTube'dan konu anlatımı videoları (başlık + küçük resim);
  yoksa yalnızca "YouTube'da ara" bağlantısı. Videolar tarayıcıda açılır.
Sonuçlar 6 saat önbellekte tutulur (aynı konu için tekrar tekrar internete gidilmez).
"""
from __future__ import annotations
from modules.diagnostics import record_failure as _record_failure

import re
import threading
import time
import urllib.parse
import hashlib

from config import get_youtube_key

_UA = {"User-Agent": "JarvisCalisma/1.0 (kisisel egitim asistani)"}
_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()
_TTL = 6 * 3600


def _get(url: str, params: dict, timeout: float = 6.0) -> dict:
    import requests
    r = requests.get(url, params=params, headers=_UA, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _wiki_images(topic: str, limit: int = 6) -> list[dict]:
    out = []
    try:
        data = _get("https://tr.wikipedia.org/w/api.php", {
            "action": "query", "format": "json", "generator": "search", "gsrsearch": topic, "gsrlimit": 6,
            "prop": "pageimages|info", "piprop": "thumbnail", "pithumbsize": 420, "inprop": "url"})
        pages = sorted((data.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
        for p in pages:
            th = (p.get("thumbnail") or {}).get("source")
            if th:
                out.append({"src": th, "title": p.get("title", ""), "url": p.get("fullurl", ""), "from": "Vikipedi"})
    except Exception:   # noqa: BLE001 - internet yoksa panel boş kalır, çalışma etkilenmez
        _record_failure('modules/studymedia.py:_wiki_images')
        pass
    if len(out) < limit:
        try:
            data = _get("https://commons.wikimedia.org/w/api.php", {
                "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
                "gsrsearch": f"{topic} filetype:bitmap|drawing", "gsrlimit": 8,
                "prop": "imageinfo", "iiprop": "url", "iiurlwidth": 420})
            pages = sorted((data.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
            for p in pages:
                ii = (p.get("imageinfo") or [{}])[0]
                if ii.get("thumburl"):
                    title = re.sub(r"^File:|\.\w+$", "", p.get("title", "")).replace("_", " ")
                    out.append({"src": ii["thumburl"], "title": title, "url": ii.get("descriptionurl", ""), "from": "Wikimedia"})
        except Exception:   # noqa: BLE001
            _record_failure('modules/studymedia.py:_wiki_images')
            pass
    return out[:limit]


_STATE: dict = {"ok": None, "msg": "", "t": 0.0, "key": ""}   # anahtarın son denenme sonucu (ana ekranda gösterilir)


def _err_text(exc) -> str:
    try:
        body = exc.response.json()["error"]
        reason = (body.get("errors") or [{}])[0].get("reason", "")
        return {"keyInvalid": "Anahtar geçersiz", "accessNotConfigured": "YouTube Data API v3 projede etkin değil",
                "quotaExceeded": "Günlük ücretsiz hak doldu (yarın açılır)", "forbidden": "Anahtarın bu API'ye izni yok",
                "ipRefererBlocked": "Anahtar kısıtlaması bu bilgisayarı engelliyor"}.get(reason, "YouTube isteği başarısız; anahtar izinlerini ve bağlantıyı kontrol et")
    except Exception:   # noqa: BLE001
        _record_failure('modules/studymedia.py:_err_text')
        return "YouTube'a bağlanılamadı; bağlantıyı kontrol et"


def _fingerprint(key):
    return hashlib.sha256(key.encode('utf-8')).hexdigest() if key else ''


def reset_cache():
    with _lock:
        _cache.clear()


def check_key(key: str | None = None) -> dict:
    """Anahtarı en ucuz istekle (1 birim) dener; sonucu ana ekrandaki durum satırı için saklar."""
    key = (key if key is not None else get_youtube_key()).strip()
    if not key:
        _STATE.update(ok=None, msg="", t=time.time(), key="")
        return {"key": bool(key), "ok": _STATE["ok"], "msg": _STATE["msg"], "t": _STATE["t"]}
    try:
        _get("https://www.googleapis.com/youtube/v3/videos", {"part": "id", "chart": "mostPopular", "maxResults": 1,
                                                                "regionCode": "TR", "key": key})
        _STATE.update(ok=True, msg="Çalışıyor", t=time.time(), key=_fingerprint(key))
    except Exception as exc:   # noqa: BLE001
        _record_failure('modules/studymedia.py:check_key')
        _STATE.update(ok=False, msg=_err_text(exc), t=time.time(), key=_fingerprint(key))
    return {"key": bool(key), "ok": _STATE["ok"], "msg": _STATE["msg"], "t": _STATE["t"]}


def state() -> dict:
    """Ana ekran için: {"key": bool, "ok": True/False/None, "msg"}. İlk soruşta arka planda bir kez dener."""
    key = get_youtube_key().strip()
    if not key:
        return {"key": False, "ok": None, "msg": "Anahtar yok"}
    if _STATE["key"] != _fingerprint(key) or (_STATE["ok"] is None and time.time() - _STATE["t"] > 60):
        _STATE.update(key=_fingerprint(key), t=time.time())
        threading.Thread(target=check_key, args=(key,), daemon=True).start()
    return {"key": True, "ok": _STATE["ok"], "msg": _STATE["msg"] or "Deneniyor…"}


def _wiki_summary(topic: str) -> dict:
    """Konunun Vikipedi özeti (ilk uygun makale): başlık, kısa açıklama, görsel, bağlantı."""
    try:
        data = _get("https://tr.wikipedia.org/w/api.php", {"action": "query", "format": "json", "list": "search",
                                                            "srsearch": topic, "srlimit": 1})
        hits = (data.get("query") or {}).get("search") or []
        if not hits:
            return {}
        title = hits[0]["title"]
        sm = _get("https://tr.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title.replace(" ", "_")), {})
        return {"title": sm.get("title") or title, "extract": (sm.get("extract") or "")[:1200],
                "thumb": ((sm.get("originalimage") or sm.get("thumbnail") or {}).get("source") or ""),
                "url": ((sm.get("content_urls") or {}).get("desktop") or {}).get("page")
                or "https://tr.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))}
    except Exception:   # noqa: BLE001
        _record_failure('modules/studymedia.py:_wiki_summary')
        return {}


def _youtube(topic: str, key: str, limit: int = 4) -> list[dict]:
    try:
        data = _get("https://www.googleapis.com/youtube/v3/search", {  # başarılıysa durum "Çalışıyor" olur
            "part": "snippet", "q": f"{topic} konu anlatımı", "type": "video", "maxResults": limit,
            "relevanceLanguage": "tr", "regionCode": "TR", "safeSearch": "strict", "videoEmbeddable": "true", "key": key})
        return [{"id": it["id"]["videoId"], "title": it["snippet"]["title"], "channel": it["snippet"]["channelTitle"],
                 "thumb": ((it["snippet"].get("thumbnails") or {}).get("medium") or {}).get("url", ""),
                 "url": "https://www.youtube.com/watch?v=" + it["id"]["videoId"]}
                for it in data.get("items", []) if (it.get("id") or {}).get("videoId")]
    except Exception as exc:   # noqa: BLE001
        _record_failure('modules/studymedia.py:_youtube')
        _STATE.update(ok=False, msg=_err_text(exc), t=time.time(), key=_fingerprint(key))
        return []


def media(topic: str, course: str = "") -> dict:
    topic = re.sub(r"\s+", " ", (topic or "")).strip()[:80]
    if not topic:
        return {"topic": "", "images": [], "videos": [], "search": ""}
    course = re.sub(r"\s+", " ", str(course or "")).strip()[:100]
    query = f"{course} {topic}".strip()
    folded_course = course.casefold().replace("\u0307", "")
    if "biyoloji" in folded_course and "temel bileşen" in topic.casefold().replace("\u0307", ""):
        query = "Canlıların temel bileşenleri biyoloji"
    key = get_youtube_key().strip()
    ck = query.casefold() + "#" + _fingerprint(key)
    with _lock:
        hit = _cache.get(ck)
        if hit and time.time() - hit[0] < _TTL:
            return hit[1]
    out = {"topic": topic, "course": course, "query": query, "wiki": _wiki_summary(query), "images": _wiki_images(query, 8),
           "videos": _youtube(query, key, 6) if key else [],
           "search": "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query + " konu anlatımı"),
           "youtube_key": bool(key)}
    if course:
        out["images"] = [image for image in out["images"] if image.get("from") == "Vikipedi"]
        if "biyoloji" in folded_course:
            unrelated = re.compile(r"istatistik|bileşen analizi|yazılım|kovaryans|regresyon", re.I)
            if unrelated.search(out.get("wiki", {}).get("title", "")):
                out["wiki"] = {}
            out["images"] = [image for image in out["images"] if not unrelated.search(image.get("title", ""))]
    with _lock:
        _cache[ck] = (time.time(), out)
    return out
