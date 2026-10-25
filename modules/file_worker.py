"""FileWorker v1 — salt-okunur dosya/klasör çıkarım katmanı.

`docs/architecture/JARVIS_FILEWORKER_READONLY_BENCHMARK_V1.md`'de tanımlı evidence
sözleşmesine göre üretir: her bulgu dosya kimliği + içerik digest'i + okuyucu adı +
(mümkünse) sayfa/satır/sayfa adı/hücre konumu taşır. Yeni parser/OCR/model eklemez;
yalnız mevcut `modules/docs.py`, `modules/document_conversion.py` ve
`modules/workbench.py.load_table()` salt-okunur yollarını orkestre eder.

Kurallar:
- Hiçbir fonksiyon dosyaya yazmaz, silmez, taşımaz veya dışa aktarmaz.
- Yalnız bilinen klasörler (Masaüstü, İndirilenler, Belgeler, Resimler, Jarvis
  Dosyaları) ve alt klasörleri taranır; `file_ops._roots()` ile aynı kapsam.
- Her sonuç `reason_code` taşır; belirsizlik sessiz başarı üretmez.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from . import docs, document_conversion, file_ops, files

MAX_SCAN_FILES = 500          # tek klasör taramasında en fazla dosya (asılı kalmayı önler)
MAX_DIGEST_BYTES = 200 * 1024 * 1024   # bundan büyük dosyada tam digest hesaplanmaz
SNIPPET_LEN = 400              # evidence metninde tutulan en fazla karakter
MAX_LOCATIONS = 200            # tek dosyadan çıkarılan en fazla evidence konumu

_STRUCTURED_EXT = {".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md"}


class FileWorkerError(ValueError):
    def __init__(self, message: str, reason_code: str):
        super().__init__(message)
        self.reason_code = reason_code


@dataclass
class Location:
    page: int | None = None
    line: int | None = None
    sheet: str | None = None
    cell_or_range: str | None = None
    text: str = ""


@dataclass
class FileObservation:
    path: str
    file_identity: str
    content_digest: str | None
    extractor_name: str
    extractor_version: str
    locations: list[Location] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    reason_code: str = "OK"


def allowed_roots() -> list[Path]:
    """Taranmasına izin verilen klasör kökleri; `file_ops`'un kullanıcı klasör kapsamıyla aynı."""
    return file_ops._roots()


