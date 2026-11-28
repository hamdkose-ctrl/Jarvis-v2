import unittest
from unittest.mock import patch

from modules import awareness_watch, pc_autonomy_queue


class PencereKotayiYemez(unittest.TestCase):
    """Pencere değişimi konuşulmuyorsa mail/takvim kotasını tüketmemeli.

    Canlı kusur (28 Kasım 21:33): her tikte "Pencere değişti" üretiliyordu;
    MAX_PER_TICK=1 yüzünden 67 okunmamış mail hiç bildirilmedi. Ölçüm: jarvis.log
    21:33 pencere, 21:35 pencere — mail satırı yok."""

    def test_pencere_maili_bastirmaz(self):
        state = {"window": "WhatsApp", "previous_window": "Jarvis", "unread_mail": 67}
        adaylar = awareness_watch.candidates(state, seen=set(), hour=12, quiet=(0, 0),
                                             sessiz_turler=("window",))
        turler = [a["kind"] for a in adaylar]
        self.assertIn("mail", turler)
        self.assertIn("window", turler)
        self.assertEqual(turler[0], "mail")   # konuşulabilir olan öne

    def test_pencere_konusulsun_istenirse_eski_sira(self):
        state = {"window": "WhatsApp", "previous_window": "Jarvis", "unread_mail": 67}
        adaylar = awareness_watch.candidates(state, seen=set(), hour=12, quiet=(0, 0))
        self.assertEqual([a["kind"] for a in adaylar], ["window"])

    def test_tik_maili_soyler_pencereyi_yazar(self):
        ayar = {"watch_enabled": True, "watch_quiet_start": 0, "watch_quiet_end": 1}
        pc_autonomy_queue._SEEN.clear()
        pc_autonomy_queue._LAST_SPOKEN.clear()
        with patch("config.load_settings", return_value=ayar), \
             patch.object(pc_autonomy_queue, "_inbox_and_calendar",
                          lambda: {"unread_mail": 67}), \
             patch("modules.pc_autonomy_queue.foreground_window", return_value="WhatsApp"), \
             patch("modules.pc_autonomy_queue._announce", return_value=True) as say:
            items = pc_autonomy_queue.watch_tick(None, hour=12)
        metin = " ".join(say.call_args[0][0] for _ in [0])
        self.assertIn("okunmamış mail", metin)
        self.assertIn("window", [i["kind"] for i in items])


if __name__ == '__main__':
    unittest.main()
