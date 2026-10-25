"""Dosya komutları: klasör açma, son dosyayı açma, klasör düzenleme (geri alınabilir)."""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from config import DATA_DIR


def _undo_file(owner: str = "") -> Path:
    """Toplu düzenleme geri alması yalnız onaylayan kullanıcıya aittir."""
    safe = re.sub(r"[^\\w-]", "_", owner)[:60] or "ortak"
    return DATA_DIR / f"organize_undo_{safe}.json"

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
def wants_organize(cmd_lower: str) -> tuple[Path, str] | None:
    if re.search(r"\b(düzenle|topla|temizle|derle|sırala)\b", cmd_lower) and not re.search(r"not|takvim", cmd_lower):
        hit = match_folder(cmd_lower)
        if hit and hit[1] in ("Masaüstü", "İndirilenler", "Belgeler"):
            return hit[0], hit[1]
    return None


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


def apply_organize(plan: list[tuple[Path, Path]], owner: str = "") -> int:
    """Dosyaları taşır ve geri alma kaydını yazar. Taşınan dosya sayısını döndürür."""
    moved = []
    for src, dst in plan:
        try:
            dst.parent.mkdir(exist_ok=True)
            final = _free_name(dst)
            shutil.move(str(src), str(final))
            moved.append([str(final), str(src)])
        except OSError:
            continue
    undo_file = _undo_file(owner)
    undo_file.parent.mkdir(parents=True, exist_ok=True)
    undo_file.write_text(json.dumps(moved, ensure_ascii=False), encoding="utf-8")
    return len(moved)


def undo_organize(owner: str = "") -> int | None:
    """Son düzenlemeyi geri alır. Kayıt yoksa None."""
    undo_file = _undo_file(owner)
    try:
        moved = json.loads(undo_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    back = 0
    for new, old in reversed(moved):
        try:
            if os.path.exists(new) and not os.path.exists(old):
                shutil.move(new, old)
                back += 1
        except OSError:
            continue
    for new, _old in moved:       # boş kalan kategori klasörlerini temizle
        try:
            Path(new).parent.rmdir()
        except OSError:
            pass
    try:
        undo_file.unlink()
    except OSError:
        pass
    return back