def _is_within_allowed(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return any(resolved == root or root in resolved.parents for root in allowed_roots())


def content_digest(path: Path) -> str | None:
    """Dosya içeriğinin sha256 digest'i. `MAX_DIGEST_BYTES`'tan büyük dosyada None (okuma denemez)."""
    try:
        if path.stat().st_size > MAX_DIGEST_BYTES:
            return None
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def scan_folder(folder: str, *, recursive: bool = True, max_files: int = MAX_SCAN_FILES) -> list[dict]:
    """Bilinen bir klasör kökü içindeki dosyaları salt-okunur listeler.

    Her girdi: path, name, ext, size, mtime. Hiçbir dosya içeriği burada okunmaz.
    İzin verilen kök dışındaki bir klasör `FileWorkerError('PERMISSION_MISMATCH')` üretir.
    """
    p = Path(folder)
    if not p.is_dir():
        raise FileWorkerError(f"Klasör bulunamadı: {folder}", "FILE_NOT_FOUND")
    if not _is_within_allowed(p):
        raise FileWorkerError(
            "Bu klasör Jarvis'in bilinen klasörleri (Masaüstü, İndirilenler, Belgeler, "
            "Resimler, Jarvis Dosyaları) dışında; tarayamam.", "PERMISSION_MISMATCH")

    pattern = "**/*" if recursive else "*"
    out = []
    for entry in p.glob(pattern):
        if not entry.is_file() or entry.name in files._IGNORE or entry.suffix.lower() in files._IGNORE_EXT:
            continue
        try:
            st = entry.stat()
        except OSError:
            continue
        out.append({
            "path": str(entry), "name": entry.name, "ext": entry.suffix.lower(),
            "size": st.st_size, "mtime": st.st_mtime,
        })
        if len(out) >= max_files:
            break
    return out


def find_duplicates(entries: list[dict]) -> list[list[dict]]:
    """Aynı içerik digest'ine sahip dosya gruplarını döndürür (tek elemanlı grup yok sayılır).

    Yalnız `MAX_DIGEST_BYTES` altındaki dosyalar digest'lenir; büyük dosyalar bu
    karşılaştırmaya girmez (uydurma eşleşme üretilmez).
    """
    by_digest: dict[str, list[dict]] = {}
    for e in entries:
        digest = content_digest(Path(e["path"]))
        if digest is None:
            continue
        by_digest.setdefault(digest, []).append(e)
    return [group for group in by_digest.values() if len(group) > 1]


def find_similar_names(entries: list[dict]) -> list[list[dict]]:
    """Normalize edilince aynı tabana düşen dosya adlarını gruplar (örn. 'rapor (1).pdf' ~ 'rapor.pdf')."""
    import re as _re
    by_base: dict[str, list[dict]] = {}
    for e in entries:
        stem = Path(e["name"]).stem
        base = _re.sub(r"\s*\(\d+\)\s*$", "", stem).strip().casefold()
        by_base.setdefault(base, []).append(e)
    return [group for group in by_base.values() if len(group) > 1]


def _extractor_version(name: str) -> str:
    try:
        import importlib.metadata as m
        return m.version(name)
    except Exception:
        return "bilinmiyor"


def _locations_from_structured(content, ext: str) -> tuple[list[Location], str, str]:
    """document_conversion.read_source() çıktısından evidence konumları üretir."""
    locs: list[Location] = []
    if ext == ".pdf":
        for i, page_text in enumerate(content.pages, 1):
            if page_text.strip():
                locs.append(Location(page=i, text=page_text[:SNIPPET_LEN]))
            if len(locs) >= MAX_LOCATIONS:
                break
        return locs, "pypdf (modules.pdf_runtime)", _extractor_version("pypdf")
    if ext == ".csv" or (ext == ".xlsx" and content.sheets):
        for sheet_name, rows in content.sheets:
            for r_idx, row in enumerate(rows, 1):
                if any(v not in (None, "") for v in row):
                    cell_range = f"A{r_idx}:{chr(64 + min(len(row), 26))}{r_idx}"
                    text = " | ".join(str(v) for v in row if v not in (None, ""))
                    locs.append(Location(sheet=sheet_name if ext == ".xlsx" else None,
                                          line=r_idx if ext == ".csv" else None,
                                          cell_or_range=cell_range if ext == ".xlsx" else None,
                                          text=text[:SNIPPET_LEN]))
                if len(locs) >= MAX_LOCATIONS:
                    break
            if len(locs) >= MAX_LOCATIONS:
                break
        name = "openpyxl" if ext == ".xlsx" else "csv (yerel okuyucu)"
        return locs, name, _extractor_version("openpyxl") if ext == ".xlsx" else "stdlib"
    if ext in (".docx", ".txt", ".md"):
        for i, block in enumerate(content.blocks, 1):
            text = block.text if block.kind != "table" else " | ".join(
                " / ".join(str(c) for c in row) for row in block.rows)
            if text and text.strip():
                locs.append(Location(line=i, text=text[:SNIPPET_LEN]))
            if len(locs) >= MAX_LOCATIONS:
                break
        name = "python-docx" if ext == ".docx" else "markdown/metin bloklayıcı"
        return locs, name, _extractor_version("python-docx") if ext == ".docx" else "stdlib"
    return locs, "document_conversion", "stdlib"


def extract(path: str) -> FileObservation:
    """Bir dosyadan evidence-bağlı, salt-okunur çıkarım. Hiçbir şey yazmaz/değiştirmez.

    Desteklenen biçimlerde (`modules.docs.SUPPORTED`) başarısızsa `reason_code` ile
    dönen bir `FileObservation` üretir; hiçbir durumda istisna yutarak sessiz
    "başarı" üretmez. Desteklenmeyen biçim veya izin dışı klasör için
    `FileWorkerError` fırlatılır.
    """
    p = Path(path)
    if not p.is_file():
        raise FileWorkerError(f"Dosya bulunamadı: {path}", "FILE_NOT_FOUND")
    if not _is_within_allowed(p):
        raise FileWorkerError(
            "Bu dosya Jarvis'in bilinen klasörleri dışında; okuyamam.", "PERMISSION_MISMATCH")

    ext = p.suffix.lower()
    if ext not in docs.SUPPORTED:
        raise FileWorkerError(
            "PDF, Word, Excel, PowerPoint, CSV, HTML, TXT, MD, RTF, ODT veya JSON dosyası seç.",
            "UNSUPPORTED_FORMAT")

    identity = str(p.resolve())
    digest = content_digest(p)
    obs = FileObservation(path=str(p), file_identity=identity, content_digest=digest,
                           extractor_name="", extractor_version="")

    try:
        if ext in _STRUCTURED_EXT:
            content = document_conversion.read_source(str(p))
            locs, name, version = _locations_from_structured(content, ext)
            obs.extractor_name, obs.extractor_version = name, version
            obs.locations = locs
            obs.warnings = list(content.warnings)
        else:
            text = docs.read_document(str(p), keep_pages=True)
            obs.extractor_name, obs.extractor_version = "modules.docs.read_document", "n/a"
            if ext == ".pptx":
                obs.extractor_name = "pptx slayt metni (zipfile/regex)"
            pages = text.split("\f") if "\f" in text else [text]
            for i, page_text in enumerate(pages, 1):
                if page_text.strip():
                    obs.locations.append(Location(page=i if len(pages) > 1 else None,
                                                    text=page_text.strip()[:SNIPPET_LEN]))
                if len(obs.locations) >= MAX_LOCATIONS:
                    break
    except FileNotFoundError:
        obs.reason_code = "FILE_NOT_FOUND"
        return obs
    except docs.PdfReadTimeout:
        obs.reason_code = "READ_TIMEOUT"
        return obs
    except ValueError as exc:
        text = str(exc).casefold()
        if "parola" in text or "şifreli" in text:
            obs.reason_code = "ENCRYPTED_OR_PROTECTED"
        elif "bozuk" in text:
            obs.reason_code = "CORRUPT_DOCUMENT"
        elif "seç" in text:
            obs.reason_code = "UNSUPPORTED_FORMAT"
        else:
            obs.reason_code = "NO_TEXT_EXTRACTED"
        obs.warnings.append(str(exc))
        return obs

    if not obs.locations:
        obs.reason_code = "NO_TEXT_EXTRACTED"
    return obs
