"""Zamanlı iş: zamanı doğru çıkar, belirsizse tahmin etme."""
import time
import unittest
from unittest.mock import patch

from modules import autonomy_when


class Parsing(unittest.TestCase):
    def test_tomorrow_with_clock(self):
        result = autonomy_when.parse_when("yarın 09:00'da not defterinde kaydet düğmesine bas")
        stamp = time.localtime(result["when"])
        self.assertEqual((stamp.tm_hour, stamp.tm_min), (9, 0))
        self.assertEqual(result["rest"], "not defterinde kaydet düğmesine bas")

    def test_relative_minutes(self):
        now = time.time()
        result = autonomy_when.parse_when("5 dakika sonra chrome da enter", now=now)
        self.assertAlmostEqual(result["when"] - now, 300, delta=2)

    def test_tomorrow_without_clock_defaults_and_says_so(self):
        result = autonomy_when.parse_when("yarın not defterinde kaydet düğmesine bas")
        self.assertEqual(time.localtime(result["when"]).tm_hour, autonomy_when.DEFAULT_HOUR)
        self.assertIn("kabul ettim", result["note"])

    def test_missing_time_is_not_guessed(self):
        result = autonomy_when.parse_when("not defterinde kaydet düğmesine bas")
        self.assertIsNone(result["when"])
        self.assertIn("zaman bulamadım", result["note"])

    def test_invalid_clock_is_refused(self):
        self.assertIsNone(autonomy_when.parse_when("saat 25:00 not defterinde kaydet düğmesine bas")["when"])

    def test_describe_is_human_readable(self):
        self.assertRegex(autonomy_when.describe(time.time()), r"\d{2}\.\d{2} \d{2}:\d{2}")


class Routing(unittest.TestCase):
    def test_time_led_pc_command_goes_to_schedule(self):
        from modules import fast_commands
        self.assertEqual(fast_commands.resolve("yarın 09:00 da not defterinde kaydet düğmesine bas")[0],
                         "autonomy_schedule")

    def test_plain_commands_are_not_affected(self):
        from modules import fast_commands
        self.assertEqual(fast_commands.resolve("ekranda ne var")[0], "screen_summary")


if __name__ == "__main__":
    unittest.main()
