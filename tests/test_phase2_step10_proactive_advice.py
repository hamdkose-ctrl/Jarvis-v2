import unittest

from modules.proactive_advisor import suggest


class ProactiveAdvisorTests(unittest.TestCase):
    def test_default_is_on_and_setting_turns_it_off(self):
        self.assertEqual(suggest("risk", "Yedek almayı düşün.", settings={})["kind"], "risk")
        self.assertIsNone(suggest("risk", "Yedek almayı düşün.", settings={"proactive_suggestions": False}))

    def test_enabled_returns_one_machine_readable_suggestion(self):
        result = suggest(
            "risk",
            "Bunu da düşünebilirsin: önce küçük bir yedek al.",
            settings={"proactive_suggestions": True},
            title="Yedek",
        )
        self.assertEqual(result["schema"], "proactive_suggestion.v1")
        self.assertEqual(result["kind"], "risk")
        self.assertEqual(result["title"], "Yedek")
        self.assertEqual(result["priority"], "low")

    def test_empty_or_unknown_kind_fails_closed(self):
        self.assertIsNone(suggest("unknown", "Bir öneri.", settings={"proactive_suggestions": True}))
        with self.assertRaises(ValueError):
            suggest("opportunity", "", settings={"proactive_suggestions": True})


if __name__ == "__main__":
    unittest.main()
