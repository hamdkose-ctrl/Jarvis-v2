from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "testler-windows.yml"


def _adimlar() -> list[dict]:
    veri = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return veri["jobs"]["testler-windows"]["steps"]


def _sinif_adimi() -> dict:
    for adim in _adimlar():
        if adim.get("id") == "sinif":
            return adim
    raise AssertionError("sinif adimi bulunamadi")


class PushHizliYolTestleri(unittest.TestCase):
    """main push'unda da hızlı yol sınıflandırması çalışmalı."""

    def test_sinif_adimi_push_olayinda_da_kosar(self):
        self.assertNotIn("if", _sinif_adimi())

    def test_push_araligi_env_ile_gelir(self):
        env = _sinif_adimi()["env"]
        self.assertIn("JARVIS_PUSH_BEFORE", env)
        self.assertIn("JARVIS_PUSH_AFTER", env)

    def test_push_araligi_kullanilir(self):
        betik = _sinif_adimi()["run"]
        self.assertIn("$once..$sonra", betik)
        self.assertIn("GITHUB_EVENT_NAME", betik)

    def test_bilinmeyen_aralikta_tam_pakete_duser(self):
        betik = _sinif_adimi()["run"]
        self.assertIn("^0+$", betik)
        self.assertIn("agir=true", betik)


if __name__ == "__main__":
    unittest.main()
