import unittest

from modules.critique_advisor import critique, requested


class HonestCritiqueTests(unittest.TestCase):
    def test_critique_has_reasoned_weak_point(self):
        result = critique(
            "Bu planı dürüstçe eleştir.",
            weak_point="Buradaki zayıf nokta şu: kapsam çok geniş.",
            because="Çünkü ölçülebilir ilk teslim sınırı tanımlanmamış.",
            impact="Bu durum ilerlemeyi takip etmeyi zorlaştırabilir.",
            next_step="İlk teslimi tek bir doğrulanabilir hedefle sınırla.",
        )
        self.assertEqual(result["schema"], "critique.v1")
        self.assertIn("Buradaki zayıf nokta şu", result["weak_point"])
        self.assertTrue(result["because"])

    def test_unrelated_request_is_not_turned_into_critique(self):
        self.assertFalse(requested("Bugün hava nasıl?"))
        self.assertIsNone(critique("Bugün hava nasıl?", weak_point="x", because="y"))

    def test_unsafe_style_is_rejected(self):
        with self.assertRaises(ValueError):
            critique("Bunu eleştir.", weak_point="Sen aptalsın.", because="Çünkü öyle.", impact="Kesinlikle başarısız olacaksın.")


if __name__ == "__main__":
    unittest.main()
