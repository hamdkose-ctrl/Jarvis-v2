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
SNIPPET_LEN = 1200             # evidence metninde tutulan en fazla karakter
MAX_LOCATIONS = 200            # tek dosyadan çıkarılan en fazla evidence konumu
EVIDENCE_BUDGET = 24_000       # tek extract turunda toplanan evidence metni bütçesi (karakter)

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
    truncated: bool = False
    continuation: int | None = None


def _bounded_locations(units: list, offset: int, make_loc) -> tuple[list[Location], bool, int | None, int]:
    """Konum/karakter bütçesini uygulayan tek toplama döngüsü.

    `units` kaynağın tam birim listesi (sayfa/blok/satır), `make_loc(unit)` bir
    Location üretir ya da boş birim için None döner. Dönüş: (locs, truncated,
    continuation_offset, işlenmeyen_birim_sayısı). Kesinti sessiz değildir; çağıran
    açık uyarı yazar ve `continuation` ile sonraki parça istenebilir.
    """
    locs: list[Location] = []
    budget = EVIDENCE_BUDGET
    index = offset
    truncated = False
    while index < len(units):
        loc = make_loc(units[index])
        if loc is None:
            index += 1
            continue
        if len(locs) >= MAX_LOCATIONS or len(loc.text) > budget:
            truncated = True
            break
        budget -= len(loc.text)
        locs.append(loc)
        index += 1
    unprocessed = len(units) - index if truncated else 0
    return locs, truncated, (index if truncated else None), unprocessed


def allowed_roots() -> list[Path]:
    """Taranmasına izin verilen klasör kökleri; `file_ops`'un kullanıcı klasör kapsamıyla aynı."""
    return file_ops._roots()


def _is_within_allowed(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in allowed_roots():
        try:
            resolved_root = root.resolve()
        except OSError:
            continue
        if resolved == resolved_root or resolved_root in resolved.parents:
            return True
    return False


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
    import importlib.metadata as m
    try:
        return m.version(name)
    except m.PackageNotFoundError:
        return "bilinmiyor"


def _locations_from_structured(content, ext: str, offset: int):
    """document_conversion.read_source() çıktısından sınırlı evidence konumları üretir."""
    if ext == ".pdf":
        units = list(enumerate(content.pages, 1))

        def make_loc(unit):
            page, page_text = unit
            return Location(page=page, text=page_text[:SNIPPET_LEN]) if page_text.strip() else None

        locs, truncated, continuation, unprocessed = _bounded_locations(units, offset, make_loc)
        return locs, "pypdf (modules.pdf_runtime)", _extractor_version("pypdf"), truncated, continuation, unprocessed
    if ext == ".csv" or (ext == ".xlsx" and content.sheets):
        units = [(sheet_name, r_idx, row)
                 for sheet_name, rows in content.sheets
                 for r_idx, row in enumerate(rows, 1)]

        def make_loc(unit):
            sheet_name, r_idx, row = unit
            if not any(v not in (None, "") for v in row):
                return None
            cell_range = f"A{r_idx}:{chr(64 + min(len(row), 26))}{r_idx}"
            text = " | ".join(str(v) for v in row if v not in (None, ""))
            return Location(sheet=sheet_name if ext == ".xlsx" else None,
                            line=r_idx if ext == ".csv" else None,
                            cell_or_range=cell_range if ext == ".xlsx" else None,
                            text=text[:SNIPPET_LEN])

        locs, truncated, continuation, unprocessed = _bounded_locations(units, offset, make_loc)
        name = "openpyxl" if ext == ".xlsx" else "csv (yerel okuyucu)"
        return locs, name, (_extractor_version("openpyxl") if ext == ".xlsx" else "stdlib"), truncated, continuation, unprocessed
    if ext in (".docx", ".txt", ".md"):
        units = list(enumerate(content.blocks, 1))

        def make_loc(unit):
            i, block = unit
            text = block.text if block.kind != "table" else " | ".join(
                " / ".join(str(c) for c in row) for row in block.rows)
            return Location(line=i, text=text[:SNIPPET_LEN]) if text and text.strip() else None

        locs, truncated, continuation, unprocessed = _bounded_locations(units, offset, make_loc)
        name = "python-docx" if ext == ".docx" else "markdown/metin bloklayıcı"
        return locs, name, (_extractor_version("python-docx") if ext == ".docx" else "stdlib"), truncated, continuation, unprocessed
    return [], "document_conversion", "stdlib", False, None, 0


def extract(path: str, *, offset: int = 0) -> FileObservation:
    """Bir dosyadan evidence-bağlı, salt-okunur çıkarım. Hiçbir şey yazmaz/değiştirmez.

    Desteklenen biçimlerde (`modules.docs.SUPPORTED`) başarısızsa `reason_code` ile
    dönen bir `FileObservation` üretir; hiçbir durumda istisna yutarak sessiz
    "başarı" üretmez. Desteklenmeyen biçim veya izin dışı klasör için
    `FileWorkerError` fırlatılır.

    `offset` önceki turda işlenen kaynak birimi (sayfa/blok/satır) sayısıdır; uzun
    belge parça parça incelenir. Konum/bütçe sınırına takılan tur `truncated=True`,
    `continuation` (sonraki parçanın offset'i) ve açık bir uyarı taşır — içerik
    sessizce atılmaz.
    """
    if type(offset) is not int or offset < 0:
        raise FileWorkerError("Devam offset'i negatif olmayan tam sayı olmalı.", "INVALID_OFFSET")
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

    def _mark_truncation(truncated: bool, continuation: int | None, unprocessed: int) -> None:
        if not truncated:
            return
        obs.truncated = True
        obs.continuation = continuation
        limit = ("konum sınırına (200)" if len(obs.locations) >= MAX_LOCATIONS
                 else f"karakter bütçesine ({EVIDENCE_BUDGET})")
        obs.warnings.append(
            f"Kanıt kesildi: {limit} takıldı, {len(obs.locations)} konum alındı, "
            f"{unprocessed} birim işlenmedi; devam için extract(path, offset={continuation}).")

    try:
        if ext in _STRUCTURED_EXT:
            content = document_conversion.read_source(str(p))
            locs, name, version, truncated, continuation, unprocessed = _locations_from_structured(content, ext, offset)
            obs.extractor_name, obs.extractor_version = name, version
            obs.locations = locs
            obs.warnings = list(content.warnings)
            _mark_truncation(truncated, continuation, unprocessed)
        else:
            text = docs.read_document(str(p), keep_pages=True)
            obs.extractor_name, obs.extractor_version = "modules.docs.read_document", "n/a"
            if ext == ".pptx":
                obs.extractor_name = "pptx slayt metni (zipfile/regex)"
            pages = text.split("\f") if "\f" in text else [text]
            units = list(enumerate(pages, 1))

            def make_loc(unit):
                i, page_text = unit
                stripped = page_text.strip()
                return Location(page=i if len(pages) > 1 else None,
                                text=stripped[:SNIPPET_LEN]) if stripped else None

            locs, truncated, continuation, unprocessed = _bounded_locations(units, offset, make_loc)
            obs.locations = locs
            _mark_truncation(truncated, continuation, unprocessed)
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
