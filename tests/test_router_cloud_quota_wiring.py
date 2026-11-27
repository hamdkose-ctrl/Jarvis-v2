"""T3b: cloud candidates reserve against a verified policy; no policy means no local limit."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from modules import failure_policy, llm, router_quota as quota, smart_router as router

NOW = 1794300000.


def policy(**changes):
    row = dict(provider="gemini", model="g2",
               source_url="https://provider.example/rates",
               verified_at=NOW - 60, expires_at=NOW + 2 * 86400, rpm=5, rpd=9)
    row.update(changes)
    return row


class _FrozenTime:
    """Rezervasyon saatinin test anına çivilenmesi; gerçek saat kullanılmaz."""

    def time(self):
        return NOW


class CloudReserveWiringTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(router, "_STORE", self.directory))
        self.enterContext(patch.object(router, "_HEALTH", {}))
        self.enterContext(patch.object(quota, "POLICIES", {}))
        self.enterContext(patch.object(quota, "time", _FrozenTime()))
        self.enterContext(patch.object(llm.privacy, "mode", return_value="normal"))
        self.spec = router.ModelSpec("gemini", "g2")
        self.request = router.ModelRequest(owner="alice", profile="conversation",
                                          max_output_tokens=128, token_budget=900)
        self.plan = router.RoutePlan((self.spec,), (), 1)

    def run_router(self, adapter=None, *, request=None):
        adapter = adapter or (lambda spec: "ok")
        with patch.object(router, "plan", return_value=self.plan):
            return router.run_request(request or self.request, adapter)

    def test_cloud_candidate_without_connection_reserves_before_send(self):
        with patch.object(quota, "reserve", return_value=False) as reserve:
            self.assertEqual(self.run_router().text, "ok")
        args, kwargs = reserve.call_args
        self.assertEqual(args, ("alice", "gemini", "g2"))
        self.assertEqual(kwargs["directory"], self.directory)
        self.assertEqual(kwargs["token_budget"], 900)
        self.assertTrue(kwargs["attempt_id"].endswith(":1"))   # istek kimliği + deneme no

    def reserved_rows(self):
        path = self.directory / "atomic_requests.sqlite3"
        if not path.exists():
            return []
        with closing(sqlite3.connect(path)) as db:
            try:
                return db.execute("SELECT provider, model FROM requests").fetchall()
            except sqlite3.OperationalError:
                return []

    def test_empty_policies_apply_no_limit_and_book_nothing(self):
        # Davranış kanıtı: doğrulanmış satır yokken gönderim aynen yapılır ve rezervasyon
        # SATIRI hiç yazılmaz (reserve limitlerden ÖNCE erken False döner).
        self.assertEqual(self.run_router().text, "ok")
        self.assertEqual(self.reserved_rows(), [])

    def test_verified_policy_books_the_send_then_skips_when_exhausted(self):
        quota.POLICIES[("gemini", "g2")] = policy(rpm=1, rpd=2)
        response = router.AdapterResponse("ok", finish_reason="stop",
                                          usage={"input_tokens": 2, "output_tokens": 3,
                                                 "total_tokens": 5})
        self.assertEqual(self.run_router(lambda spec: response).text, "ok")
        self.assertEqual(self.reserved_rows(), [("gemini", "g2")])
        with closing(sqlite3.connect(self.directory / "atomic_requests.sqlite3")) as db:
            reserved, actual = db.execute(
                "SELECT token_units, actual_tokens FROM requests").fetchone()
        # Kanıt: gerçek sağlayıcı toplamı (5) ölçülmüş üst sınırın (900) altında kaldı;
        # reconcile rezervasyonu gerçek toplama indirdi.
        self.assertLessEqual(actual, self.request.token_budget)
        self.assertEqual((reserved, actual), (5, 5))
        calls = []
        with self.assertRaises(failure_policy.ProviderExhaustedError) as caught:
            self.run_router(lambda spec: calls.append(spec))
        self.assertEqual(calls, [])          # dolmuş rezervasyon HTTP denemez
        self.assertIn("doldu", str(caught.exception))

    def test_stale_verification_means_no_policy_not_a_block(self):
        # Süresi geçmiş doğrulama "yerel politika yok" demektir: 31 gün sonra tüm
        # bulut trafiğini kesen sert durdurma yok; sağlayıcının kendi 429/413 sınırı konuşur.
        quota.POLICIES[("gemini", "g2")] = policy(expires_at=NOW - 1)
        self.assertEqual(self.run_router().text, "ok")
        self.assertEqual(self.reserved_rows(), [])

    def test_broken_row_shape_still_blocks_the_send(self):
        quota.POLICIES[("gemini", "g2")] = policy(model="other")
        calls = []
        with self.assertRaises(failure_policy.ProviderExhaustedError) as caught:
            self.run_router(lambda spec: calls.append(spec))
        self.assertEqual(calls, [])
        self.assertIn("kimliği uyuşmuyor", str(caught.exception))


class TokenUpperBoundTests(unittest.TestCase):
    def captured_request(self, *, prompt, system, max_tokens, history=None):
        seen = {}

        def fake(request, adapter, **kwargs):
            seen["request"] = request
            return type("Result", (), {"text": "ok"})()

        with patch.object(llm, "current_user", return_value="alice"), \
             patch.object(llm.requests_state, "request_identity", return_value="rid"), \
             patch.object(llm.requests_state, "model_work_class", return_value=None), \
             patch.object(router, "run_request", side_effect=fake):
            llm._send(prompt, system, max_tokens, history)
        return seen["request"]

    def test_send_passes_a_measured_upper_bound_not_an_estimate(self):
        prompt, system, max_tokens = "Türkçe metin çok daha uzun bir gövde", "sistem", 256
        request = self.captured_request(prompt=prompt, system=system, max_tokens=max_tokens)
        self.assertEqual(request.token_budget,
                         llm.token_upper_bound(prompt, system, max_tokens))
        # Bayt sayılır, karakter değil: Türkçe harfler UTF-8 de birden çok bayt kaplar.
        self.assertGreater(request.token_budget, len(prompt) + max_tokens)
        self.assertGreaterEqual(request.token_budget, len(prompt.encode()) + max_tokens)
        self.assertGreaterEqual(request.token_budget, max_tokens)

    def test_upper_bound_covers_every_message_exactly_once(self):
        def turn(role, text):
            return type("Turn", (), {"role": role,
                                     "parts": [type("Part", (), {"text": text})()]})()
        history = [turn("user", "önceki soru"), turn("model", "önceki cevap")]
        text = "soru" + "sistem" + "önceki soru" + "önceki cevap"
        bound = llm.token_upper_bound("soru", "sistem", 64, history)
        # Dört mesaj (2 geçmiş + sistem + istem) tam bir kez sayılır; geçmiş düşerse
        # sınır 32 bayt eksik kalır ve bu eşitlik kırılır.
        self.assertEqual(bound, len(text.encode()) + 64
                         + 4 * llm.MESSAGE_OVERHEAD_BYTES)


if __name__ == "__main__":
    unittest.main()
