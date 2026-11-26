"""Hız freni bağlantısı: tavanın %90'ında bekler, ölçülmemiş modelde hiç beklemez.

Canlı ölçüm (26 Kasım): Gemini 3.5 Flash Lite tavanı 15 istek/dk, 250K token/dk;
22 Kasım 01:31'de 22 istek / 252.020 token ile 429 alınmıştı.
"""
import contextlib
import unittest
from unittest import mock

from modules import smart_router, usage_meter


@contextlib.contextmanager
def _no_sleep():
    with mock.patch.object(smart_router.time, "sleep") as sleep, \
         mock.patch.object(smart_router, "_check_request", lambda r: None):
        yield sleep


class Brake(unittest.TestCase):
    def setUp(self):
        usage_meter._RECENT.clear()

    def _spec(self, model="gemini-3.5-flash-lite"):
        return mock.Mock(model=model, provider="gemini")

    def test_no_wait_below_headroom(self):
        with _no_sleep() as sleep:
            waited = smart_router._respect_rate_limit(mock.Mock(), self._spec())
        self.assertEqual(waited, 0.0)
        self.assertFalse(sleep.called)

    def test_waits_when_requests_near_limit(self):
        for _ in range(14):
            usage_meter.note_recent("gemini-3.5-flash-lite", 100)
        with _no_sleep() as sleep:
            waited = smart_router._respect_rate_limit(mock.Mock(), self._spec())
        self.assertGreater(waited, 0)
        self.assertTrue(sleep.called)

    def test_waits_when_tokens_near_limit(self):
        usage_meter.note_recent("gemini-3.5-flash-lite", 240_000)
        with _no_sleep():
            self.assertGreater(smart_router._respect_rate_limit(mock.Mock(), self._spec()), 0)

    def test_unmeasured_model_never_waits(self):
        for _ in range(50):
            usage_meter.note_recent("unknown-model", 10 ** 7)
        with _no_sleep() as sleep:
            self.assertEqual(smart_router._respect_rate_limit(mock.Mock(), self._spec("unknown-model")), 0.0)
        self.assertFalse(sleep.called)

    def test_wait_is_bounded(self):
        usage_meter.note_recent("gemini-3.5-flash-lite", 999_999)
        with _no_sleep():
            waited = smart_router._respect_rate_limit(mock.Mock(), self._spec())
        self.assertLessEqual(waited, smart_router.MAX_BRAKE_SECONDS)


if __name__ == "__main__":
    unittest.main()
