import unittest

from modules.guidance_advisor import guide, requested


class GuidanceAdvisorTests(unittest.TestCase):
    def test_guidance_is_stepwise_and_practical(self):
        result = guide(
            "Bu işi nasıl yaparım, adım adım anlat.",
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

    def test_normal_question_is_not_forced_into_guidance(self):
        self.assertFalse(requested("Bugün hava nasıl?"))
        self.assertIsNone(guide("Bugün hava nasıl?", objective="x", steps=[]))


if __name__ == "__main__":
    unittest.main()
