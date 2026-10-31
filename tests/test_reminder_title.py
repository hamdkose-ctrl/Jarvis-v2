"""Hatırlatma başlığı: kaldırılan saat ekinden ("14:30'da") kalan tek başına kesme işareti başlığa girmez."""
import unittest
from datetime import datetime

from modules import reminder_parse
from test_brain_b3c2 import Pipeline


class TitleParserTests(unittest.TestCase):
    NOW = datetime(2026, 10, 31, 12, 0)

    def title(self, text):
        return reminder_parse.parse(text, self.NOW)["title"]

    def test_time_suffix_leaves_no_stray_apostrophe(self):
        for text, expected in (
            ("cuma günü 14:30'da dişçiyi hatırlat", "dişçiyi"),
            ("15:30'da annemi aramayı hatırlat", "annemi aramayı"),
            ("dişçiyi cuma 14:30'da hatırlat", "dişçiyi"),
            ("yarın 10'da toplantıyı hatırlat", "toplantıyı"),
            ("cuma günü 14:30’da dişçiyi hatırlat", "dişçiyi"),
        ):
            self.assertEqual(self.title(text), expected, text)

    def test_apostrophes_inside_words_are_kept(self):
        self.assertEqual(self.title("yarın 10'da Ahmet'e mesaj atmayı hatırlat"), "ahmet'e mesaj atmayı")


class SavedEventTests(Pipeline):
    def test_saved_event_title_is_clean_through_brain_and_legacy_planner(self):
        text = "cuma günü 14:30'da dişçiyi hatırlat"
        entry, out, feedback, handle = self.through_brain(text)
        self.assertEqual([e["title"] for e in self.ctx.profile.data["events"]], ["dişçiyi"])
        self.ctx.profile.data["events"] = []
        self.ctx._planner_command(text, self.ctx._tr_lower(text))
        self.assertEqual([e["title"] for e in self.ctx.profile.data["events"]], ["dişçiyi"])


if __name__ == "__main__":
    unittest.main()
