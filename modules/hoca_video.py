"""Hoca modu kaynakları: YouTube videosu bilgisi (resmî API) ve altyazı/metin dosyası.

Video indirilmez ve YouTube'un gayriresmî altyazı adresleri kullanılmaz. Video için yalnız kullanıcının kendi
YouTube Data API anahtarıyla başlık, açıklama ve bölümler (1 kota birimi) alınır. Tam altyazı kullanıcının
kaydettiği .srt/.vtt/.txt dosyasından gelir; dosya yalnız bilinen kullanıcı klasörlerinde okunur.
"""
from __future__ import annotations

import re
from pathlib import Path

from modules.diagnostics import record_failure as _record_failure
from modules.hoca import HocaError

CHUNK = 2500
MAX_SOURCE = 60_000
_MAX_FILE = 8 * 1024 * 1024
_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_TEXT_TYPES = {".srt", ".vtt", ".txt", ".md"}
_DOC_TYPES = {".pdf", ".docx", ".rtf", ".odt", ".html", ".htm"}


def video_id(text: str) -> str | None:
    m = re.search(r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:[^\s#]*&)?v=|shorts/|embed/|live/))([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])", str(text or ""))
    return m.group(1) if m else None


_CUE_TIME = re.compile(r"^\s*(?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3}\s*-->\s*(?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3}.*$")


def parse_subtitles(raw: str) -> str:
    """SRT/VTT içeriğinden düz metin: sıra numaraları, zaman çizgileri, etiketler ve ardışık tekrarlar atılır."""
    lines, last = [], ""
    for line in str(raw or "").replace("﻿", "").splitlines():
        s = line.strip()
        if (not s or s.isdigit() or _CUE_TIME.match(s) or s.upper().startswith(("WEBVTT", "NOTE", "STYLE", "REGION"))
                or re.match(r"^(Kind|Language):", s)):
            continue
        s = re.sub(r"<[^>]+>", "", s).strip()
        if s and s != last:
            lines.append(s)
            last = s
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


_CHAPTER = re.compile(r"^\s*(?:[-•*]\s*)?((?:\d{1,2}:)?\d{1,2}:\d{2})\s*[-–—:.)]?\s*(.+?)\s*$")


def chapters(description: str) -> list[str]:
    """Açıklamadaki '0:00 Giriş' satırları; YouTube bölümleri bu biçimle tanımlanır."""
    out = []
    for line in str(description or "").splitlines():
        m = _CHAPTER.match(line)
        if m:
            out.append(f"{m.group(1)} {m.group(2)}"[:120])
    return out[:60]


def video_source(url: str, key: str | None = None) -> dict:
    """{'label','text'}: başlık, kanal, bölümler ve açıklama. Anahtar yoksa/başarısızsa açık HocaError."""
    vid = video_id(url)
    if not vid:
        raise HocaError("Video bağlantısı anlaşılamadı. youtube.com/watch?v=… veya youtu.be/… biçiminde ver.")
    if key is None:
        from config import get_youtube_key
        key = get_youtube_key()
    key = (key or "").strip()
    if not key:
        raise HocaError("Video bilgisi için YouTube anahtarı gerekir (Çalışma ekranında eklenir). Altyazıyı .srt, .vtt veya "
                        ".txt olarak kaydedip 'hoca modu: kaynak \"dosya yolu\"' diyerek de çalışabiliriz.")
    from modules import studymedia
    try:
        data = studymedia._get("https://www.googleapis.com/youtube/v3/videos", {"part": "snippet", "id": vid, "key": key})
    except Exception as exc:
        _record_failure('modules/hoca_video.py:video_source')
        raise HocaError(f"Video bilgisi alınamadı: {studymedia._err_text(exc)}.")
    items = data.get("items") or []
    if not items:
        raise HocaError("Video bulunamadı ya da herkese açık değil.")
    sn = items[0].get("snippet") or {}
    desc = str(sn.get("description") or "")
    ch = chapters(desc)
    parts = [f"Video: {sn.get('title', '')}", f"Kanal: {sn.get('channelTitle', '')}"]
    if ch:
        parts.append("Bölümler:\n" + "\n".join(ch))
    parts.append("Açıklama:\n" + desc[:4000])
    return {"label": str(sn.get("title") or "Video")[:120], "text": "\n".join(parts)[:MAX_SOURCE], "video": vid, "full": False}


def _allowed(path: Path) -> bool:
    from modules import file_ops
    try:
        real = path.resolve()
        return any(real == r.resolve() or r.resolve() in real.parents for r in file_ops._roots())
    except OSError:
        _record_failure('modules/hoca_video.py:_allowed')
        return False


def file_source(path: str) -> dict:
    """Altyazı/metin/belge dosyasından kaynak. Yalnız Masaüstü, İndirilenler, Belgeler, Resimler ve Jarvis Dosyaları altında."""
    p = Path(str(path or "").strip().strip('"'))
    if not p.is_file():
        raise HocaError(f"Dosya bulunamadı: {p.name or path}")
    if not _allowed(p):
        raise HocaError("Bu dosyayı yalnız Masaüstü, İndirilenler, Belgeler, Resimler veya Jarvis Dosyaları klasöründen okurum.")
    ext = p.suffix.lower()
    if ext not in _TEXT_TYPES | _DOC_TYPES:
        raise HocaError("Desteklenen kaynaklar: .srt, .vtt, .txt, .md, .pdf, .docx, .rtf, .odt, .html.")
    try:
        if p.stat().st_size > _MAX_FILE:
            raise HocaError("Dosya çok büyük (en çok 8 MB).")
        from modules import docs
        if ext in _TEXT_TYPES:
            raw = docs.decode_text(p.read_bytes())
            text = parse_subtitles(raw) if ext in {".srt", ".vtt"} else re.sub(r"[ \t]+", " ", raw).strip()
        else:
            text = docs.read_document(str(p)).strip()
    except HocaError:
        raise
    except Exception as exc:
        _record_failure('modules/hoca_video.py:file_source')
        raise HocaError(f"Dosya okunamadı ({type(exc).__name__}).")
    if not text:
        raise HocaError("Dosyadan metin çıkmadı.")
    return {"label": p.stem[:120], "text": text[:MAX_SOURCE], "full": True}


def chunks(text: str, size: int = CHUNK) -> list[str]:
    """Cümle/satır sınırında yaklaşık size uzunlukta parçalar."""
    text, out = str(text or "").strip(), []
    while text:
        if len(text) <= size:
            out.append(text)
            break
        cut = max(text.rfind("\n", 0, size), text.rfind(". ", 0, size) + 1, text.rfind(" ", 0, size))
        cut = cut if cut > size // 2 else size
        out.append(text[:cut].strip())
        text = text[cut:].strip()
    return out
