"""`privacy` ↔ `config` içe aktarma sırası: hangi modül önce yüklenirse yüklensin çalışır.

Canlı kusur (22 Kasım 2026): `python -m unittest test_model_free_news_fallback` tek
başına düşüyordu — `privacy` önce yüklenince `config` modül düzeyinde `API_KEY`
hesaplıyor, `privacy.unprotect` henüz tanımlı olmadığı için
"partially initialized module" hatası alınıyordu. Anahtar artık tembel okunuyor.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ImportOrderTests(unittest.TestCase):
    def _run(self, script):
        sonuc = subprocess.run([sys.executable, '-X', 'utf8', '-c', script],
                               cwd=str(ROOT), capture_output=True, text=True, timeout=120)
        self.assertEqual(sonuc.returncode, 0, sonuc.stderr[-800:])
        return sonuc.stdout.strip()

    def test_privacy_first_then_config_key(self):
        cikti = self._run(
            'import modules.privacy\n'
            'from config import API_KEY\n'
            'print(type(API_KEY).__name__)')
        self.assertEqual(cikti, 'str')

    def test_config_first_then_privacy(self):
        cikti = self._run(
            'from config import API_KEY\n'
            'import modules.privacy\n'
            'print(type(API_KEY).__name__, modules.privacy.mode())')
        self.assertTrue(cikti.startswith('str '), cikti)

    def test_module_getattr_only_serves_api_key(self):
        cikti = self._run(
            'import config\n'
            'try:\n'
            '    config.BULUNMAYAN_ALAN\n'
            'except AttributeError as exc:\n'
            '    print("AttributeError" if "BULUNMAYAN_ALAN" in str(exc) else "yanlış")\n')
        self.assertEqual(cikti, 'AttributeError')
