"""Klasör envanteri v1 — salt-okunur düzenleme ÖNERİSİ raporu.

`modules/file_worker.py` üzerine ince bir katman: tarama, yineleme/benzer-ad
tespiti zaten orada var; burada bunlara ek olarak boş/eski dosya adaylarını
işaretler ve hepsini tek bir rapora toplar. Hiçbir dosyayı taşımaz, yeniden
adlandırmaz, silmez veya arşivlemez — bu, planın 5. adımıdır (onaylı effect)
ve bu dosyanın kapsamı dışındadır.

Uygulama sırası (Dosya çalışma alanı tasarımı, madde 7): bu modül 2. adımı
karşılar — "Read-only klasör envanteri + duplicate/sınıflandırma önerileri".
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import file_worker as fw

OLD_FILE_DAYS = 180            # bu kadar gündür değişmemiş dosya "eski aday"
_TEMP_NAME_HINTS = ("~$", ".temp", ".bak", ".old")  # .tmp/.part/.crdownload zaten files._IGNORE_EXT'te elenir


@dataclass
class InventoryReport:
    folder: str
    total_files: int
    by_extension: dict[str, int] = field(default_factory=dict)
    duplicate_groups: list[list[dict]] = field(default_factory=list)
    similar_name_groups: list[list[dict]] = field(default_factory=list)
    empty_file_candidates: list[dict] = field(default_factory=list)
    old_file_candidates: list[dict] = field(default_factory=list)
    temp_name_candidates: list[dict] = field(default_factory=list)
    truncated: bool = False    # fw.MAX_SCAN_FILES sınırına çarpıldıysa True


def _is_temp_name(name: str) -> bool:
    lower = name.lower()
    return lower.startswith("~$") or any(lower.endswith(suf) for suf in _TEMP_NAME_HINTS if not suf.startswith("~"))


def build_report(folder: str, *, old_file_days: int = OLD_FILE_DAYS) -> InventoryReport:
    """`folder` için salt-okunur envanter + düzenleme önerisi raporu üretir.

    İzin dışı veya var olmayan klasör için `fw.FileWorkerError` yükselir
    (`scan_folder` ile aynı davranış) — sessiz boş rapor üretilmez.
    """
    entries = fw.scan_folder(folder)

    by_ext: dict[str, int] = {}
    empty: list[dict] = []
    old: list[dict] = []
    temp: list[dict] = []
    now = time.time()
    cutoff = old_file_days * 86400

    for e in entries:
        by_ext[e["ext"] or "(uzantısız)"] = by_ext.get(e["ext"] or "(uzantısız)", 0) + 1
        if e["size"] == 0:
            empty.append(e)
        if (now - e["mtime"]) > cutoff:
            old.append(e)
        if _is_temp_name(e["name"]):
            temp.append(e)

    return InventoryReport(
        folder=folder,
        total_files=len(entries),
        by_extension=by_ext,
        duplicate_groups=fw.find_duplicates(entries),
        similar_name_groups=fw.find_similar_names(entries),
        empty_file_candidates=empty,
        old_file_candidates=old,
        temp_name_candidates=temp,
        truncated=len(entries) >= fw.MAX_SCAN_FILES,
    )
