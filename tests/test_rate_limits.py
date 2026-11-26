"""Hız freni sayıları: yalnız ölçülmüş tavanlarla, uydurma modelde fren kapalı."""
import unittest

from modules import rate_limits


class Limits(unittest.TestCase):
    def test_measured_limits_are_known(self):
        self.assertEqual(rate_limits.limit_for("gemini-3.5-flash-lite"), (15, 250_000))
        self.assertEqual(rate_limits.limit_for("gemini-2.5-flash-tts"), (3, 10_000))

    def test_unknown_model_has_no_brake(self):
        self.assertIsNone(rate_limits.limit_for("gemini-9.9-unknown"))
        self.assertFalse(rate_limits.should_wait(999, 99_999_999, "gemini-9.9-unknown"))

    def test_headroom_triggers_wait(self):
        self.assertFalse(rate_limits.should_wait(5, 100_000, "gemini-3.5-flash-lite"))
        self.assertTrue(rate_limits.should_wait(14, 0, "gemini-3.5-flash-lite"))
        self.assertTrue(rate_limits.should_wait(0, 230_000, "gemini-3.5-flash-lite"))

    def test_observed_peak_would_have_waited(self):
        # 22 Kasım 01:31: 22 istek / 252.020 token — o dakika 429 alınmıştı.
        self.assertTrue(rate_limits.should_wait(22, 252_020, "gemini-3.5-flash-lite"))


if __name__ == "__main__":
    unittest.main()
