"""Uyanıklığın gerçek besleyicileri: okunmamış mail ve yaklaşan takvim."""
import datetime
import unittest
from unittest import mock

from modules import pc_autonomy_queue


class Sources(unittest.TestCase):
    def test_mail_and_calendar_feed_the_state(self):
        soon = datetime.datetime.now() + datetime.timedelta(minutes=10)
        with mock.patch("modules.google_api.connected", return_value=True), \
             mock.patch("modules.google_api.unread_count", return_value=3), \
             mock.patch("modules.google_api.day_events", return_value=[(soon, "toplantı")]):
            state = pc_autonomy_queue._inbox_and_calendar()
        self.assertEqual(state["unread_mail"], 3)
        self.assertLessEqual(state["next_event_minutes"], 10)

    def test_not_connected_returns_empty(self):
        with mock.patch("modules.google_api.connected", return_value=False):
            self.assertEqual(pc_autonomy_queue._inbox_and_calendar(), {})

    def test_failure_is_recorded_not_raised(self):
        with mock.patch("modules.google_api.connected", side_effect=RuntimeError("boom")):
            self.assertEqual(pc_autonomy_queue._inbox_and_calendar(), {})

    def test_watch_tick_uses_the_sources(self):
        pc_autonomy_queue._SEEN.clear()
        soon = datetime.datetime.now() + datetime.timedelta(minutes=5)
        with mock.patch("config.load_settings", return_value={"watch_enabled": True}), \
             mock.patch("modules.pc_autonomy_queue.foreground_window", return_value="Chrome"), \
             mock.patch("modules.google_api.connected", return_value=True), \
             mock.patch("modules.google_api.unread_count", return_value=2), \
             mock.patch("modules.google_api.day_events", return_value=[(soon, "toplantı")]):
            items = pc_autonomy_queue.watch_tick(None)
        kinds = {item["kind"] for item in items} if items else set()
        self.assertTrue(kinds & {"mail", "calendar", "window"})


if __name__ == "__main__":
    unittest.main()
