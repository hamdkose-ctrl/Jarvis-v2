"""Uyanıklık: gürültü süzme, sessiz saat, tekrar engeli, kapalı varsayılan."""
import unittest

from modules import awareness_watch as watch


class Noise(unittest.TestCase):
    def test_disabled_by_default(self):
        self.assertFalse(watch.enabled({}))

    def test_window_change_is_a_candidate(self):
        items = watch.candidates({"window": "Chrome", "previous_window": "Not Defteri"},
                                 seen=set(), hour=12)
        self.assertEqual(items[0]["kind"], "window")

    def test_same_window_is_not_a_candidate(self):
        items = watch.candidates({"window": "Chrome", "previous_window": "Chrome"},
                                 seen=set(), hour=12)
        self.assertEqual(items, [])

    def test_quiet_hours_silence_everything(self):
        self.assertEqual(watch.candidates({"unread_mail": 3}, seen=set(), hour=23), [])

    def test_seen_item_is_not_repeated(self):
        state = {"unread_mail": 2}
        first = watch.candidates(state, seen=set(), hour=12)
        seen = watch.mark_seen(first, set())
        self.assertEqual(watch.candidates(state, seen=seen, hour=12), [])

    def test_upcoming_event_is_noticed(self):
        items = watch.candidates({"next_event_minutes": 10}, seen=set(), hour=9)
        self.assertEqual(items[0]["kind"], "calendar")


if __name__ == "__main__":
    unittest.main()
