"""Yol haritası 0–4 kapanış kaydı: dosya duruyor ve maddeler adlandırılmış."""
import unittest
from pathlib import Path

DOC = Path(__file__).resolve().parents[1] / "docs" / "YOL_HARITASI_0_4_KAPANIS_2026-11-26.md"


class Closure(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text(encoding="utf-8")

    def test_all_five_items_are_present(self):
        for title in ("Dosya işlemleri", "Arama sonucuna tıklama", "Kopyala", "Form doldurma", "Zamanlı iş"):
            self.assertIn(title, self.text)

    def test_known_limit_is_stated(self):
        self.assertIn("odak geçişi", self.text)

    def test_verdict_present(self):
        self.assertIn("kapandı", self.text.lower())


if __name__ == "__main__":
    unittest.main()
