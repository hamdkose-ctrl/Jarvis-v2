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


class EmptyForeground(unittest.TestCase):
    """Görev çubuğu/Shell_Flyout gibi başlıksız pencereler aday üretmemeli."""

    def test_empty_titles_fall_back_to_owner(self):
        class Fake:
            @staticmethod
            def GetForegroundWindow():
                return 5

            @staticmethod
            def GetWindowText(handle):
                return "Hesap Makinesi" if handle == 9 else ""

            @staticmethod
            def GetAncestor(handle, flag):
                return 0

            @staticmethod
            def GetWindow(handle, flag):
                return 9

        with patch.dict("sys.modules", {"win32gui": Fake}):
            self.assertEqual(pc_autonomy_queue.foreground_window(), "Hesap Makinesi")
