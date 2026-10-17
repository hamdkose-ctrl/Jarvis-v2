"""Jarvis'te daha önce kabul edilmiş kritik davranışların değişmez regresyon kapısı.

Ayrıntılı testler kendi dosyalarında kalır. Kullanıcıya verilmiş davranışlar kalıcı contract
kimlikleriyle ``tests.stability_manifest`` içinde tutulur ve bu kapı hepsini birlikte çalıştırır.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.stability_manifest import CONTRACT_MANIFEST, test_names

CONTRACTS = test_names()


def main() -> int:
    loader = unittest.defaultTestLoader
    suite = loader.loadTestsFromNames(CONTRACTS)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print('Stability contracts:', ', '.join(CONTRACT_MANIFEST))
        return 0
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
