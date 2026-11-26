"""Brain 0-11 defteri kapandı: kapanış kaydı duruyor ve dürüst ayrımı koruyor."""
import unittest
from pathlib import Path

DOC = Path(__file__).resolve().parents[1] / "docs" / "architecture" / "BRAIN_00_11_KAPANIS_2026-11-26.md"


class ClosureRecord(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text(encoding="utf-8")

    def test_every_item_is_listed(self):
        for index in range(12):
            self.assertIn(f"BRAIN-{index:02d}", self.text)

    def test_measurement_gap_is_not_declared_closed(self):
        self.assertIn("M-1", self.text)
        self.assertIn("ölçülmedi", self.text.lower())

    def test_single_understanding_owner_kept(self):
        self.assertIn("tek anlama sahibi", self.text.lower())


if __name__ == "__main__":
    unittest.main()
