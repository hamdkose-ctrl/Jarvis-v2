"""Hız freni **kalan bütçeyle** sınırlı (B-01 / T0).

Canlı kusur: fren yalnız iptali denetliyordu. `check_ready_connection` bütçesi 12 sn iken
fren 20 sn'ye kadar bekleyebiliyor, istek kendi freniyle `LocalDeadline`'a düşüyordu.
Doğru davranış: bütçe yetmiyorsa **hiç beklememek**.
"""
import time
import unittest
from unittest import mock

from modules import llm, usage_meter


class Brake(unittest.TestCase):
    def setUp(self):
        usage_meter._RECENT.clear()

    def _spec(self, model="gemini-3.5-flash-lite"):
        return mock.Mock(model=model, provider="gemini")

    def _brake(self, model="gemini-3.5-flash-lite", deadline=None, sleeper=None):
        slept = []
        with mock.patch.object(llm.requests_state, "check", lambda: None):
            waited = llm.apply_rate_brake(self._spec(model), sleeper=sleeper or slept.append,
                                          deadline=deadline)
        return waited, slept

    def _saturate(self):
        usage_meter.note_recent("gemini-3.5-flash-lite", 999_999)

    # --- davranış (önceki testler) -------------------------------------------------
    def test_no_wait_below_headroom(self):
        waited, slept = self._brake()
        self.assertEqual(waited, 0.0)
        self.assertEqual(slept, [])

    def test_waits_when_requests_near_limit(self):
        for _ in range(14):
            usage_meter.note_recent("gemini-3.5-flash-lite", 100)
        waited, slept = self._brake()
        self.assertGreater(waited, 0)
        self.assertTrue(slept)

    def test_unmeasured_model_never_waits(self):
        for _ in range(50):
            usage_meter.note_recent("unknown-model", 10 ** 7)
        waited, slept = self._brake("unknown-model")
        self.assertEqual(waited, 0.0)
        self.assertEqual(slept, [])

    # --- bütçe sınırı (T0) ---------------------------------------------------------
    def test_tight_budget_never_waits(self):
        self._saturate()
        deadline = time.monotonic() + 3
        waited, slept = self._brake(deadline=deadline)
        self.assertEqual(waited, 0.0)
        self.assertEqual(slept, [])

    def test_generous_budget_is_capped_at_max(self):
        self._saturate()
        deadline = time.monotonic() + 60
        waited, _ = self._brake(deadline=deadline)
        self.assertLessEqual(waited, llm.BRAKE_MAX_SECONDS)

    def test_budget_shorter_than_max_limits_the_wait(self):
        self._saturate()
        deadline = time.monotonic() + 6
        waited, _ = self._brake(deadline=deadline)
        self.assertLessEqual(waited, 6 - llm.BRAKE_PAY_SECONDS)

    def test_cancel_stops_mid_wait(self):
        self._saturate()
        calls = {"n": 0}

        def check():
            calls["n"] += 1
            if calls["n"] > 1:
                raise llm.requests_state.Cancelled()

        with mock.patch.object(llm.requests_state, "check", check):
            with self.assertRaises(llm.requests_state.Cancelled):
                llm.apply_rate_brake(self._spec(), sleeper=lambda seconds: None,
                                     deadline=time.monotonic() + 60)
        self.assertGreater(calls["n"], 1)

    def test_state_is_test_local(self):
        usage_meter.note_recent("a", 100)
        self.assertEqual(usage_meter.recent_usage("a"), (1, 100))
        usage_meter._RECENT.clear()
        self.assertEqual(usage_meter.recent_usage("a"), (0, 0))


if __name__ == "__main__":
    unittest.main()
