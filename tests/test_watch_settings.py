"""Uyanıklık ayarı: gerçek sahip `config.load_settings`; profil nesnesinde alan yok."""
import unittest
from unittest.mock import patch

from modules import pc_autonomy_queue


class _Runtime:
    log = type("L", (), {"info": staticmethod(lambda *a, **k: None)})()


class Settings(unittest.TestCase):
    def setUp(self):
        pc_autonomy_queue._SEEN.clear()

    def test_real_setting_opens_the_watch(self):
        with patch("config.load_settings", return_value={"watch_enabled": True, "watch_quiet_start": 0, "watch_quiet_end": 1}), \
             patch("modules.pc_autonomy_queue.foreground_window", return_value="Chrome"), \
             patch("modules.voice_runtime.announce_active", return_value=True) as say:
            items = pc_autonomy_queue.watch_tick(_Runtime())
        self.assertEqual(len(items), 1)
        say.assert_called_once()

    def test_missing_key_keeps_it_closed(self):
        with patch("config.load_settings", return_value={}), \
             patch("modules.voice_runtime.announce_active", return_value=True) as say:
            self.assertEqual(pc_autonomy_queue.watch_tick(_Runtime()), [])
        say.assert_not_called()

    def test_settings_failure_keeps_it_closed(self):
        with patch("config.load_settings", side_effect=OSError("yok")), \
             patch("modules.voice_runtime.announce_active", return_value=True) as say:
            self.assertEqual(pc_autonomy_queue.watch_tick(_Runtime()), [])
        say.assert_not_called()


if __name__ == "__main__":
    unittest.main()
