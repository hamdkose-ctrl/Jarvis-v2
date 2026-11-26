"""Uyanıklık ön pencereyi gerçekten okur (boş sorgu ile değil)."""
import unittest
from unittest.mock import patch

from modules import pc_autonomy_queue


class _Runtime:
    log = type("L", (), {"info": staticmethod(lambda *a, **k: None)})()


class Foreground(unittest.TestCase):
    def setUp(self):
        pc_autonomy_queue._SEEN.clear()

    def test_foreground_title_opens_candidate(self):
        fake_win32 = type("W", (), {"GetWindowText": staticmethod(lambda h: "Chrome"),
                                    "GetForegroundWindow": staticmethod(lambda: 1)})()
        with patch.dict("sys.modules", {"win32gui": fake_win32}), \
             patch("config.load_settings", return_value={"watch_enabled": True, "watch_quiet_start": 0, "watch_quiet_end": 1}), \
             patch("modules.voice_runtime.announce_active", return_value=True) as say:
            items = pc_autonomy_queue.watch_tick(_Runtime())
        self.assertEqual(len(items), 1)
        self.assertIn("Chrome", items[0]["text"])
        say.assert_called_once()

    def test_missing_library_is_silent(self):
        with patch.dict("sys.modules", {"win32gui": None}), \
             patch("config.load_settings", return_value={"watch_enabled": True, "watch_quiet_start": 0, "watch_quiet_end": 1}), \
             patch("modules.voice_runtime.announce_active", return_value=True) as say:
            self.assertEqual(pc_autonomy_queue.watch_tick(_Runtime()), [])
        say.assert_not_called()


if __name__ == "__main__":
    unittest.main()
