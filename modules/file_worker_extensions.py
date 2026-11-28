"""Phase 4B FileWorker hardening: bounded read/search and explicit document outputs."""
from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
import time
from pathlib import Path

import release_guard

from modules import file_resource_guard, resource_leases

MAX_PATCH_BYTES = 10 * 1024 * 1024
MAX_SEARCH_BYTES = 5 * 1024 * 1024
MAX_SEARCH_FILES = 500
MAX_RESULTS = 50


class FileWorkerExtensionError(ValueError):
    pass


def _regular(path: Path, *, max_bytes: int) -> os.stat_result:
    try:
        info = path.stat()
    except OSError as exc:
        raise FileWorkerExtensionError("Dosya okunamadı.") from exc
    if not stat.S_ISREG(info.st_mode):
        raise FileWorkerExtensionError("Özel dosya türü okunamaz veya değiştirilemez.")
    if info.st_size > max_bytes:
        raise FileWorkerExtensionError("Dosya güvenli boyut sınırını aşıyor.")
    return info


def _minified(path: Path, text: str) -> bool:
    if path.suffix.lower() in {".min.js", ".min.css", ".bundle.js", ".bundle.css"}:
        return True
    lines = text.splitlines()
    return bool(lines) and (max(map(len, lines)) > 5000 or len(lines) <= 2 and len(text) > 8000)


_MONTHS_TR = {
    "ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "mayis": 5,
    "haziran": 6, "temmuz": 7, "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9,
    "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12,
}
_MONTH_NAMES = "|".join(sorted(_MONTHS_TR, key=len, reverse=True))
_DATE_ISO = re.compile(r"\b((?:19|20)\d{2})-(\d{1,2})-(\d{1,2})\b")
_DATE_DMY = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./]((?:19|20)\d{2})\b")
_DATE_TR_MONTH = re.compile(rf"\b(\d{{1,2}})\s+({_MONTH_NAMES})\s+((?:19|20)\d{{2}})\b", re.IGNORECASE)


