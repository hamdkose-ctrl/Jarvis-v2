"""Kisa komutlar: 'youtube ac', 'maili ac', 'ilk mail ne' dogru yetenege baglanir."""
import unittest

from modules import capability_brain, fast_commands


class ShortCommands(unittest.TestCase):
    def test_site_open(self):
        for text, site in (("youtube aç", "youtube.com"), ("maili aç", "gmail.com"),
                           ("müzik aç", "music.youtube.com")):
            result = capability_brain.resolve(text)
            self.assertEqual((result["status"], result["capability"]), ("ok", "pc_open_site"))
            self.assertEqual(result["slots"]["text"], site)

    def test_screen_read(self):
        result = capability_brain.resolve("ilk mail ne")
        self.assertEqual((result["status"], result["capability"]), ("ok", "screen_read_text"))

    def test_short_file_list(self):
        result = capability_brain.resolve("indirilenler ne var")
        self.assertEqual(result["capability"], "file_list")
        self.assertIn("Downloads", result["slots"]["path"])

    def test_saved_time_question_is_core(self):
        self.assertEqual(fast_commands.resolve("saat kaç")[0], "fast_time")


if __name__ == "__main__":
    unittest.main()
