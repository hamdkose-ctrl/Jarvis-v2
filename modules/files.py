"""Dosya komutları: klasör açma, son dosyayı açma, klasör düzenleme (geri alınabilir)."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from config import DATA_DIR


def _undo_file(owner: str = "") -> Path:
    """Toplu düzenleme geri alması yalnız onaylayan kullanıcıya aittir."""
    from modules import file_resource_guard
    safe, _old = file_resource_guard.receipt_owner_suffixes(owner)
    return DATA_DIR / f"organize_undo_{safe}.json"


def _legacy_undo_file(owner: str = "") -> Path:
    from modules import file_resource_guard
    _safe, old = file_resource_guard.receipt_owner_suffixes(owner)
    return DATA_DIR / f"organize_undo_{old}.json"

# (söylenen kök) -> (klasör adaylar, klasör sözcüğü gerekir mi)
_FOLDERS = (
    (r"indirilen\w*|download\w*|indirdi\w*", ("Downloads", "İndirilenler"), False, "İndirilenler"),
    (r"masaüst\w*|desktop\w*", ("Desktop", "OneDrive/Desktop", "OneDrive/Masaüstü", "Masaüstü"), False, "Masaüstü"),
    (r"belge\w*|document\w*", ("Documents", "OneDrive/Documents", "OneDrive/Belgeler", "Belgeler"), False, "Belgeler"),
    (r"resim\w*|fotoğraf\w*|picture\w*", ("Pictures", "OneDrive/Pictures", "Resimler"), False, "Resimler"),
    (r"video\w*", ("Videos", "Videolar"), True, "Videolar"),
    (r"müzik\w*|music\w*", ("Music", "Müzik"), True, "Müzik"),
)
_IGNORE = {"desktop.ini", "thumbs.db"}
_IGNORE_EXT = {".tmp", ".crdownload", ".part", ".partial", ".lnk", ".url"}

CATEGORIES = {
    "Belgeler": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".ppt", ".pptx", ".txt", ".odt", ".rtf", ".md"},
    "Resimler": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".heic", ".tif", ".tiff"},
    "Videolar": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm"},
    "Müzikler": {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg"},
    "Arşivler": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Programlar": {".exe", ".msi", ".apk", ".iso"},
}


def folder_path(candidates: tuple[str, ...]) -> Path | None:
    home = Path.home()
    for c in candidates:
        p = home / c
        if p.is_dir():
            return p
    return None


def match_folder(text: str) -> tuple[Path, str, bool] | None:
    """Metinde geçen klasör adını bulur: (yol, görünen ad, 'klasör' sözcüğü gerekli mi)."""
    for pattern, cands, need_word, label in _FOLDERS:
        if re.search(rf"\b(?:{pattern})", text):
            p = folder_path(cands)
            if p:
                return p, label, need_word
    return None


def _real_files(folder: Path) -> list[Path]:
    out = []
    try:
        for p in folder.iterdir():
            if p.is_file() and p.name.lower() not in _IGNORE and p.suffix.lower() not in _IGNORE_EXT \
                    and not p.name.startswith("."):
                out.append(p)
    except OSError:
        pass
    return out


def latest_file(folder: Path) -> Path | None:
    files = _real_files(folder)
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def open_path(path: Path) -> None:
    os.startfile(str(path))      # type: ignore[attr-defined]


def handle(cmd_lower: str) -> str | None:
    """'indirilenlerdeki son dosyayı aç', 'masaüstünü aç' gibi komutlar. İlgisizse None."""
    t = cmd_lower.strip()
    hit = match_folder(t)
    if not hit:
        return None
    folder, label, need_word = hit
    if re.search(r"\bson\b", t) and re.search(r"dosya|indirdi|indirilen\w*\s+(?:aç|göster)", t):
        newest = latest_file(folder)
        if not newest:
            return f"{label} klasöründe dosya bulamadım."
        if re.search(r"\b(nedir|ne|hangisi|adı|göster)\b", t) and not re.search(r"\baç\b", t):
            return f"{label} klasöründeki son dosya: {newest.name}."
        try:
            open_path(newest)
        except OSError as exc:
            return f"Dosyayı açamadım: {exc}"
        return f"{label} klasöründeki son dosyayı açıyorum: {newest.name}."
    if re.search(r"\b(aç|göster)\b", t) and len(t.split()) <= 4 and (not need_word or "klasör" in t):
        try:
            open_path(folder)
        except OSError as exc:
            return f"Klasörü açamadım: {exc}"
        return f"{label} klasörünü açıyorum."
    return None


# --- düzenleme --------------------------------------------------------------------------------
# Kanonical düzenleme yetkisinin kapalı klasör kimliği: yalnız bu üç gerçek kullanıcı klasörü.
# Understanding bir anahtar seçer, yol burada sabit listeden çözülür — ham metinden klasör tahmini yok.
ORGANIZE_FOLDERS = {
    "desktop": (("Desktop", "OneDrive/Desktop", "OneDrive/Masaüstü", "Masaüstü"), "Masaüstü"),
    "downloads": (("Downloads", "İndirilenler"), "İndirilenler"),
    "documents": (("Documents", "OneDrive/Documents", "OneDrive/Belgeler", "Belgeler"), "Belgeler"),
}


def organize_folder(key: object) -> tuple[Path, str] | None:
    """Core'un doğruladığı anahtarı gerçek klasör kimliğine çevirir; çözülemezse None."""
    row = ORGANIZE_FOLDERS.get(key) if isinstance(key, str) else None
    if row is None:
        return None
    candidates, label = row
    path = folder_path(candidates)
    return (path, label) if path is not None else None


