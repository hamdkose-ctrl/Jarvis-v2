"""Çağıransız yüzeyler kayıtsız kalamaz: tarama ile kayıt birbirini tutmalı."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _scan():
    spec = importlib.util.spec_from_file_location("dead_symbol_scan",
                                                  ROOT / "scripts" / "dead_symbol_scan.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {f"{mod}.{ad}" for mod, ad in module.scan()}


def _kayit():
    names = set()
    for line in (ROOT / "docs" / "olu_kod_kaydi.txt").read_text(encoding="utf-8").splitlines():
        text = line.split("#", 1)[0].strip()
        if text:
            names.add(text)
    return names


class OluKodKaydiTestleri(unittest.TestCase):
    def test_taramadaki_her_yuzey_kayitta(self):
        eksik = _scan() - _kayit()
        self.assertFalse(eksik, f"Kayda yazılmayan çağıransız yüzeyler: {sorted(eksik)}")

    def test_kayittaki_her_yuzey_gercekten_cagiransiz(self):
        bayat = _kayit() - _scan()
        self.assertFalse(bayat, f"Artık çağrılan ya da silinmiş kayıtlar: {sorted(bayat)}")


if __name__ == "__main__":
    unittest.main()
