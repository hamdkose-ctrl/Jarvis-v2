"""Üretimde çağrılmayan ortak fonksiyonları listeler (AST + tek geçişli sayaç).

Kapsam: modules/*.py ve web.py içindeki alt çizgiyle başlamayan, test olmayan
üst düzey fonksiyonlar. Çağrı sayımı modules/*.py, tests/*.py ve web.py içindeki
tüm geçişlerdir; tanım satırının kendisi bir geçiş sayılır.
"""
from __future__ import annotations

import ast
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _sources():
    files = sorted((ROOT / "modules").glob("*.py"))
    entry = ROOT / "web.py"
    if entry.exists():
        files.append(entry)
    return files


def _definitions(files):
    out = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            name = getattr(node, "name", "")
            is_func = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            if is_func and name and not name.startswith("_") and not name.startswith("test"):
                out.append((path.name, name))
    return out


def _occurrences() -> Counter:
    counts = Counter()
    for pattern in ("modules/*.py", "tests/*.py"):
        for path in ROOT.glob(pattern):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            counts.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text))
    entry = ROOT / "web.py"
    if entry.exists():
        counts.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", entry.read_text(encoding="utf-8")))
    return counts


def scan():
    """(modül, ad) çiftleri: üretimde kendisinden başka geçişi olmayan fonksiyonlar."""
    counts = _occurrences()
    return sorted((module[:-3], name) for module, name in _definitions(_sources())
                  if counts[name] <= 1)


def main() -> int:
    for module, name in scan():
        print(f"{module}.{name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
