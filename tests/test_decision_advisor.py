import unittest

from modules.decision_advisor import analyze


class DecisionAdvisorTests(unittest.TestCase):
    def test_returns_pros_cons_and_reasoned_recommendation(self):
        result = analyze([
            {"name": "A", "pros": ["ucuz", "hızlı"], "cons": ["sınırlı"]},
            {"name": "B", "pros": ["güçlü"], "cons": ["pahalı", "yavaş"]},
        ])
        self.assertEqual(result["recommendation"], "A")
        self.assertEqual(len(result["options"]), 2)
        self.assertIn("gerekçe", result["reason"])

    def test_rejects_empty_or_incomplete_options(self):
        with self.assertRaises(ValueError):
            analyze([])
        with self.assertRaises(ValueError):
            analyze([{"name": "A", "pros": [], "cons": []}])
