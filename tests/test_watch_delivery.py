"""Uyanıklık bildirimi: kapalıyken tek çağrı yok, açıkken mevcut sahibe gider."""
import unittest
from unittest.mock import patch

from modules import awareness_watch, pc_autonomy_queue


class Delivery(unittest.TestCase):
    def setUp(self):
        pc_autonomy_queue._SEEN.clear()

    def _run(self, settings, state=None):
        with patch("config.load_settings", return_value=settings),              patch("modules.pc_autonomy_queue.foreground_window", return_value=""),              patch("modules.voice_runtime.announce_active", return_value=True) as say:
            items = pc_autonomy_queue.watch_tick(_Runtime(settings), hour=12)
        return items, say

    def test_disabled_watch_never_announces(self):
        items, say = self._run({}, {})
        self.assertEqual(items, [])
        say.assert_not_called()

    def test_enabled_watch_announces_once(self):
        state = {"status": "ok", "match": {"title": "Chrome"}}
        with patch.object(pc_autonomy_queue, "_inbox_and_calendar", lambda: {}), \
             patch("config.load_settings", return_value={"watch_enabled": True, "watch_quiet_start": 0, "watch_quiet_end": 1}), \
             patch("modules.pc_autonomy_queue.foreground_window", return_value="Chrome"):
            settings = {"watch_enabled": True, "watch_quiet_start": 0, "watch_quiet_end": 1}
            first = pc_autonomy_queue.watch_tick(_Runtime(settings), hour=12)
            second = pc_autonomy_queue.watch_tick(_Runtime(settings), hour=12)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])


class _Runtime:
    def __init__(self, settings):
        self.profile = type("P", (), {"settings": settings})()
        self.log = type("L", (), {"info": staticmethod(lambda *a, **k: None)})()


if __name__ == "__main__":
    unittest.main()


class VoiceAndNoise(unittest.TestCase):
    """Ses açık; gereksiz bilgi (pencere değişimi) varsayılan olarak konuşulmaz."""

    def test_announce_is_silent_when_voice_off(self):
        from modules import pc_autonomy_queue, voice_runtime
        from unittest import mock
        with mock.patch.object(voice_runtime, "announce_active") as announce, \
             mock.patch("config.load_settings", return_value={"watch_enabled": True, "watch_voice": False}):
            self.assertFalse(pc_autonomy_queue._announce("pencere değişti"))
        self.assertFalse(announce.called)

    def test_announce_speaks_when_voice_on(self):
        from modules import pc_autonomy_queue, voice_runtime
        from unittest import mock
        with mock.patch.object(voice_runtime, "announce_active", return_value=True) as announce, \
             mock.patch("config.load_settings", return_value={"watch_voice": True}):
            self.assertTrue(pc_autonomy_queue._announce("pencere değişti"))
        self.assertTrue(announce.called)


class WindowNoticesAreQuiet(unittest.TestCase):
    """Pencere değişimi gözünün önünde: ses açık olsa da konuşulmaz (26 Kasım)."""

    def test_window_change_is_logged_not_spoken(self):
        from modules import pc_autonomy_queue, voice_runtime
        from unittest import mock
        pc_autonomy_queue._SEEN.clear()
        runtime = mock.Mock()
        with mock.patch("config.load_settings", return_value={"watch_enabled": True}),              mock.patch("modules.pc_autonomy_queue.foreground_window", return_value="Chrome"),              mock.patch.object(voice_runtime, "announce_active") as announce:
            items = pc_autonomy_queue.watch_tick(runtime, hour=12)
        self.assertEqual(len(items), 1)
        self.assertFalse(announce.called)
        self.assertTrue(runtime.log.info.called)


class ClockIndependent(unittest.TestCase):
    """Uyanıklık testleri duvar saatine bağlı olmamalı (CI'da gece koşunca düşüyordu)."""

    def setUp(self):
        pc_autonomy_queue._SEEN.clear()

    def _tick(self, hour):
        from unittest import mock as _mock
        with _mock.patch.object(pc_autonomy_queue, "_inbox_and_calendar", lambda: {}), \
             _mock.patch("config.load_settings",
                         return_value={"watch_enabled": True, "watch_quiet_start": 22, "watch_quiet_end": 8}), \
             _mock.patch("modules.pc_autonomy_queue.foreground_window", return_value="Chrome"):
            return pc_autonomy_queue.watch_tick(None, hour=hour)

    def test_daytime_hour_produces_a_candidate(self):
        self.assertEqual(len(self._tick(12)), 1)

    def test_quiet_hour_produces_nothing(self):
        self.assertEqual(self._tick(23), [])
        self.assertEqual(self._tick(3), [])

