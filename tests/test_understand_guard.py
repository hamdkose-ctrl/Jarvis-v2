"""Anlam bekçisi: yanlış iş yapmama + özyineleme koruması."""
import unittest

from modules import capability_brain, fast_commands


class NoFalseAction(unittest.TestCase):
    def test_poem_request_is_not_a_pc_command(self):
        self.assertEqual(capability_brain.resolve("bana bir şiir yaz")["status"], "uncertain")

    def test_reminder_without_pc_step_is_not_scheduled(self):
        self.assertEqual(capability_brain.resolve("yarınki toplantıyı hatırlat")["status"], "uncertain")

    def test_real_typing_command_still_works(self):
        result = capability_brain.resolve("chrome a youtube yaz")
        self.assertEqual((result["status"], result["capability"]), ("ok", "pc_type"))


class RecursionGuard(unittest.TestCase):
    def test_time_phrase_does_not_loop(self):
        for text in ("5 dakika sonra chrome da enter",
                     "yarın 09:00'da not defterinde kaydet düğmesine bas",
                     "bugün saat 14:00 toplantı"):
            fast_commands.resolve(text)          # RecursionError vermemeli


if __name__ == "__main__":
    unittest.main()