def same_plan(before: list[tuple[Path, Path]], after: list[tuple[Path, Path]]) -> bool:
    """Önizlenen plan ile güncel plan aynı çiftleri mi taşıyor (sıra dahil)."""
    return [(str(a), str(b)) for a, b in before] == [(str(a), str(b)) for a, b in after]


def _identity(path: Path) -> str:
    """Dosyanın o andaki kimlik imzası: boy, zaman damgaları ve disk üzerindeki dosya indeksi.

    Windows'ta `st_ctime` yaratılma zamanıdır ve bir dosyanın yerine aynı boy/zamanlı başka bir dosya
    konduğunda değişmeyebilir; `st_ino` (NTFS dosya indeksi) o ayrımı taşır."""
    try:
        info = path.stat()
    except OSError:
        return "yok"
    return f"{info.st_size}:{info.st_mtime_ns}:{info.st_ctime_ns}:{info.st_ino}"


def plan_stamp(plan: list[tuple[Path, Path]]) -> str:
    """Yol çiftlerinin ötesinde, her kaynağın o andaki dosya kimliği mührü (salt metin).

    Aynı adda ve aynı boyda yabancı bir dosya kaynağın yerine konsa ya da içerik değişse mühür
    değişir; böylece ESKİ onay başka bir dosyayı taşımaz. Salt metin olduğu için bekleyen iş
    ile birlikte JSON/oturum turuna dayanır."""
    return hashlib.sha256(
        "\n".join(f"{src}|{dst}|{_identity(src)}" for src, dst in plan).encode("utf-8")
    ).hexdigest()


def plan_organize(folder: Path) -> list[tuple[Path, Path]]:
    """(kaynak, hedef) çiftleri. Kısayollar, klasörler ve geçici dosyalar yerinde kalır."""
    plan = []
    for f in _real_files(folder):
        ext = f.suffix.lower()
        cat = next((c for c, exts in CATEGORIES.items() if ext in exts), "Diğer")
        plan.append((f, folder / cat / f.name))
    return plan


