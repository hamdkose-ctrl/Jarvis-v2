import unittest
from datetime import datetime
from unittest.mock import patch

from modules import learning, wakeword
from modules.personalization import Profile


class V58RegressionTests(unittest.TestCase):

    def test_time_reminder_is_not_saved_as_rule(self):
        class FakeProfile:
            data = {"rules": []}
            def save(self):
                raise AssertionError("zamana bağlı hatırlatma kural olarak kaydedilmemeli")
        msg = learning.add_rule(FakeProfile(), "Pazartesi notlarımı o gün hatırlat")
        self.assertIn("hatırlatma", msg.casefold())
        self.assertEqual(FakeProfile.data["rules"], [])

    def test_all_day_event_notifies_on_its_day(self):
        p = Profile.__new__(Profile)
        p.data = {"events": [{"id": 1, "title": "Notlara bak", "when": "2026-10-05", "notified": False}]}
        p.save = lambda: None
        self.assertEqual(p._due_events(datetime(2026, 10, 5, 8, 59)), [])
        due = p._due_events(datetime(2026, 10, 5, 9, 1))
        self.assertEqual([x["title"] for x in due], ["Notlara bak"])
        self.assertEqual(p._due_events(datetime(2026, 10, 5, 10, 0)), [])

    def test_default_wake_sensitivity_is_more_tolerant(self):
        with patch("modules.wakeword.load_settings", return_value={}):
            self.assertLessEqual(wakeword.sensitivity_threshold(), 0.22)


if __name__ == "__main__":
    unittest.main()
