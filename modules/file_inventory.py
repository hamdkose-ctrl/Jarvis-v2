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


# ------------------------------------------------------------------ Excel çıktısı
# İkinci bir tablo/Excel yazıcısı kurulmaz: var olan, test edilmiş
# `modules/workbench.write_output`/`unique_path` kullanılır (gerçek çalıştığı
# bu PR'da elle ve mevcut test paketiyle doğrulandı). `workbench` burada
# modül seviyesinde import edilmez; o modül `llm`'i (ve dolayısıyla
# google-genai'yi) yüklüyor, oysa envanter raporu üretmek model gerektirmez —
# yalnız gerçekten dosya yazılacağı an (`export_xlsx`) içeri alınır.

def _rows(entries: list[dict]) -> list[list]:
    return [[e["name"], e["path"], e["ext"] or "", e["size"]] for e in entries]


def _group_rows(groups: list[list[dict]], group_label: str) -> list[list]:
    out = []
    for i, group in enumerate(groups, 1):
        for e in group:
            out.append([f"{group_label} {i}", e["name"], e["path"], e["size"]])
    return out


def export_xlsx(report: InventoryReport, *, _workbench=None) -> str:
    """Raporu, kaynak klasörün içine yeni bir `.xlsx` dosyası olarak yazar.

    Dosya adı `unique_path` ile çakışma yaşamaz (var olan bir adın üzerine
    yazılmaz). Döndürülen yol string'dir. Hiçbir taranan dosyaya dokunulmaz;
    yalnız yeni, tek bir özet dosyası eklenir.

    `_workbench` yalnız testler içindir (gerçek `modules.workbench`'i tüm
    `llm`/google-genai zincirine girmeden değiştirmek için doğrudan parametre
    olarak verilir). `sys.modules` üzerinden gizlice değiştirmek, `workbench`
    bu süreçte başka bir yerden önceden gerçekten içeri alınmışsa Python'un
    import önbelleklemesi nedeniyle sessizce işe yaramaz — bu yüzden parametre
    kullanılır, modül yama tekniği kullanılmaz.
    """
    from pathlib import Path

    if _workbench is not None:
        workbench = _workbench
    else:
        from . import workbench

    sheets = [
        ("Özet", [["Alan", "Değer"],
                  ["Klasör", report.folder],
                  ["Toplam dosya", report.total_files],
                  ["Yineleme grubu", len(report.duplicate_groups)],
                  ["Benzer ad grubu", len(report.similar_name_groups)],
                  ["Boş dosya adayı", len(report.empty_file_candidates)],
                  ["Eski dosya adayı (180+ gün)", len(report.old_file_candidates)],
                  ["Geçici ad adayı", len(report.temp_name_candidates)],
                  ["Tarama sınırına ulaşıldı mı", "Evet" if report.truncated else "Hayır"]]),
        ("Uzantı dağılımı", [["Uzantı", "Sayı"]] + [[k, v] for k, v in sorted(report.by_extension.items())]),
        ("Yinelenenler", [["Grup", "Dosya adı", "Yol", "Boyut"]] + _group_rows(report.duplicate_groups, "Yineleme")),
        ("Benzer adlar", [["Grup", "Dosya adı", "Yol", "Boyut"]] + _group_rows(report.similar_name_groups, "Benzer")),
        ("Boş dosya adayları", [["Dosya adı", "Yol", "Uzantı", "Boyut"]] + _rows(report.empty_file_candidates)),
        ("Eski dosya adayları", [["Dosya adı", "Yol", "Uzantı", "Boyut"]] + _rows(report.old_file_candidates)),
        ("Geçici ad adayları", [["Dosya adı", "Yol", "Uzantı", "Boyut"]] + _rows(report.temp_name_candidates)),
    ]
    folder = Path(report.folder)
    destination = workbench.unique_path(folder, "Klasor_Envanteri", ".xlsx")
    workbench.write_output(destination, f"Klasör envanteri · {folder.name}", sheets)
    return str(destination)
