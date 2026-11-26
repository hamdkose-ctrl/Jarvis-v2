"""Uyanıklık bildirimi: kapalıyken tek çağrı yok, açıkken mevcut sahibe gider."""
import unittest
from unittest.mock import patch

from modules import awareness_watch, pc_autonomy_queue


class Delivery(unittest.TestCase):
    def setUp(self):
        pc_autonomy_queue._SEEN.clear()

    def _run(self, settings, state=None):
        with patch("config.load_settings", return_value=settings),              patch("modules.pc_autonomy_queue.foreground_window", return_value=""),              patch("modules.voice_runtime.announce_active", return_value=True) as say:
            items = pc_autonomy_queue.watch_tick(_Runtime(settings))
        return items, say

    def test_disabled_watch_never_announces(self):
        items, say = self._run({}, {})
        self.assertEqual(items, [])
        say.assert_not_called()

    def test_enabled_watch_announces_once(self):
        state = {"status": "ok", "match": {"title": "Chrome"}}
        with patch("config.load_settings", return_value={"watch_enabled": True, "watch_quiet_start": 0, "watch_quiet_end": 1}),              patch("modules.pc_autonomy_queue.foreground_window", return_value="Chrome"):
            settings = {"watch_enabled": True, "watch_quiet_start": 0, "watch_quiet_end": 1}
            first = pc_autonomy_queue.watch_tick(_Runtime(settings))
            second = pc_autonomy_queue.watch_tick(_Runtime(settings))
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])


class _Runtime:
    def __init__(self, settings):
        self.profile = type("P", (), {"settings": settings})()
        self.log = type("L", (), {"info": staticmethod(lambda *a, **k: None)})()


if __name__ == "__main__":
    unittest.main()


class SilentByDefault(unittest.TestCase):
    """Uyanıklık varsayılan olarak SES ÇIKARMAZ (canlı istek 26 Kasım)."""

    def test_announce_is_silent_when_voice_off(self):
        from modules import pc_autonomy_queue, voice_runtime
        from unittest import mock
        with mock.patch.object(voice_runtime, "announce_active") as announce, \
             mock.patch("config.load_settings", return_value={"watch_enabled": True}):
            self.assertFalse(pc_autonomy_queue._announce("pencere değişti"))
        self.assertFalse(announce.called)

    def test_announce_speaks_when_voice_on(self):
        from modules import pc_autonomy_queue, voice_runtime
        from unittest import mock
        with mock.patch.object(voice_runtime, "announce_active", return_value=True) as announce, \
             mock.patch("config.load_settings", return_value={"watch_voice": True}):
            self.assertTrue(pc_autonomy_queue._announce("pencere değişti"))
        self.assertTrue(announce.called)
