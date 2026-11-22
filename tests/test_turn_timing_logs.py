"""Tur zamanlaması iki ayrı log satırına bölünür: anlama ve Core elleri.

Tek sayı ("cevap hazırlama 1-27 sn") kaybın nerede olduğunu göstermiyordu;
bu koruma satırların sessizce silinmesini engeller.
"""
import unittest
from pathlib import Path

KAYNAK = Path(__file__).resolve().parents[1] / 'modules' / 'engine_loop.py'


class TurnTimingLogTests(unittest.TestCase):
    def setUp(self):
        self.metin = KAYNAK.read_text(encoding='utf-8')

    def test_understanding_stage_is_measured(self):
        self.assertIn('Süre: anlama %.0f ms', self.metin)

    def test_core_stage_is_measured(self):
        self.assertIn('Süre: core eller %.0f ms', self.metin)

    def test_total_still_logged(self):
        self.assertIn('Süre: cevap hazırlama %.1f sn', self.metin)


if __name__ == '__main__':
    unittest.main()
