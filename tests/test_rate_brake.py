"""Hız freni: ölçülmüş tavanın %90'ında bekler, ölçülmemiş modelde hiç beklemez.

Ölçüm (26 Kasım, kullanıcının AI Studio sayfası): Gemini 3.5 Flash Lite 15 istek/dk,
250K token/dk. 22 Kasım 01:31'de 22 istek / 252.020 token ile 429 alınmıştı.
"""
import unittest
from unittest import mock

from modules import llm, usage_meter


class Brake(unittest.TestCase):
    def setUp(self):
        usage_meter._RECENT.clear()

    def _spec(self, model="gemini-3.5-flash-lite"):
        return mock.Mock(model=model, provider="gemini")

    def _brake(self, model="gemini-3.5-flash-lite"):
        waited = []
        with mock.patch.object(llm.requests_state, "check", lambda: None):
            result = llm.apply_rate_brake(self._spec(model), sleeper=waited.append)
        return result, waited

    def test_no_wait_below_headroom(self):
        waited, sleeps = self._brake()
        self.assertEqual(waited, 0.0)
        self.assertEqual(sleeps, [])

    def test_waits_when_requests_near_limit(self):
        for _ in range(14):
            usage_meter.note_recent("gemini-3.5-flash-lite", 100)
        waited, sleeps = self._brake()
        self.assertGreater(waited, 0)
        self.assertTrue(sleeps)

    def test_waits_when_tokens_near_limit(self):
        usage_meter.note_recent("gemini-3.5-flash-lite", 240_000)
        waited, _ = self._brake()
        self.assertGreater(waited, 0)

    def test_unmeasured_model_never_waits(self):
        for _ in range(50):
            usage_meter.note_recent("unknown-model", 10 ** 7)
        waited, sleeps = self._brake("unknown-model")
        self.assertEqual(waited, 0.0)
        self.assertEqual(sleeps, [])

    def test_wait_is_bounded(self):
        usage_meter.note_recent("gemini-3.5-flash-lite", 999_999)
        waited, _ = self._brake()
        self.assertLessEqual(waited, llm.BRAKE_MAX_SECONDS)


if __name__ == "__main__":
    unittest.main()
