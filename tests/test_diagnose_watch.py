"""Teşhis: uyanıklık (gözlem) durumu görünür olmalı."""
import unittest
from unittest.mock import patch

from modules import diagnose, pc_autonomy_queue


class UyaniklikTeshisi(unittest.TestCase):
    def setUp(self):
        pc_autonomy_queue._SEEN.clear()

    def test_kapaliyken_nasil_acilacagi_soylenir(self):
        with patch("config.load_settings", return_value={}):
            item = diagnose.check_watch()
        self.assertEqual(item["status"], "warn")
        self.assertIn("kapalı", item["detail"])
        self.assertTrue(item["fix"])

    def test_acikken_sessiz_saat_ve_olay_sayisi(self):
        pc_autonomy_queue._SEEN.update({"a", "b"})
        with patch("config.load_settings",
                   return_value={"watch_enabled": True, "watch_quiet_start": 23,
                                 "watch_quiet_end": 7}):
            item = diagnose.check_watch()
        self.assertEqual(item["status"], "ok")
        self.assertIn("23:00–07:00", item["detail"])
        self.assertIn("2 olay", item["detail"])

    def test_ayar_okunamazsa_sessizce_atlanir(self):
        with patch("config.load_settings", side_effect=OSError("yok")):
            self.assertIsNone(diagnose.check_watch())


if __name__ == '__main__':
    unittest.main()
