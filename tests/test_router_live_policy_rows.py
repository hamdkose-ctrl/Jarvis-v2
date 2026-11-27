"""T3c: canlı Groq kota satırları, bayat satır tanısı ve hız freninin kaldırılması.

Kanıt üç ayrı iddiaya ayrılır: (1) POLICIES gerçekten üç doğrulanmış satır taşır ve
şema onları geçerli sayar, (2) satır varken dakikadaki 31. istek yerelde atlanır ve
sağlayıcı çağrılmaz, bayat satır limit uygulamaz ama sessiz de kalmaz, (3) fren
(`apply_rate_brake`/`BRAKE_*`) artık yoktur; görsel yol token üst sınırına bağlanmaz.
"""
import inspect
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from modules import failure_policy, llm, rate_limits, router_quota as quota, smart_router as router, usage_meter

NOW = 1796000000.                     # 30 Kas 2026; satırların geçerlilik penceresi içinde
LIVE = {("groq", "openai/gpt-oss-120b"), ("groq", "openai/gpt-oss-20b"),
        ("groq", "qwen/qwen3.8-27b")}


class _FrozenTime:
    """Rezervasyon saati test anına çivilenir; gerçek saat kullanılmaz."""

    def time(self):
        return NOW


def temp_store(case):
    directory = Path(case.enterContext(tempfile.TemporaryDirectory()))
    case.enterContext(patch.object(router, "_STORE", directory))
    case.enterContext(patch.object(router, "_HEALTH", {}))
    case.enterContext(patch.object(quota, "time", _FrozenTime()))
    case.enterContext(patch.object(llm.privacy, "mode", return_value="normal"))
    return directory


def booked(directory):
    path = Path(directory) / "atomic_requests.sqlite3"
    if not path.exists():
        return 0
    with closing(sqlite3.connect(path)) as db:
        try:
            return db.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
        except sqlite3.OperationalError:
            return 0


class LivePolicyRowsTests(unittest.TestCase):
    # Satırlar koda gerçekten yazıldı mı; yoksa test boş POLICIES üzerinde yalan mı söyler?

    def test_exactly_three_verified_groq_rows(self):
        self.assertEqual(set(quota.POLICIES), LIVE)
        for (provider, model), row in quota.POLICIES.items():
            with self.subTest(model=model):
                self.assertEqual((row["provider"], row["model"]), (provider, model))
                self.assertEqual(row["source_url"], "https://console.groq.com/docs/rate-limits")
                self.assertEqual(row["verified_at"], 1795651200)   # 26 Kas 2026 00:00 UTC
                self.assertEqual(row["expires_at"] - row["verified_at"], 30 * 86400)
                self.assertLessEqual(row["expires_at"] - row["verified_at"], 31 * 86400)
                self.assertEqual((row["rpm"], row["rpd"]), (30, 1000))
                # Token limiti bilinçli olarak yok: yazılı tpm görsel analizi durdururdu.
                self.assertNotIn("tpm", row)
                self.assertNotIn("tpd", row)

    def test_rows_pass_the_real_schema_inside_their_window(self):
        for provider, model in LIVE:
            with self.subTest(model=model):
                self.assertEqual(quota.validate_policy(provider, model,
                                                       quota.POLICIES[(provider, model)], NOW),
                                 (30, 1000, None, None))


class LivePolicyEnforcementTests(unittest.TestCase):
    def setUp(self):
        self.directory = temp_store(self)

    def run_router(self, plan, request, adapter):
        with patch.object(router, "plan", return_value=plan):
            return router.run_request(request, adapter)

    def test_thirty_first_request_in_the_minute_is_skipped_without_a_provider_call(self):
        spec = router.ModelSpec("groq", "openai/gpt-oss-120b")
        plan = router.RoutePlan((spec,), (), 1)
        request = router.ModelRequest(owner="alice", profile="conversation",
                                     max_output_tokens=64)
        calls = []

        def adapter(item):
            calls.append(item)
            return "ok"

        for _ in range(30):
            self.assertEqual(self.run_router(plan, request, adapter).text, "ok")
        with self.assertRaises(failure_policy.ProviderExhaustedError) as caught:
            self.run_router(plan, request, adapter)
        self.assertEqual(len(calls), 30)          # 31. istek sağlayıcıya hiç gitmedi
        self.assertIn("doldu", str(caught.exception))
        self.assertEqual(booked(self.directory), 30)

    def test_without_a_row_behavior_is_unchanged(self):
        # T3b testi korunur; burada kilit: satır yokken tek deneme ve disk yazımı yok.
        self.enterContext(patch.object(quota, "POLICIES", {}))
        spec = router.ModelSpec("groq", "openai/gpt-oss-120b")
        plan = router.RoutePlan((spec,), (), 1)
        request = router.ModelRequest(owner="alice", profile="conversation",
                                     max_output_tokens=64)
        calls = []
        self.assertEqual(self.run_router(plan, request, lambda item: calls.append(item) or "ok").text,
                         "ok")
        self.assertEqual(len(calls), 1)
        self.assertEqual(booked(self.directory), 0)


class StalePolicyDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(quota, "_STALE_LOGGED", set()))

    def stale_row(self):
        return {"provider": "groq", "model": "stale-fixture",
                "source_url": "https://console.groq.com/docs/rate-limits",
                "verified_at": NOW - 40 * 86400, "expires_at": NOW - 10 * 86400,
                "rpm": 30, "rpd": 1000}

    def reserve(self):
        return quota.reserve("alice", "groq", "stale-fixture",
                             directory=self.directory, now=NOW)

    def test_expired_row_blocks_nothing_and_logs_exactly_one_line(self):
        self.enterContext(patch.object(quota, "POLICIES",
                                       {("groq", "stale-fixture"): self.stale_row()}))
        with self.assertLogs("jarvis", level="ERROR") as logs:
            self.assertFalse(self.reserve())
            self.assertFalse(self.reserve())    # ikinci çağrı satırı tekrarlamaz
        self.assertEqual(len(logs.records), 1)
        self.assertIn("policy_expired", logs.records[0].getMessage())
        self.assertEqual(booked(self.directory), 0)   # limit yok, satır yazılmadı


class BrakeRemovalTests(unittest.TestCase):
    def test_brake_symbols_are_absent(self):
        for name in ("apply_rate_brake", "BRAKE_STEP_SECONDS", "BRAKE_MAX_SECONDS",
                     "BRAKE_PAY_SECONDS"):
            self.assertFalse(hasattr(llm, name), name)

    def test_no_code_file_mentions_the_brake(self):
        root = Path(__file__).resolve().parents[1]
        hits = []
        for folder in ("modules", "tests"):
            for path in (root / folder).rglob("*.py"):
                if path.name == Path(__file__).name:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                if "apply_rate_brake" in text or "BRAKE_" in text:
                    hits.append(str(path.relative_to(root)))
        self.assertEqual(hits, [])

    def test_near_cap_usage_never_sleeps_inside_dispatch(self):
        request = router.ModelRequest(owner="alice", profile="conversation",
                                     max_output_tokens=64)
        spec = router.ModelSpec("groq", "openai/gpt-oss-120b")
        slept = []
        with llm.owner_context("alice"), \
             patch.object(llm, "_send_provider", return_value="yanıt"), \
             patch.object(usage_meter, "recent_usage", return_value=(10_000, 10_000_000)), \
             patch.object(rate_limits, "limit_for", return_value=(30, 8000)), \
             patch.object(rate_limits, "should_wait", return_value=True), \
             patch("time.sleep", side_effect=slept.append):
            self.assertEqual(llm.dispatch(request, spec, "soru", "sistem"), "yanıt")
        self.assertEqual(slept, [])      # eski fren burada 2,5 sn beklerdi


class ImagePathLockTests(unittest.TestCase):
    # Görsel yol token üst sınırı taşımadığı için yazılı bir tpm onu durdurmamalı.

    def test_image_source_does_not_depend_on_token_budget(self):
        for function in (llm.ask_image, llm._image_transport):
            with self.subTest(function=function.__name__):
                self.assertNotIn("token_budget", inspect.getsource(function))

    def test_live_row_reserves_a_request_without_a_token_bound(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.assertTrue(quota.reserve("alice", "groq", "openai/gpt-oss-120b",
                                      directory=directory, now=NOW, token_budget=None))
        self.assertEqual(booked(directory), 1)


if __name__ == "__main__":
    unittest.main()