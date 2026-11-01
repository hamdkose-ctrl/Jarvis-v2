import unittest

from modules.decision_advisor import analyze
from modules.brain_understanding import ADVISORY_ARGUMENT_KEY
from test_brain_pr8b_advisor_echo import semantic


class DecisionAdvisorTests(unittest.TestCase):
    def test_explicit_choice_produces_structured_analysis(self):
        result = analyze(
            "Evden mi ofisten mi çalışayım?",
            [
                {"name": "Evden", "pros": ["Esneklik"], "cons": ["Dikkat dağınıklığı"]},
                {"name": "Ofisten", "pros": ["Ekip erişimi"], "cons": ["Yol süresi"]},
            ],
            recommendation="Evden",
            rationale="Bugünkü odak ihtiyacı ve yol süresi birlikte değerlendirildi.",
            uncertainties=["Evdeki dikkat koşulları"],
        )
        self.assertEqual(result["schema"], "decision_analysis.v1")
        self.assertEqual(result["recommendation"]["option"], "Evden")
        self.assertEqual(result["uncertainties"], ["Evdeki dikkat koşulları"])

    def test_non_decision_request_is_not_forced_into_analysis(self):
        # canonical Understanding owns the choice; the advisor module no longer guesses.
        self.assertIsNone(semantic("Bugün hava nasıl?").arguments.get(ADVISORY_ARGUMENT_KEY))

    def test_invalid_recommendation_fails_closed(self):
        with self.assertRaises(ValueError):
            analyze("Hangisi?", [{"name": "A", "pros": [], "cons": []}], recommendation="B")


if __name__ == "__main__":
    unittest.main()
