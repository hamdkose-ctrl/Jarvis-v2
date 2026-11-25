"""Yetenek beyni: serbest cümle → yetenek; emin değilse iş yapmaz."""
import unittest
from unittest.mock import patch

from modules import capability_brain as brain


class Mapping(unittest.TestCase):
    def test_pattern_phrases_still_win(self):
        result = brain.resolve("chrome da adres alanına youtube yaz")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["via"], "pattern")

    def test_free_phrasing_maps_to_typing(self):
        result = brain.resolve("chrome a youtube yaz")
        self.assertEqual((result["status"], result["capability"]), ("ok", "pc_type"))
        self.assertEqual(result["slots"]["text"], "youtube")
        self.assertEqual(result["slots"]["window"], "chrome")

    def test_result_click_is_recognised(self):
        result = brain.resolve("ilk sonuca bas")
        self.assertEqual(result["capability"], "pc_click_result")

    def test_confirm_is_recognised(self):
        self.assertEqual(brain.resolve("onayliyorum")["capability"], "pc_confirm")

    def test_navigation_without_window_asks(self):
        result = brain.resolve("youtube a git")
        self.assertEqual(result["status"], "need")
        self.assertEqual(result["missing"], ["window"])

    def test_unrelated_sentence_is_not_forced(self):
        result = brain.resolve("dün akşam ne yediğimi hatırlamıyorum")
        self.assertEqual(result["status"], "uncertain")
        self.assertIsNone(result["capability"])


class Slots(unittest.TestCase):
    def test_folder_word_becomes_real_path(self):
        result = brain.resolve("indirilenler klasöründe ne var")
        self.assertEqual(result["capability"], "file_list")
        self.assertIn("Downloads", result["slots"]["path"])

    def test_file_is_found_only_when_unambiguous(self):
        with patch.object(brain, "guess_path", return_value="/tmp/tek.txt"):
            result = brain.resolve("şu dosyayı oku")
        self.assertEqual(result["capability"], "file_read")
        self.assertEqual(result["slots"]["path"], "/tmp/tek.txt")

    def test_ambiguous_file_asks(self):
        with patch.object(brain, "guess_path", return_value=""):
            result = brain.resolve("gece planı dosyasını oku")
        self.assertEqual(result["status"], "need")
        self.assertEqual(result["missing"], ["path"])

    def test_type_strips_filler_words(self):
        result = brain.resolve("chrome a hava durumu yaz")
        self.assertEqual(result["slots"]["text"], "hava durumu")


if __name__ == "__main__":
    unittest.main()
