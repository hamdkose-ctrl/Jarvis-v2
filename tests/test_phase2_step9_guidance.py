import unittest

from modules.brain_understanding import ADVISORY_ARGUMENT_KEY
from modules.guidance_advisor import guide
from test_brain_pr8b_advisor_echo import semantic


class GuidanceAdvisorTests(unittest.TestCase):
    def test_guidance_is_stepwise_and_practical(self):
        result = guide(
            objective="İlk sürümü güvenli biçimde hazırlamak",
            steps=[
                {
                    "action": "Kapsamı yaz",
                    "why": "Belirsizliği azaltır",
                    "risks": ["Kapsamın büyümesi"],
                    "watchouts": ["Tek hedef seç"],
                },
                {
                    "action": "Küçük test ekle",
                    "why": "Davranışı ölçer",
                    "risks": ["Testin eksik kalması"],
                    "watchouts": ["Başarısız testi kaydet"],
                },
            ],
        )
        self.assertEqual(result["schema"], "guidance.v1")
        self.assertEqual(result["steps"][0]["order"], 1)
        self.assertIn("why", result["steps"][1])

    def test_normal_question_has_no_canonical_guidance_semantics(self):
        # canonical Understanding owns the choice; the advisor module no longer guesses.
        self.assertIsNone(semantic("Bugün hava nasıl?").arguments.get(ADVISORY_ARGUMENT_KEY))


if __name__ == "__main__":
    unittest.main()
