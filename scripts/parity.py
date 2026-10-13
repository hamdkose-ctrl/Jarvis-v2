"""Kaynak ağacı ile kurulu JARVIS ağacını karşılaştırır (parity denetimi).

Yalnızca proje kaynakları karşılaştırılır; kullanıcı verileri, loglar, önbellekler,
sanal ortam ve yedekler dışarıda tutulur. Sonuç dört grupta raporlanır:

    aynı       : iki tarafta da aynı içerik
    eksik      : kaynakta var, kurulumda yok
    farklı     : iki tarafta da var, içerik değişmiş
    fazladan   : kurulumda var, kaynakta yok

Kullanım:
    python scripts/parity.py <kurulum_klasoru> [--kaynak <kaynak_klasoru>] [--json]

Kaynak varsayılanı bu dosyanın iki üst klasörüdür (depo kökü).
Çıkış kodu: 0 = birebir aynı, 1 = fark var, 2 = kullanım hatası.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Karşılaştırmaya girmeyen klasörler: sanal ortam, kullanıcı verisi, önbellek, yedek, bağımlılık.
_SKIP_DIRS = {".venv", "venv", ".git", "__pycache__", ".pytest_cache", ".ruff_cache",
              ".backups", "node_modules", "JarvisAndroid", ".jarvis"}
# Karşılaştırmaya girmeyen dosyalar: derlenmiş/üretilmiş çıktılar ve arşivler.
_SKIP_SUFFIX = (".pyc", ".pyo", ".log", ".zip", ".yeni")


def _iter_files(root: Path):
    """Klasör ağacındaki karşılaştırılabilir dosyaları (göreli yol, tam yol) üretir."""
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in _SKIP_DIRS for part in rel.parts[:-1]):
            continue
        if path.name.endswith(_SKIP_SUFFIX):
            continue
        yield rel, path


def _hash(path: Path) -> str:
    """Git blob sha1'i ile aynı yöntem: updater.py ve git_publish.py ile tutarlı."""
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def collect(root: Path) -> dict:
    """Kök altındaki dosyaların {göreli yol: sha1} haritasını çıkarır."""
    out: dict = {}
    for rel, path in _iter_files(root):
        try:
            out[rel.as_posix()] = _hash(path)
        except OSError:
            continue
    return out


def compare(source: Path, install: Path) -> dict:
    """İki ağacı karşılaştırır; aynı/eksik/farklı/fazladan gruplarını döndürür."""
    src, inst = collect(source), collect(install)
    same: list = []
    missing: list = []
    different: list = []
    for name, digest in sorted(src.items()):
        if name not in inst:
            missing.append(name)
        elif inst[name] != digest:
            different.append(name)
        else:
            same.append(name)
    extra = sorted(name for name in inst if name not in src)
    return {"same": same, "missing": missing, "different": different, "extra": extra,
            "source": str(source), "install": str(install)}


def _report(result: dict) -> None:
    print(f"Kaynak : {result['source']}")
    print(f"Kurulum: {result['install']}")
    print("Hariç  : " + ", ".join(sorted(_SKIP_DIRS)) + " · " + ", ".join(_SKIP_SUFFIX))
    print()
    groups = (("Eksik (kaynakta var, kurulumda yok)", "missing"),
              ("Farklı (içerik değişmiş)", "different"),
              ("Fazladan (kurulumda var, kaynakta yok)", "extra"),
              ("Aynı", "same"))
    for title, key in groups:
        items = result[key]
        print(f"{title}: {len(items)}")
        for name in items:
            print("  " + name)
    print()
    print(f"Özet: aynı={len(result['same'])} · eksik={len(result['missing'])} · "
          f"farklı={len(result['different'])} · fazladan={len(result['extra'])}")
    if result["missing"] or result["different"] or result["extra"]:
        print("Kaynak ile kurulum birebir aynı DEĞİL: güncelleme aktarımı tamamlanmamış olabilir.")
    else:
        print("Kaynak ile kurulum birebir aynı.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Kaynak ağacı ile kurulu JARVIS ağacını karşılaştırır.")
    parser.add_argument("kurulum", help="Çalışan JARVIS kurulum klasörü")
    parser.add_argument("--kaynak", default=str(Path(__file__).resolve().parent.parent),
                        help="Kaynak (depo) klasörü; varsayılan depo kökü")
    parser.add_argument("--json", action="store_true", help="Sonucu JSON olarak yaz")
    args = parser.parse_args(argv)

    source, install = Path(args.kaynak), Path(args.kurulum)
    for label, path in (("kaynak", source), ("kurulum", install)):
        if not path.is_dir():
            print(f"HATA: {label} klasörü bulunamadı: {path}", file=sys.stderr)
            return 2

    result = compare(source, install)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _report(result)
    return 0 if not (result["missing"] or result["different"] or result["extra"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