class TekrarVeSinir(unittest.TestCase):
    """Belge: aynı olay tekrar söylenmez, bir tikte en fazla bir aday döner."""

    def setUp(self):
        pc_autonomy_queue._SEEN.clear()

    def _tick(self, okunmamis):
        ayar = {"watch_enabled": True, "watch_quiet_start": 0, "watch_quiet_end": 1}
        with patch("config.load_settings", return_value=ayar), \
             patch.object(pc_autonomy_queue, "_inbox_and_calendar",
                          lambda: {"unread_mail": okunmamis}), \
             patch("modules.pc_autonomy_queue.foreground_window", return_value=""), \
             patch("modules.pc_autonomy_queue._announce") as say:
            items = pc_autonomy_queue.watch_tick(_Runtime(ayar), hour=12)
        return items, say

    def test_ayni_olay_ikinci_kez_soylenmez(self):
        ilk, _ = self._tick(3)
        self.assertEqual(len(ilk), 1)
        ikinci, say = self._tick(3)
        self.assertEqual(ikinci, [])
        self.assertFalse(say.called)

    def test_farkli_olay_beklemeden_soylenir(self):
        self._tick(3)
        ucuncu, say = self._tick(4)
        self.assertEqual(len(ucuncu), 1)
        self.assertTrue(say.called)


class SonBildirimDogruMu(unittest.TestCase):
    """Ses kapalıyken/başarısızken "son bildirim" gösterilmemeli (sağlık P3)."""

    AYAR = {"watch_enabled": True, "watch_quiet_start": 0, "watch_quiet_end": 1}

    def setUp(self):
        pc_autonomy_queue._SEEN.clear()
        pc_autonomy_queue._LAST_SPOKEN.clear()

    def _tick(self, seslendi):
        with patch("config.load_settings", return_value=self.AYAR), \
             patch.object(pc_autonomy_queue, "_inbox_and_calendar",
                          lambda: {"unread_mail": 3}), \
             patch("modules.pc_autonomy_queue.foreground_window", return_value=""), \
             patch("modules.pc_autonomy_queue._announce", return_value=seslendi):
            return pc_autonomy_queue.watch_tick(None, hour=12)

    def test_ses_kapaliyken_kayit_yok(self):
        self.assertEqual(len(self._tick(False)), 1)
        self.assertEqual(pc_autonomy_queue.announce_state(), {})

    def test_sesliyken_kayit_var(self):
        self._tick(True)
        self.assertIn("mail", pc_autonomy_queue.announce_state()["text"])


class AcilTakvimGecikmez(unittest.TestCase):
    """Takvim uyarısı zaman-kritik: herhangi bir hız sınırı onu geciktirmemeli.

    Bu testin varlık sebebi gerçek bir hatadır (28 Kasım): bildirimlere 10 dakikalık
    bekleme eklenmişti ve "5 dakika sonra toplantı" uyarısı 10 dakika gecikecekti.
    Bekleme geri alındı; bu test aynı sınıfın geri gelmemesini sabitler."""

    AYAR = {"watch_enabled": True, "watch_quiet_start": 0, "watch_quiet_end": 1}

    def setUp(self):
        pc_autonomy_queue._SEEN.clear()
        pc_autonomy_queue._LAST_SPOKEN.clear()

    def _tick(self, state):
        with patch("config.load_settings", return_value=self.AYAR), \
             patch.object(pc_autonomy_queue, "_inbox_and_calendar", lambda: state), \
             patch("modules.pc_autonomy_queue.foreground_window", return_value=""), \
             patch("modules.pc_autonomy_queue._announce", return_value=True) as say:
            items = pc_autonomy_queue.watch_tick(None, hour=12)
        return items, say

    def test_mail_soylendikten_hemen_sonra_takvim_de_soylenir(self):
        ilk, _ = self._tick({"unread_mail": 3})
        self.assertEqual(ilk[0]["kind"], "mail")
        ikinci, say = self._tick({"next_event_minutes": 5})
        self.assertEqual(len(ikinci), 1)
        self.assertEqual(ikinci[0]["kind"], "calendar")
        self.assertTrue(say.called)

    def test_sessiz_saatte_takvim_de_soylenmez(self):
        with patch("config.load_settings",
                   return_value={"watch_enabled": True, "watch_quiet_start": 0,
                                 "watch_quiet_end": 23}), \
             patch.object(pc_autonomy_queue, "_inbox_and_calendar",
                          lambda: {"next_event_minutes": 5}), \
             patch("modules.pc_autonomy_queue.foreground_window", return_value=""), \
             patch("modules.pc_autonomy_queue._announce") as say:
            items = pc_autonomy_queue.watch_tick(None, hour=12)
        self.assertEqual(items, [])
        self.assertFalse(say.called)


if __name__ == '__main__':
    unittest.main()
