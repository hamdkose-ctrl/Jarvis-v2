"""Telefon açılış hatası görünür olmalı (R8)."""
import unittest
from unittest.mock import Mock, patch

from modules import phone


class PhoneErrorVisibilityTests(unittest.TestCase):
    def tearDown(self):
        phone.note_error("")

    def test_hata_saklanir_ve_bosluklar_sadelestirilir(self):
        phone.note_error("  Güvenli   bağlantı\n hazır değil  ")
        self.assertEqual(phone.last_error(), "Güvenli bağlantı hazır değil")

    def test_hata_300_karakterle_sinirlanir(self):
        phone.note_error("x" * 500)
        self.assertEqual(len(phone.last_error()), 300)

    def test_hata_yoksa_bos_doner(self):
        phone.note_error("")
        self.assertEqual(phone.last_error(), "")

if __name__ == "__main__":
    unittest.main()