def summary(plan: list[tuple[Path, Path]]) -> str:
    counts: dict[str, int] = {}
    for _src, dst in plan:
        counts[dst.parent.name] = counts.get(dst.parent.name, 0) + 1
    return ", ".join(f"{n} {k}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1]))


def _free_name(dst: Path) -> Path:
    if not dst.exists():
        return dst
    for i in range(1, 1000):
        cand = dst.with_name(f"{dst.stem} ({i}){dst.suffix}")
        if not cand.exists():
            return cand
    return dst


def _move_create_only(source: Path, destination: Path) -> None:
    """Same-volume file move without ever replacing another path.

    An existing destination (including one created by a non-cooperating
    process after our preflight) makes os.link fail atomically. Cross-volume
    moves and filesystems without hard links fail closed rather than falling
    back to shutil.copy2, which could overwrite a racing destination.
    The caller writes the intent receipt before this operation: a crash
    between link and unlink leaves an unknown effect, never an auto-retry.
    """
    os.link(source, destination)
    if not os.path.samefile(source, destination):
        raise OSError('Source identity changed during create-only move.')
    source.unlink()


def _content_digest(path: Path) -> str:
    """Content-bound undo identity, stable across a same-bytes restored file."""
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _validated_undo_entries(value):
    if not isinstance(value, list) or any(
        not isinstance(row, list) or len(row) not in (2, 3, 4)
        or any(not isinstance(item, str) or not item for item in row)
        or (len(row) >= 3 and
            (len(row[2]) != 64 or any(ch not in '0123456789abcdef' for ch in row[2])))
        or (len(row) == 4 and row[3] not in {'intent', 'moved'})
        for row in value
    ):
        raise ValueError('Geri alma kaydı bozuk; dosyalara dokunulmadı.')
    return value


def apply_organize(plan: list[tuple[Path, Path]], owner: str = "",
                   *, expected_stamp: str | None = None) -> int:
    """Apply a confirmed plan through the same physical claims as file_ops.

    The per-owner undo receipt is held for the entire batch. Every source and
    actual destination is claimed separately (no 16-path batch limit).
    A stale preview or a changed file fails before a move; never overwrite
    somebody else's pending undo receipt or an existing destination.
    """
    from contextlib import nullcontext
    import release_guard
    from modules import file_resource_guard, resource_leases

    if (not isinstance(plan, list)
            or any(not isinstance(row, (list, tuple)) or len(row) != 2
                   for row in plan)):
        raise ValueError('Düzenleme planı geçersiz; dosyalar taşınmadı.')
    if expected_stamp is not None and (
            not isinstance(expected_stamp, str) or len(expected_stamp) != 64):
        raise ValueError('Düzenleme onayı geçersiz.')
    receipt = _undo_file(owner)
    legacy = _legacy_undo_file(owner)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    try:
        with file_resource_guard.claim_paths(receipt, legacy):
            if receipt != legacy and (legacy.exists() or legacy.is_symlink()):
                raise ValueError(
                    'Önceki düzenleme makbuzunun sahibi belirsiz; işlem yapılmadı.'
                )
            if receipt.exists():
                try:
                    previous = _validated_undo_entries(json.loads(
                        receipt.read_text(encoding='utf-8')))
                except (OSError, ValueError) as exc:
                    raise ValueError('Önceki geri alma kaydı doğrulanamadı; yeni düzenleme yapılmadı.') from exc
                if previous:
                    raise ValueError('Önceki düzenlemenin geri alma kaydı duruyor; önce onu tamamla.')
            if expected_stamp is not None and plan_stamp(plan) != expected_stamp:
                raise ValueError('Düzenleme önizlemesindeki dosyalar değişti; yeniden onay gerekli.')
            # Snapshot BEFORE effects, then revalidate EACH source under its
            # physical claim to close the preview->move TOCTOU window.
            original = [(Path(src), Path(dst), _identity(Path(src))) for src, dst in plan]
            moved = []
            for source, destination, stamp in original:
                if stamp == 'yok':
                    raise ValueError('Düzenlenecek dosya kayboldu; plan yeniden hazırlanmalı.')
                if destination.parent.is_symlink():
                    raise ValueError('Düzenleme hedefi sembolik bağ; dosya taşınmadı.')
                destination.parent.mkdir(exist_ok=True)
                with file_resource_guard.claim_paths(source, destination):
                    if (source.is_symlink() or not source.is_file()
                            or _identity(source) != stamp):
                        raise ValueError('Dosya değişti; eski düzenleme onayı uygulanmadı.')
                    final = _free_name(destination)
                    claim_suffix = (
                        nullcontext() if final == destination
                        else file_resource_guard.claim_paths(final)
                    )
                    with claim_suffix:
                        if final.exists() or final.is_symlink():
                            raise resource_leases.LeaseConflict(
                                'Organize destination was taken before move.'
                            )
                        # Write-ahead: a process death AFTER the physical move
                        # but BEFORE its completion marker must leave a durable
                        # intent that prohibits blind replay or a second batch.
                        pending = [str(final), str(source),
                                   _content_digest(source), 'intent']
                        release_guard.atomic(
                            receipt, json.dumps(moved + [pending],
                                                ensure_ascii=False).encode('utf-8'),
                        )
                        _move_create_only(source, final)
                        pending[3] = 'moved'
                        moved.append(pending)
                        # Mark only a proven move. If this write fails, the
                        # previous 'intent' remains as a manual-review fence.
                        release_guard.atomic(
                            receipt, json.dumps(moved, ensure_ascii=False).encode('utf-8'),
                        )
            return len(moved)
    except resource_leases.LeaseConflict as exc:
        raise ValueError('Aynı dosyada veya geri alma kaydında başka bir işlem çalışıyor.') from exc


def undo_organize(owner: str = "") -> int | None:
    """Undo only content-verified moves under the same cross-process file claims.

    Two-field legacy receipts remain readable but never authorize a blind move:
    an unverified old record may refer to a different file now at that path.
    """
    import release_guard
    from modules import file_resource_guard, resource_leases

    receipt = _undo_file(owner)
    legacy = _legacy_undo_file(owner)
    if not receipt.exists() and not receipt.is_symlink() and not legacy.exists() and not legacy.is_symlink():
        return None
    try:
        with file_resource_guard.claim_paths(receipt, legacy):
            if receipt != legacy and (legacy.exists() or legacy.is_symlink()):
                # Owner is ambiguous after historical truncation.
                return None
            try:
                moved = _validated_undo_entries(json.loads(
                    receipt.read_text(encoding='utf-8')))
            except (OSError, ValueError):
                return None
            restored, blocked = 0, []
            for entry in reversed(moved):
                new, old = entry[:2]
                try:
                    with file_resource_guard.claim_paths(Path(new), Path(old)):
                        source, destination = Path(new), Path(old)
                        if (not source.is_file() or source.is_symlink()
                                or destination.exists() or destination.is_symlink()
                                or len(entry) < 3
                                or (len(entry) == 4 and entry[3] != 'moved')
                                or _content_digest(source) != entry[2]):
                            blocked.append(entry)
                            continue
                        _move_create_only(source, destination)
                        restored += 1
                except (OSError, resource_leases.LeaseConflict):
                    blocked.append(entry)
            if blocked:
                release_guard.atomic(
                    receipt,
                    json.dumps(list(reversed(blocked)), ensure_ascii=False).encode('utf-8'),
                )
            else:
                receipt.unlink(missing_ok=True)
            for new, _old, *_digest in moved:
                try:
                    Path(new).parent.rmdir()
                except OSError:
                    pass
            return restored
    except (OSError, resource_leases.LeaseConflict):
        return 0
