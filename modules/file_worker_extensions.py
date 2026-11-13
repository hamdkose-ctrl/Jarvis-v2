"""Phase 4B FileWorker hardening: bounded read/search and explicit document outputs."""
from __future__ import annotations

import os
import re
import stat
import tempfile
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


def extract_obligations(text: str, *, source: str = "") -> list[dict]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Yükümlülük çıkarımı için metin gerekli.")
    rows = []
    date_pattern = r"(?:19|20)\d{2}-\d{2}-\d{2}"
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    for sentence in sentences:
        dates = re.findall(date_pattern, sentence)
        lower = sentence.casefold()
        obligation = bool(re.search(r"\b(?:gerekir|zorunlu|zorundasın|etmelisin|yapılmalı|yapmalısın|must|shall|required)\b", lower))
        if dates:
            rows.append({"kind": "deadline", "text": sentence, "due": dates[0], "source": source})
        if obligation or dates:
            rows.append({"kind": "obligation", "text": sentence, "due": dates[0] if dates else None, "source": source})
    return rows


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
                from pptx import Presentation
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


def patch_text(path: str | Path, replacements: dict[str, str]) -> str:
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
            return updated
    except resource_leases.LeaseConflict as exc:
        raise FileWorkerExtensionError("Metin dosyası başka görev tarafından kullanılıyor.") from exc
