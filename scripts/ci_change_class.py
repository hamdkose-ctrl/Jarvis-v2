"""Değişiklik sınıfı: yalnız doküman mı, kod mu? CI hızlı yolu buna bakar."""
from __future__ import annotations

import argparse
import re
import sys

# Kod sayılan önekler: biri bile değişirse tam doğrulama şart.
_KOD_ONEK = (
    'modules/', 'scripts/', 'tests/', 'webui/', 'android/', 'assets/', '.github/',
    'requirements',
)
_MD = re.compile(r"\.md\Z", re.IGNORECASE)


def classify(paths) -> str:
    """Yalnız markdown değiştiyse 'docs'; başka her durumda 'code'."""
    satirlar = [p.strip().replace("\\", "/") for p in paths if isinstance(p, str) and p.strip()]
    if not satirlar:
        return "code"          # sınıflandırılamayan değişiklik güvenli tarafa düşer
    for yol in satirlar:
        if yol.startswith(_KOD_ONEK) or not _MD.search(yol):
            return "code"
    return "docs"


def main(argv=None) -> int:
    """CI adımı: --paths ile gelen dosyaları sınıflar, "true"/"false" yazar."""
    parser = argparse.ArgumentParser(description="CI hızlı yol sınıflandırıcısı")
    parser.add_argument("--paths", nargs="*", default=[], help="değişen dosya yolları")
    args = parser.parse_args(argv)
    print("true" if classify(args.paths) == "code" else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
