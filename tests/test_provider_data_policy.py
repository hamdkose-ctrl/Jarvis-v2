"""Provider data-policy regressions for the existing Smart Router.

Research-derived product rule supplied by the project manager:
- Gemini-class cloud routes are PUBLIC-only.
- SENSITIVE text may use verified-free Groq, then local Ollama.
- OpenRouter has no approved sensitive-data policy in this contract and is PUBLIC-only.
- Cloudflare remains the existing image-generation transport; it is not invented as a text LLM route here.
- NVIDIA is not an implemented Jarvis provider and is not added by these tests.

No test in this module performs a real network/provider call.
"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modules import llm, smart_router as router


class ProviderDataPolicyTests(unittest.TestCase):
    OWNER = "alice"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target, value in (("_STORE", Path(self.tmp.name)), ("_HEALTH", {}), ("_LAST", {})):
            p = patch.object(router, target, value)
            p.start(); self.addCleanup(p.stop)
        for obj, name, value in (
            (router.privacy, "mode", "normal"),
            (router.privacy, "protect", lambda text: "enc:" + text),
            (router.privacy, "unprotect", lambda text: text.removeprefix("enc:")),
            (llm, "user_key", "gem-key"),
            (llm, "user_groq_key", "groq-key"),
            (llm, "active_model", "gem-model"),
            (llm, "groq_model", "groq-model"),
        ):
            p = patch.object(obj, name, side_effect=value if callable(value) else None,
                             return_value=None if callable(value) else value)
            p.start(); self.addCleanup(p.stop)
        router.configure(self.OWNER, True, model="openrouter/free", key="openrouter-key")
        self._evidence("gemini", "gem-model")
        self._evidence("groq", "groq-model")
        self._evidence("openrouter", "openrouter/free")

    def _evidence(self, provider: str, model: str) -> None:
        now = router.time.time()
        router.set_free_tier_evidence(
            self.OWNER,
            provider=provider,
            model=model,
            free_tier_verified=True,
            source="manager-research-fixture",
            evidence_ref="test://verified-free-tier",
            verified_at=now,
            ttl_seconds=3600,
            eligibility="eligible",
            quota_state="available",
            quota_remaining=10,
            hard_stop_guaranteed=True,
            verification_status="verified",
            reason="provider data-policy regression fixture",
        )

    def test_sensitive_code_skips_public_only_gemini_even_when_gemini_is_preferred(self):
        called = []
        result = router.run(
            self.OWNER,
            "Python hatasını düzelt; iletişim adresim ali@example.com",
            lambda provider: called.append(provider) or "ok",
            preferred="gemini",
        )
        self.assertEqual(result, "ok")
        self.assertEqual(called, ["groq"])

    def test_sensitive_groq_failure_falls_to_local_not_gemini_or_openrouter(self):
        called = []
        def invoke(provider):
            called.append(provider)
            if provider == "groq":
                raise llm.CloudError("temporary")
            if provider == "ollama":
                return "local-answer"
            self.fail("Sensitive content reached a PUBLIC-only cloud route: " + provider)
        self.assertEqual(
            router.run(self.OWNER, "IBAN: TR120006200000123456789012 için bunu açıkla", invoke),
            "local-answer",
        )
        self.assertEqual(called, ["groq", "ollama"])

    def test_sensitive_without_eligible_groq_uses_local_even_if_gemini_has_evidence(self):
        state = router.settings(self.OWNER)
        state["free_tier_evidence"].pop("groq", None)
        router._save_state(self.OWNER, state)
        called = []
        result = router.run(
            self.OWNER,
            "API key=abcdefghijkl1234567890 için yardım et",
            lambda provider: called.append(provider) or "ok",
        )
        self.assertEqual(result, "ok")
        self.assertEqual(called, ["ollama"])

    def test_sensitive_openrouter_preference_does_not_override_data_policy(self):
        called = []
        result = router.run(
            self.OWNER,
            "E-posta adresim ali@example.com; bunu özetle",
            lambda provider: called.append(provider) or "ok",
            preferred="openrouter",
        )
        self.assertEqual(result, "ok")
        self.assertEqual(called, ["groq"])

    def test_sensitive_vision_does_not_send_image_request_to_public_only_gemini(self):
        called = []
        result = router.run(
            self.OWNER,
            "Ekrandaki ali@example.com adresini kontrol et",
            lambda provider: called.append(provider) or "ok",
            image=True,
            preferred="gemini",
        )
        self.assertEqual(result, "ok")
        self.assertEqual(called, ["ollama"])

    def test_gizli_mode_is_sensitive_even_without_detectable_secret_tokens(self):
        called = []
        with patch.object(router.privacy, "mode", return_value="gizli"):
            result = router.run(
                self.OWNER,
                "Bu özel iş planını analiz et",
                lambda provider: called.append(provider) or "ok",
                preferred="gemini",
            )
        self.assertEqual(result, "ok")
        self.assertEqual(called, ["groq"])

    def test_public_code_request_preserves_existing_gemini_preference(self):
        called = []
        result = router.run(
            self.OWNER,
            "Python quicksort örneği yaz",
            lambda provider: called.append(provider) or "ok",
            preferred="gemini",
        )
        self.assertEqual(result, "ok")
        self.assertEqual(called, ["gemini"])

    def test_public_provider_pool_does_not_grow_new_nvidia_or_cloudflare_text_routes(self):
        candidates = router.candidates(self.OWNER, "analysis")
        self.assertNotIn("nvidia", candidates)
        self.assertNotIn("cloudflare", candidates)


if __name__ == "__main__":
    unittest.main()
