"""Deterministik roadmap drift CI kontrolu.

PR'de yol haritasini (docs/Jarvis_Yol_Haritasi.md) guncellemesi gereken
degisiklik var mi denetler. LLM, ag veya GitHub API cagirisi YAPMAZ.
Sadece git diff ve AST kullanir.

Kural (sözleşme):

- modules/*.py YENI dosya (main'de yok) -> yeni yetenek -> roadmap gerekli
- modules/*.py DEGIŞTIRILMIŞ ve public üst-seviye simge
  (class/def, '_' ile baslamayanlar) sayisi main'e gore artmissa -> yeni yetenek
  -> roadmap gerekli
- modules/*.py DEGIŞTIRILMIŞ ve mantik/govdesi degismisse -> roadmap gerekli
  (fail-closed; yarin/boşluk degisikligi degilse PASS)
- docs/Jarvis_Yol_Haritasi.md degismis -> zaten guncellenmis (PASS tetikleyici)
- tests/, .github/, scripts/, docs* (roadmap haric) -> hariç, gerekli degil
- Digers (kok seviyeli .py, diger uzantilar) -> konservatif olarak
  roadmap-affecting sayilmaz (yanlis pozitif onleme)

Karar:
  roadmap_affecting bos degil VE roadmap degismemisse -> FAIL (exit 1)
  diger durumlar -> PASS (exit 0)
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROADMAP_FILE = "docs/Jarvis_Yol_Haritasi.md"
ROADMAP_ENTRIES_DIR = "docs/yol_haritasi_girisler/"

EXCLUDED_PREFIXES = (
    "tests/",
    ".github/",
    "scripts/",
    "docs/",
)

EXCLUDED_SUFFIXES = (
    ".md",
    ".txt",
    ".bat",
    ".ps1",
    ".sh",
    ".gitignore",
    ".gitattributes",
)


def _run(args, cwd=None):
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
    )


def _is_new_file(root: Path, path: str) -> bool:
    cp = _run(["git", "cat-file", "-e", f"main:{path}"], cwd=str(root))
    return cp.returncode != 0


def _normalize(source: str) -> str:
    """Kaynagi AST ile yeniden uret: yorumlar ve gereksiz bosluklar kirilir,
    sadece yapisal esligi kontrol etmek icin kullanilir."""
    try:
        tree = ast.parse(source)
        return ast.unparse(tree)
    except SyntaxError:
        return source


def _public_symbols(source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    symbols = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and not node.name.startswith("_"):
            symbols.add(node.name)
    return symbols


def _symbols_on_main(root: Path, path: str) -> set[str]:
    cp = _run(["git", "show", f"main:{path}"], cwd=str(root))
    if cp.returncode != 0:
        return set()
    return _public_symbols(cp.stdout)


def _symbols_current(root: Path, path: str) -> set[str]:
    p = root / path
    if not p.is_file():
        return set()
    return _public_symbols(p.read_text(encoding="utf-8", errors="replace"))


def _symbol_delta(root: Path, path: str) -> set[str]:
    return _symbols_current(root, path) - _symbols_on_main(root, path)


def _body_changed_on_main(root: Path, path: str) -> bool:
    """Mevcut dosyanin normalized govdesi ile main'deki govdesini karsilastirir.
    Farkliysa True (mantik degisti)."""
    cp = _run(["git", "show", f"main:{path}"], cwd=str(root))
    if cp.returncode != 0:
        return False
    main_norm = _normalize(cp.stdout)
    p = root / path
    if not p.is_file():
        return False
    cur_norm = _normalize(p.read_text(encoding="utf-8", errors="replace"))
    return main_norm != cur_norm


def _is_excluded(path: str) -> bool:
    if path == ROADMAP_FILE:
        return True
    for prefix in EXCLUDED_PREFIXES:
        if path.startswith(prefix):
            return True
    for suffix in EXCLUDED_SUFFIXES:
        if path.endswith(suffix):
            return True
    return False


def classify(
    changed_files: list[str],
    root: Path = ROOT,
    *,
    is_new_file=None,
    symbol_delta=None,
    body_delta=None,
) -> dict:
    """Degisen dosyalari siniflandir ve karar ver.

    Donduren dict anahtarlari:
      roadmap_affecting : list[str]  roadmap guncellemesini gerektiren degisiklikler
      excluded          : list[str]  hariç tutulmus degisiklikler
      roadmap_updated   : bool       docs/Jarvis_Yol_Haritasi.md degismis mi
      roadmap_required  : bool       roadmap_affecting bos degil mi
      pass              : bool       gerekirse roadmap guncellenmissa True
    """
    is_new_file = is_new_file or (lambda p: _is_new_file(root, p))
    symbol_delta = symbol_delta or (lambda p: _symbol_delta(root, p))
    body_delta = body_delta or (lambda p: _body_changed_on_main(root, p))

    roadmap_affecting: list[str] = []
    excluded: list[str] = []
    roadmap_updated = False

    for path in changed_files:
        # Yol haritasi girişi artık PR basina ayri dosyaya yazilabiliyor (çakışma önlemi):
        # docs/yol_haritasi_girisler/T<no>.md de "yol haritasi güncellendi" sayilir.
        if path == ROADMAP_FILE or path.startswith(ROADMAP_ENTRIES_DIR):
            roadmap_updated = True
            continue
        if _is_excluded(path):
            excluded.append(path)
            continue

        # modules/*.py -> yeni dosya, yeni public simge veya govde degisikligi
        # = yeni yetenek / Faz durumu degisikligi -> roadmap gerekli.
        if path.startswith("modules/") and path.endswith(".py"):
            if is_new_file(path):
                roadmap_affecting.append(path)
                continue
            new_symbols = symbol_delta(path)
            if new_symbols:
                roadmap_affecting.append(path)
                continue
            if body_delta(path):
                roadmap_affecting.append(path)
                continue

        # Digers: varsayilan olarak roadmap-affecting sayilmaz
        # (yanlis pozitif onleme icin konservatif).

    roadmap_required = len(roadmap_affecting) > 0
    return {
        "roadmap_affecting": sorted(roadmap_affecting),
        "excluded": sorted(excluded),
        "roadmap_updated": roadmap_updated,
        "roadmap_required": roadmap_required,
        "pass": (not roadmap_required) or roadmap_updated,
    }


def _changed_files(root: Path = ROOT) -> list[str]:
    """PR ana dala (main) gore degisen dosyalari dondurur."""
    cp = _run(["git", "diff", "--name-only", "main...HEAD"], cwd=str(root))
    if cp.returncode != 0:
        raise RuntimeError(f"git diff main...HEAD basarisiz: {cp.stderr.strip()}")
    return [line for line in cp.stdout.splitlines() if line.strip()]


def main() -> int:
    changed_files = _changed_files(root=ROOT)
    result = classify(changed_files, root=ROOT)
    if result["roadmap_required"] and not result["roadmap_updated"]:
        print(
            "ROADMAP DRIFT: Aşağıdaki yol haritası etkileyici değişiklikler "
            "bulundu ancak docs/Jarvis_Yol_Haritasi.md güncellenmemiş:"
        )
        for path in result["roadmap_affecting"]:
            print(f"  - {path}")
        print("Lütfen PR'de docs/Jarvis_Yol_Haritasi.md'yi de güncelleyin.")
        return 1
    if result["roadmap_affecting"]:
        print(
            "ROADMAP OK: Yol haritası etkileyici değişiklikler söz konusu ve "
            "docs/Jarvis_Yol_Haritasi.md güncellenmiş."
        )
    else:
        print(
            "ROADMAP OK: Yol haritası güncellemesini gerektiren değişiklik yok."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

