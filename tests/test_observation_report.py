""""Ne görüyorsun?" — gözlem katmanı bildiğini söyler, bilmediğini uydurmaz."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from modules import command_manager, pc_autonomy_queue


class GozlemRaporu(unittest.TestCase):
    def setUp(self):
        pc_autonomy_queue._SEEN.clear()
        pc_autonomy_queue._LAST_SPOKEN.clear()

    def test_kapaliyken_de_durum_soylenir(self):
        with patch("config.load_settings", return_value={}), \
             patch.object(pc_autonomy_queue, "_inbox_and_calendar", lambda: {}):
            rapor = pc_autonomy_queue.observation_report()
        self.assertIn("uyanıklık kapalı", rapor)
        self.assertIn("henüz bildirim yok", rapor)

    def test_mail_ve_takvim_varsa_yazilir(self):
        with patch("config.load_settings",
                   return_value={"watch_enabled": True, "watch_quiet_start": 23,
                                 "watch_quiet_end": 7}), \
             patch.object(pc_autonomy_queue, "_inbox_and_calendar",
                          lambda: {"unread_mail": 4, "next_event_minutes": 12}):
            rapor = pc_autonomy_queue.observation_report()
        self.assertIn("uyanıklık açık (sessiz 23:00–07:00)", rapor)
        self.assertIn("4 okunmamış mail", rapor)
        self.assertIn("12 dakika sonra", rapor)

    def test_rapor_sormak_bildirimleri_yutmaz(self):
        with patch("config.load_settings", return_value={"watch_enabled": True}), \
             patch.object(pc_autonomy_queue, "_inbox_and_calendar",
                          lambda: {"unread_mail": 4}):
            pc_autonomy_queue.observation_report()
        self.assertEqual(pc_autonomy_queue._SEEN, set())

    def test_komut_raporu_baglar(self):
        ctx = SimpleNamespace(profile=SimpleNamespace(slug="hamdi"), session="s")
        with patch.object(pc_autonomy_queue, "observation_report", lambda: "RAPOR"):
            self.assertEqual(command_manager.dispatch(ctx, "ne görüyorsun?", "ne görüyorsun?"),
                             "RAPOR")


if __name__ == '__main__':
    unittest.main()