def _normalize_date(year: int, month: int, day: int) -> str | None:
    """Gerçek takvim tarihi doğrular; uydurma/eksik tarih None döner."""
    from datetime import date
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def extract_dates(text: str) -> list[str]:
    """Metindeki gerçek tarihleri ISO YYYY-MM-DD olarak, görünüş sırasıyla döner.

    Desteklenen biçimler: `2026-12-05`, `05.12.2026` / `05/12/2026` ve
    `5 Aralık 2026`. Geçersiz takvim değeri (ör. 31.02) ve çözülemeyen tarih
    listede yer almaz; asla tarih uydurulmaz.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    found: list[tuple[int, str]] = []
    for m in _DATE_ISO.finditer(text):
        iso = _normalize_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if iso:
            found.append((m.start(), iso))
    for m in _DATE_DMY.finditer(text):
        iso = _normalize_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if iso:
            found.append((m.start(), iso))
    for m in _DATE_TR_MONTH.finditer(text):
        month = _MONTHS_TR.get(m.group(2).casefold())
        if month:
            iso = _normalize_date(int(m.group(3)), month, int(m.group(1)))
            if iso:
                found.append((m.start(), iso))
    # Aynı tarih birden çok kalıba düşebilir; konum sırası korunur, tekrarlar elenir.
    ordered: list[str] = []
    for _, iso in sorted(found):
        if iso not in ordered:
            ordered.append(iso)
    return ordered


def extract_obligations(text: str, *, source: str = "") -> list[dict]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Yükümlülük çıkarımı için metin gerekli.")
    rows = []
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    for sentence in sentences:
        dates = extract_dates(sentence)
        lower = sentence.casefold()
        obligation = bool(re.search(r"\b(?:gerekir|zorunlu|zorundasın|etmelisin|yapılmalı|yapmalısın|must|shall|required)\b", lower))
        if dates:
            rows.append({"kind": "deadline", "text": sentence, "due": dates[0], "source": source})
        if obligation or dates:
            rows.append({"kind": "obligation", "text": sentence, "due": dates[0] if dates else None, "source": source})
    return rows


def apply_patch(
    path: str | Path,
    replacements: dict[str, str],
    *,
    consent: bool,
    allowed_root: str | Path | None = None,
) -> dict:
    """Metin yamasını yalnız açık izinle ve izinli klasörde uygular.

    `consent` tam olarak True değilse yazma yok. Hedef, `allowed_root`
    (varsayılan: kullanıcı ev dizini) altında olmak zorunda. Başarıda
    öncesi/sonrası özet ve yedek yolu döner.
    """
    if consent is not True:
        raise FileWorkerExtensionError("Metin yaması için açık yazma izni gerekli.")
    target = Path(path)
    kok = Path(allowed_root) if allowed_root is not None else Path.home()
    try:
        hedef = target.resolve(strict=True)
        izinli = kok.resolve(strict=True)
    except OSError as exc:
        raise FileWorkerExtensionError("Yazma hedefi çözümlenemedi.") from exc
    if hedef != izinli and izinli not in hedef.parents:
        raise FileWorkerExtensionError("Yazma izni verilen klasörün dışında.")
    makbuz: dict = {}
    updated = patch_text(hedef, replacements, _receipt=makbuz)
    return {
        "path": str(hedef),
        "backup": makbuz.get("backup"),
        "digest_before": makbuz.get("digest_before"),
        "digest_after": makbuz.get("digest_after"),
        "chars": len(updated),
    }


def create_pptx_with_consent(
    destination: str | Path,
    slides: list[dict],
    *,
    consent: bool,
    allowed_root: str | Path | None = None,
    writer=None,
) -> dict:
    """PPTX üretimini açık izinle ve izinli klasörde yapar.

    `consent` tam olarak True değilse dosya oluşturulmaz; hedef
    `allowed_root` (varsayılan: kullanıcı ev dizini) altında olmalı.
    """
    if consent is not True:
        raise FileWorkerExtensionError("PPTX üretimi için açık yazma izni gerekli.")
    hedef = Path(destination)
    kok = Path(allowed_root) if allowed_root is not None else Path.home()
    try:
        izinli = kok.resolve(strict=True)
        cozulen = hedef.parent.resolve(strict=True) / hedef.name
    except OSError as exc:
        raise FileWorkerExtensionError("PPTX hedefi çözümlenemedi.") from exc
    if izinli not in cozulen.parents:
        raise FileWorkerExtensionError("Yazma izni verilen klasörün dışında.")
    sonuc = create_pptx(str(cozulen), slides, writer=writer)
    try:
        ozet = hashlib.sha256(cozulen.read_bytes()).hexdigest()
    except OSError as exc:
        raise FileWorkerExtensionError("Oluşan dosya okunamadı.") from exc
    return {**sonuc, "path": str(cozulen), "digest": ozet}


def create_pptx(destination: str, slides: list[dict], *, writer=None) -> dict:
    if not isinstance(destination, str) or not destination.strip() or not isinstance(slides, list) or not slides:
        raise ValueError("PPTX hedefi ve en az bir slayt gerekli.")
    payload = {"destination": destination, "slides": [{"title": str(row.get("title", "")), "body": str(row.get("body", ""))} for row in slides if isinstance(row, dict)]}
    if len(payload["slides"]) != len(slides):
        raise ValueError("Slayt sözleşmesi geçersiz.")
    if writer is not None and not callable(writer):
        raise ValueError("PPTX yazıcısı callable olmalı.")
    try:
        target = Path(destination)
        with file_resource_guard.claim_paths(target):
            # Creating an artifact is not authority to clobber an earlier one.
            if target.exists() or target.is_symlink():
                raise FileExistsError('PPTX output already exists; no overwrite.')
            if writer is not None:
                # Injected writer preserves its existing contract; production
                # PPTX output uses the complete-temp + no-replace path below.
                writer(payload)
            else:
                try:
                    from pptx import Presentation
                except ImportError as exc:
                    # A core-only install may lack the optional PowerPoint writer; say
                    # so in the user's language instead of leaking an ImportError.
                    raise FileWorkerExtensionError(
                        "PowerPoint yazıcısı kurulu değil; sunum dosyası oluşturulamadı.") from exc
                presentation = Presentation()
                for slide in payload["slides"]:
                    page = presentation.slides.add_slide(presentation.slide_layouts[1])
                    page.shapes.title.text = slide["title"]
                    page.placeholders[1].text = slide["body"]
                # PPTX libraries write multiple ZIP entries. Never expose a
                # partially written final artifact or replace an existing one.
                with tempfile.NamedTemporaryFile(
                        dir=target.parent, prefix='.jarvis-pptx-', suffix='.pptx',
                        delete=False) as opened:
                    temporary = Path(opened.name)
                try:
                    presentation.save(str(temporary))
                    # ZIP writer has closed the archive, but durable publish
                    # still requires flushing those bytes before its name
                    # becomes visible. Never link a half-written document.
                    with temporary.open('r+b') as completed:
                        completed.flush()
                        os.fsync(completed.fileno())
                    os.link(temporary, target)  # atomic create-only, same volume
                finally:
                    temporary.unlink(missing_ok=True)
    except resource_leases.LeaseConflict as exc:
        raise FileWorkerExtensionError("PPTX dosyası başka görev tarafından kullanılıyor.") from exc
    return {"destination": destination, "slides": len(payload["slides"]), "state": "written"}


def search_files(root: str | Path, query: str, *, max_files: int = MAX_SEARCH_FILES) -> list[dict]:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Dosya arama metni gerekli.")
    if type(max_files) is not int or not 1 <= max_files <= MAX_SEARCH_FILES:
        raise ValueError("Dosya arama sınırı geçersiz.")
    base = Path(root)
    if not base.is_dir():
        raise FileWorkerExtensionError("Arama klasörü bulunamadı.")
    results = []
    for path in sorted(base.rglob("*"), key=lambda item: str(item).casefold()):
        if len(results) >= max_files:
            break
        if not path.is_file():
            continue
        try:
            _regular(path, max_bytes=MAX_SEARCH_BYTES)
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError, FileWorkerExtensionError):
            continue
        if _minified(path, text) or query.casefold() not in text.casefold():
            continue
        index = text.casefold().find(query.casefold())
        results.append({"path": str(path), "name": path.name, "snippet": text[max(0, index - 120):index + len(query) + 240]})
    return results[:MAX_RESULTS]


def _yedek_yaz(target: Path, icerik: bytes) -> str:
    """Yama öncesi içeriği yanına yazar; dönüş yedek yoludur."""
    yedek = target.with_name(target.name + time.strftime(".bak-%Y%m%d%H%M%S"))
    yedek.write_bytes(icerik)
    return str(yedek)


def patch_text(
    path: str | Path,
    replacements: dict[str, str],
    *,
    _receipt: dict | None = None,
) -> str:
    target = Path(path)
    if not isinstance(replacements, dict) or not replacements or any(not isinstance(k, str) or not isinstance(v, str) for k, v in replacements.items()):
        raise ValueError("Metin yaması geçersiz.")
    try:
        with file_resource_guard.claim_paths(target):
            _regular(target, max_bytes=MAX_PATCH_BYTES)
            text = target.read_text(encoding="utf-8")
            if _minified(target, text):
                raise FileWorkerExtensionError("Minified/büyük tek satırlı dosya otomatik yamalanamaz.")
            updated = text
            for old, new in replacements.items():
                if old not in updated:
                    raise FileWorkerExtensionError("Yama hedef metni bulunamadı.")
                updated = updated.replace(old, new, 1)
            # The complete new text is atomically published under the same
            # physical identity claim; a crash cannot truncate the old file.
            release_guard.atomic(target, updated.encode("utf-8"))
            if _receipt is not None:
                # Özet ve yedek, aynı kaynak kilidinin içinde alınır: araya giren
                # yazma olmadığı için "önce/sonra" kanıtı gerçektir.
                _receipt["digest_before"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
                _receipt["digest_after"] = hashlib.sha256(updated.encode("utf-8")).hexdigest()
                _receipt["backup"] = _yedek_yaz(target, text.encode("utf-8"))
            return updated
    except resource_leases.LeaseConflict as exc:
        raise FileWorkerExtensionError("Metin dosyası başka görev tarafından kullanılıyor.") from exc