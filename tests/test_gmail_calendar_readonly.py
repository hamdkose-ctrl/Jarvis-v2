import unittest
from datetime import datetime, timezone

from modules import gmail_calendar_readonly as work


class FakeThreads:
    def get(self, **kwargs):
        return self
    def execute(self):
        return {"id": "t1", "messages": [
            {"id": "m1", "internalDate": "1", "payload": {"headers": [
                {"name": "From", "value": "a@example.com"}, {"name": "Subject", "value": "Plan"}
            ]}, "snippet": "İlk mesaj"},
            {"id": "m2", "internalDate": "2", "payload": {"headers": [
                {"name": "From", "value": "me@example.com"}, {"name": "Subject", "value": "Plan"}
            ]}, "snippet": "Son mesaj"},
        ]}


class FakeGmail:
    def users(self):
        return self
    def threads(self):
        return FakeThreads()


class GmailCalendarReadonlyTests(unittest.TestCase):
    def test_thread_reader_returns_bounded_metadata_and_snippets(self):
        result = work.read_thread(FakeGmail(), "t11")
        self.assertEqual(result["id"], "t11")
        self.assertEqual(result["messages"][1]["from"], "me@example.com")
        self.assertEqual(result["messages"][0]["snippet"], "İlk mesaj")

    def test_planning_suggestion_finds_available_window_without_writing_calendar(self):
        result = work.suggest_slot(
            datetime(2026, 10, 27, 9, tzinfo=timezone.utc),
            datetime(2026, 10, 27, 17, tzinfo=timezone.utc),
            [(datetime(2026, 10, 27, 10, tzinfo=timezone.utc), datetime(2026, 10, 27, 11, tzinfo=timezone.utc), "Toplantı")],
            minutes=60,
        )
        self.assertEqual(result["state"], "suggested")
        self.assertEqual(result["start"].hour, 9)
        self.assertIn("takvime eklemez", result["note"])

    def test_invalid_thread_or_event_range_is_rejected(self):
        with self.assertRaises(work.GmailCalendarReadonlyError):
            work.validate_thread_id("../t1")
        with self.assertRaises(work.GmailCalendarReadonlyError):
            work.suggest_slot(datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc), [], minutes=60)


if __name__ == "__main__":
    unittest.main()
