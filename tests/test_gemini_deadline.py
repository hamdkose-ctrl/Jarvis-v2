"""Gemini isteği 10 sn'den kısa deadline ile gönderilmez (canlı 400 hatası)."""
import unittest
from unittest import mock

from modules import llm


class Deadline(unittest.TestCase):
    def _opts(self, remaining):
        with mock.patch.object(llm.requests_state, "budget_remaining", return_value=remaining):
            return llm._gemini_request_http_options()

    def test_short_budget_omits_timeout(self):
        # Google: "Manually set deadline 3s is too short. Minimum allowed deadline is 10s."
        self.assertNotIn("timeout", self._opts(3))
        self.assertNotIn("timeout", self._opts(9))

    def test_enough_budget_sets_timeout(self):
        self.assertEqual(self._opts(30)["timeout"], 30_000)
        self.assertEqual(self._opts(None)["timeout"], 45_000)


if __name__ == "__main__":
    unittest.main()
