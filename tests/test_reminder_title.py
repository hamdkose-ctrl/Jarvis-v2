"""PR #481 regression: saat eki kaldırılınca tek başına kalan kesme işareti başlığa girmemeli."""
import logging
import unittest
from datetime import datetime

from modules import main_planner, reminder_parse
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
            with self.subTest(text=text):
                self.assertEqual(self.title(text), expected)

    def test_apostrophes_inside_words_are_kept(self):
        self.assertEqual(self.title("yarın 10'da Ahmet'e mesaj atmayı hatırlat"), "ahmet'e mesaj atmayı")


class SavedEventTests(Pipeline):
    def setUp(self):
        root = logging.getLogger()
        before = root.handlers[:]
        super().setUp()
        created = [handler for handler in root.handlers if handler not in before]

        def close_created_handlers():
            for handler in created:
                if handler in root.handlers:
                    root.removeHandler(handler)
                handler.close()

        # Pipeline's TemporaryDirectory cleanup is older, so this LIFO cleanup closes
        # Windows file handles before the temp directory is removed.
        self.addCleanup(close_created_handlers)

    def test_saved_event_title_is_clean_through_brain_and_typed_reminder_core(self):
        text = "cuma günü 14:30'da dişçiyi hatırlat"
        self.through_brain(text)
        self.assertEqual([e["title"] for e in self.ctx.profile.data["events"]], ["dişçiyi"])

        self.ctx.profile.data["events"] = []
        typed = reminder_parse.parse(text, datetime(2026, 10, 31, 12, 0))
        self.assertEqual(typed["title"], "dişçiyi")
        main_planner.reminder_core(self.ctx, typed, text, self.ctx._tr_lower(text))
        self.assertEqual([e["title"] for e in self.ctx.profile.data["events"]], ["dişçiyi"])
        self.assertFalse(hasattr(self.ctx, "_planner_command"))


if __name__ == "__main__":
    unittest.main()
