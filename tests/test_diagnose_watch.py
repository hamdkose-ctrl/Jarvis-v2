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

    def test_son_bildirim_gorunur(self):
        ayar = {"watch_enabled": True, "watch_quiet_start": 0, "watch_quiet_end": 1}
        pc_autonomy_queue._LAST_SPOKEN.clear()
        with patch("config.load_settings", return_value=ayar), \
             patch.object(pc_autonomy_queue, "_inbox_and_calendar", lambda: {"unread_mail": 3}), \
             patch("modules.pc_autonomy_queue.foreground_window", return_value=""), \
             patch("modules.pc_autonomy_queue._announce"):
            pc_autonomy_queue.watch_tick(None, hour=12, now=1764432000.0)
        with patch("config.load_settings", return_value=ayar):
            item = diagnose.check_watch()
        self.assertIn("son bildirim", item["detail"])

    def test_bildirim_yoksa_acikca_soylenir(self):
        pc_autonomy_queue._LAST_SPOKEN.clear()
        with patch("config.load_settings", return_value={"watch_enabled": True}):
            item = diagnose.check_watch()
        self.assertIn("henüz bildirim yok", item["detail"])


if __name__ == '__main__':
    unittest.main()
