import unittest

from modules.critique_advisor import critique
from modules.brain_understanding import ADVISORY_ARGUMENT_KEY
from test_brain_pr8b_advisor_echo import semantic


class HonestCritiqueTests(unittest.TestCase):
    def test_critique_has_reasoned_weak_point(self):
        result = critique(
            weak_point="Buradaki zayıf nokta şu: kapsam çok geniş.",
            because="Çünkü ölçülebilir ilk teslim sınırı tanımlanmamış.",
            impact="Bu durum ilerlemeyi takip etmeyi zorlaştırabilir.",
            next_step="İlk teslimi tek bir doğrulanabilir hedefle sınırla.",
        )
        self.assertEqual(result["schema"], "critique.v1")
        self.assertIn("Buradaki zayıf nokta şu", result["weak_point"])
        self.assertTrue(result["because"])

    def test_unrelated_request_has_no_canonical_critique_semantics(self):
        # canonical Understanding owns the choice; the advisor module no longer guesses.
        self.assertIsNone(semantic("Bugün hava nasıl?").arguments.get(ADVISORY_ARGUMENT_KEY))

    def test_unsafe_style_is_rejected(self):
        with self.assertRaises(ValueError):
            critique(weak_point="Sen aptalsın.", because="Çünkü öyle.", impact="Kesinlikle başarısız olacaksın.")


if __name__ == "__main__":
    unittest.main()
