"""Günlük kota ile dakikalık hız aşımı ayrılır (canlı 26 Kasım bulgusu).

Gemini'nin 429 gövdesi "You exceeded your current quota..." diyor ama "daily" demiyordu;
bu yüzden günlük kota dakikalık hız sanılıp hemen yeniden deneniyordu (13 hatanın 10'u).
"""
import unittest

from modules import failure_policy


class Classify(unittest.TestCase):
    def test_gemini_quota_body_is_daily(self):
        body = ("429 RESOURCE_EXHAUSTED. You exceeded your current quota, please check your "
                "plan and billing details.")
        self.assertTrue(failure_policy.quota_exhausted_text(body))

    def test_free_tier_mention_is_daily(self):
        self.assertTrue(failure_policy.quota_exhausted_text("quotaId: GenerateRequestsPerDay free_tier"))

    def test_plain_rate_limit_is_not_daily(self):
        self.assertFalse(failure_policy.quota_exhausted_text("HTTP 429 Too Many Requests"))
        self.assertFalse(failure_policy.quota_exhausted_text("slow down"))

    def test_existing_patterns_still_work(self):
        self.assertTrue(failure_policy.quota_exhausted_text("insufficient_quota"))
        self.assertTrue(failure_policy.quota_exhausted_text("günlük limit doldu"))


if __name__ == "__main__":
    unittest.main()
