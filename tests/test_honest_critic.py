import unittest

from modules.honest_critic import critique


class HonestCriticTests(unittest.TestCase):
    def test_critique_is_direct_respectful_and_structured(self):
        result = critique("iş planı", ["hedef ölçülebilir değil"], strengths=["motivasyon var"])
        self.assertEqual(result["topic"], "iş planı")
        self.assertTrue(result["points"][0]["text"].startswith("Buradaki zayıf nokta şu çünkü"))
        self.assertEqual(result["tone"], "dürüst ve saygılı")

    def test_critique_requires_weaknesses(self):
        with self.assertRaises(ValueError):
            critique("konu", [])


if __name__ == "__main__":
    unittest.main()
