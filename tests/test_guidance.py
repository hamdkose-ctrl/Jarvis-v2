import unittest

from modules.guidance import build


class GuidanceTests(unittest.TestCase):
    def test_guidance_is_stepwise_and_explains_choice_and_risks(self):
        result = build(
            "düzenli spor",
            ["takvime koy", "küçük başla"],
            options=[{"name": "sabah", "why": "güne erken başlar"}],
            risks=["aşırı yüklenme"],
        )
        self.assertEqual(result["goal"], "düzenli spor")
        self.assertEqual(result["steps"][0]["order"], 1)
        self.assertEqual(result["selected_option"]["name"], "sabah")
        self.assertEqual(result["selected_option"]["why"], "güne erken başlar")
        self.assertTrue(result["risks"][0]["mitigation"])

    def test_guidance_requires_steps(self):
        with self.assertRaises(ValueError):
            build("hedef", [])


if __name__ == "__main__":
    unittest.main()
