"""F-009 P0: Smart Router is the only automatic free-provider transition authority.

No test in this module performs a real provider/network call.
"""
from __future__ import annotations

from types import SimpleNamespace
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from modules import failure_policy, llm, smart_router as router, ui_jobs
from web_models import WebModels


class ProviderRoutingAuthorityTests(unittest.TestCase):
    OWNER = "alice"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target, value in [
            ("_STORE", Path(self.tmp.name)),
            ("_HEALTH", {}),
            ("_LAST", {}),
        ]:
            p = patch.object(router, target, value)
            p.start(); self.addCleanup(p.stop)
        for obj, name, value in [
            (router.privacy, "mode", "normal"),
            (llm, "current_user", self.OWNER),
            (llm, "user_key", "gem-key"),
            (llm, "user_groq_key", "groq-key"),
            (llm, "active_model", "gem-model"),
            (llm, "groq_model", "groq-model"),
        ]:
            p = patch.object(obj, name, return_value=value)
            p.start(); self.addCleanup(p.stop)
        p = patch.object(router.privacy, "protect", side_effect=lambda text: "enc:" + text)
        p.start(); self.addCleanup(p.stop)
        p = patch.object(router.privacy, "unprotect", side_effect=lambda text: text.removeprefix("enc:"))
        p.start(); self.addCleanup(p.stop)
        with patch.object(router, "status", return_value={}):
            router.configure(self.OWNER, True, key="openrouter-key")

    def evidence(self, provider: str, model: str) -> None:
        now = router.time.time()
        router.set_free_tier_evidence(
            self.OWNER,
            provider=provider,
            model=model,
            free_tier_verified=True,
            source="test-fixture",
            evidence_ref="test://verified-free-tier",
            verified_at=now,
            ttl_seconds=3600,
            eligibility="eligible",
            quota_state="available",
            quota_remaining=10,
            hard_stop_guaranteed=True,
            verification_status="verified",
            reason="strict zero-cost regression fixture",
        )

    def test_explicit_groq_preference_enters_router_before_transport(self):
        with patch.object(router, "run", return_value="router-answer") as routed, \
             patch.object(llm, "_groq", return_value="direct-answer") as direct:
            result = llm._send("merhaba", "", 100, None, "groq")
        self.assertEqual(result, "router-answer")
        routed.assert_called_once()
        self.assertEqual(routed.call_args.kwargs.get("preferred"), "groq")
        direct.assert_not_called()

    def test_explicit_ollama_preference_enters_router_before_transport(self):
        with patch.object(router, "run", return_value="router-answer") as routed, \
             patch.object(llm, "_ollama_task", return_value="direct-answer") as direct:
            result = llm._send("merhaba", "", 100, None, "ollama")
        self.assertEqual(result, "router-answer")
        routed.assert_called_once()
        self.assertEqual(routed.call_args.kwargs.get("preferred"), "ollama")
        direct.assert_not_called()

    def test_explicit_gemini_preference_enters_router_before_transport(self):
        with patch.object(router, "run", return_value="router-answer") as routed, \
             patch.object(llm, "_with_models", return_value="direct-answer") as direct, \
             patch.object(llm, "_cli", return_value=Mock()):
            result = llm._send("merhaba", "", 100, None, "gemini")
        self.assertEqual(result, "router-answer")
        routed.assert_called_once()
        self.assertEqual(routed.call_args.kwargs.get("preferred"), "gemini")
        direct.assert_not_called()

    def test_explicit_openrouter_preference_enters_router_before_transport(self):
        with patch.object(router, "run", return_value="router-answer") as routed, \
             patch.object(router, "openrouter", return_value="direct-answer") as direct:
            result = llm._send("merhaba", "", 100, None, "openrouter")
        self.assertEqual(result, "router-answer")
        routed.assert_called_once()
        self.assertEqual(routed.call_args.kwargs.get("preferred"), "openrouter")
        direct.assert_not_called()

    def test_preferred_gemini_missing_evidence_never_reaches_gemini_transport(self):
        called = []
        def callback(provider):
            called.append(provider)
            if provider == "gemini":
                self.fail("Gemini transport must not run without exact free-tier evidence")
            raise llm.LocalModelError("local unavailable")
        with self.assertRaises(failure_policy.ProviderExhaustedError) as caught:
            router.run(self.OWNER, "merhaba", callback, preferred="gemini")
        self.assertNotIn("gemini", called)
        self.assertIn("PROVIDER_FREE_TIER_EVIDENCE_MISSING", str(caught.exception.reason_code))

    def test_preference_reorders_only_eligible_free_routes(self):
        self.evidence("gemini", "gem-model")
        self.evidence("groq", "groq-model")
        called = []
        def callback(provider):
            called.append(provider)
            if provider == "gemini":
                raise llm.CloudError("temporary")
            if provider == "groq":
                return "groq-answer"
            raise llm.LocalModelError("local unavailable")
        self.assertEqual(
            router.run(self.OWNER, "merhaba", callback, preferred="gemini"),
            "groq-answer",
        )
        self.assertEqual(called[:2], ["gemini", "groq"])

    def test_cloud_confirmation_and_key_without_evidence_never_call_cloud(self):
        called = []
        def callback(provider):
            called.append(provider)
            if provider in {"gemini", "groq", "openrouter"}:
                self.fail("Cloud transport must not run without exact evidence")
            raise llm.LocalModelError("local unavailable")
        with self.assertRaises(failure_policy.ProviderExhaustedError):
            router.run(self.OWNER, "merhaba", callback)
        self.assertEqual(called, ["ollama"])

    def test_openrouter_preference_without_evidence_does_not_call_openrouter(self):
        called = []
        def callback(provider):
            called.append(provider)
            if provider == "openrouter":
                self.fail("OpenRouter transport must not run without exact free-model evidence")
            raise llm.LocalModelError("local unavailable")
        with self.assertRaises(failure_policy.ProviderExhaustedError):
            router.run(self.OWNER, "merhaba", callback, preferred="openrouter")
        self.assertNotIn("openrouter", called)

    def test_local_privacy_preference_never_calls_cloud(self):
        self.evidence("gemini", "gem-model")
        self.evidence("groq", "groq-model")
        called = []
        with patch.object(router.privacy, "mode", return_value="yerel"):
            result = router.run(
                self.OWNER,
                "merhaba",
                lambda provider: called.append(provider) or "local-answer",
                preferred="gemini",
            )
        self.assertEqual(result, "local-answer")
        self.assertEqual(called, ["ollama"])

    def test_automatic_pool_never_contains_paid_providers(self):
        self.evidence("gemini", "gem-model")
        self.evidence("groq", "groq-model")
        for task in ("chat", "code", "analysis", "vision"):
            with self.subTest(task=task):
                candidates = router.candidates(self.OWNER, task)
                self.assertNotIn("openai", candidates)
                self.assertNotIn("anthropic", candidates)

    def test_manual_provider_preference_is_not_paid_consent(self):
        from modules import paid_providers, user_models
        with patch.object(paid_providers, "configure") as paid_configure, \
             patch.object(paid_providers, "generate", side_effect=AssertionError("paid")) as paid_generate, \
             patch.object(user_models, "save_choice") as save_choice, \
             patch.object(llm, "save_settings") as save_settings:
            llm.set_provider("gemini")
        paid_configure.assert_not_called()
        paid_generate.assert_not_called()
        save_choice.assert_called_once_with(self.OWNER, provider="gemini")
        self.assertEqual(save_settings.call_args.kwargs["ai_mode"], "gemini")

    def test_gemini_same_provider_model_fallback_stays_available_with_exact_evidence(self):
        calls = []
        def execute(model):
            calls.append(model)
            if model == "gem-a":
                raise llm.errors.ClientError(404, {"error": {"message": "missing"}})
            return "gem-b-answer"
        with patch.object(llm, "model_names", return_value=["gem-a", "gem-b"]), \
             patch.object(router, "provider_allowed", return_value={"ok": True}), \
             patch.object(llm, "_fallback_states", {}), patch.object(llm, "_rate_limited", {}):
            self.assertEqual(llm._with_models(execute, router_authorized=True), "gem-b-answer")
        self.assertEqual(calls, ["gem-a", "gem-b"])

    def test_gemini_fallback_model_without_exact_evidence_is_not_called(self):
        calls = []
        def execute(model):
            calls.append(model)
            raise llm.errors.ClientError(404, {"error": {"message": "missing"}})
        def allowed(owner, provider, model=None, **_):
            return {"ok": model == "gem-a"}
        with patch.object(llm, "model_names", return_value=["gem-a", "gem-b"]), \
             patch.object(router, "provider_allowed", side_effect=allowed), \
             patch.object(llm, "_fallback_states", {}), patch.object(llm, "_rate_limited", {}):
            with self.assertRaises(llm.errors.ClientError):
                llm._with_models(execute, router_authorized=True)
        self.assertEqual(calls, ["gem-a"])

    def test_groq_same_provider_model_fallback_stays_available_with_exact_evidence(self):
        first = Mock(status_code=404, headers={}, text="missing")
        second = Mock(status_code=200, headers={})
        second.json.return_value = {"choices": [{"message": {"content": "groq-b-answer"}}]}
        seen = []
        def post(_url, *, headers, json, timeout):
            seen.append(json["model"])
            return first if json["model"] == "groq-a" else second
        with patch.object(llm, "GROQ_MODELS", ["groq-a", "groq-b"]), \
             patch.object(llm, "groq_model", return_value="groq-a"), \
             patch.object(router, "settings", return_value={"cloud_free_confirmed": True}), \
             patch.object(router, "provider_allowed", return_value={"ok": True}), \
             patch.object(llm.requests, "post", side_effect=post), \
             patch.object(llm, "_fallback_states", {}), patch.object(llm, "_rate_limited", {}):
            self.assertEqual(llm._groq([], "", 100, router_authorized=True), "groq-b-answer")
        self.assertEqual(seen, ["groq-a", "groq-b"])

    def test_public_strict_image_request_still_enters_router(self):
        with patch.object(llm.privacy, "mode", return_value="normal"), \
             patch.object(llm, "provider", return_value="ollama"), \
             patch.object(router, "run", return_value="router-image") as routed, \
             patch.object(llm, "_ask_image", side_effect=AssertionError("direct bypass")):
            result = llm.ask_image("missing.png", "buna bak", strict=True)
        self.assertEqual(result, "router-image")
        routed.assert_called_once()
        self.assertEqual(routed.call_args.kwargs.get("preferred"), "ollama")
        self.assertTrue(routed.call_args.kwargs.get("image"))

    def test_auxiliary_gemini_is_denied_for_non_auto_preference_without_evidence(self):
        for preferred in ("groq", "gemini"):
            with self.subTest(preferred=preferred), patch.object(llm, "provider", return_value=preferred):
                self.assertFalse(llm.gemini_aux_allowed())

    def test_live_uses_exact_live_model_for_auxiliary_gate(self):
        from modules import live
        with patch.object(llm, "gemini_aux_allowed", return_value=False) as allowed:
            self.assertFalse(live.enabled())
        allowed.assert_called_once_with(live.model_name())

    def test_embedding_requires_exact_embedding_model_evidence(self):
        self.evidence("gemini", "gem-model")
        client = Mock()
        client.models.embed_content.return_value = SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0])])
        with patch.object(llm, "provider", return_value="gemini"), \
             patch.object(llm, "_cli", return_value=client):
            with self.assertRaises(ValueError):
                llm.embed(["metin"])
        client.models.embed_content.assert_not_called()

    def test_missing_evidence_reason_is_not_misreported_as_quota(self):
        called = []
        with self.assertRaises(failure_policy.ProviderExhaustedError) as caught:
            router.run(
                self.OWNER,
                "merhaba",
                lambda provider: called.append(provider) or (_ for _ in ()).throw(llm.LocalModelError("local unavailable")),
                preferred="gemini",
            )
        self.assertNotIn("gemini", called)
        self.assertEqual(caught.exception.reason_code, "PROVIDER_FREE_TIER_EVIDENCE_MISSING")
        self.assertNotIn("kota doldu", str(caught.exception).casefold())


class ProviderSetupGenerationBoundaryTests(unittest.TestCase):
    def bridge(self, owner="alice"):
        bridge = WebModels()
        runtime = SimpleNamespace(
            _p=lambda: SimpleNamespace(slug=owner, name=owner.title()),
            llm=Mock(),
            privacy=SimpleNamespace(audit=Mock()),
            _record_failure=Mock(),
            time=Mock(),
        )
        bridge._runtime = runtime
        return bridge, runtime

    def test_gemini_key_save_does_not_generate(self):
        bridge, runtime = self.bridge()
        with patch("google.genai.Client", side_effect=AssertionError("generation client must not be created")):
            result = bridge.user_key_set("Alice", "gem-key")
        self.assertTrue(result["ok"])
        runtime.llm.set_user_key.assert_called_once_with("alice", "gem-key")
        self.assertIn("doğrulan", result["msg"].casefold())

    def test_groq_key_save_does_not_generation_test(self):
        bridge, runtime = self.bridge()
        runtime.llm.user_groq_key.return_value = "groq-key"
        runtime.llm.status.return_value = {}
        runtime.llm.test_groq.side_effect = AssertionError("key save must not generate")
        result = bridge.groq_key_save("groq-key", model="groq-model", activate=True)
        self.assertTrue(result["ok"])
        runtime.llm.set_user_groq_key.assert_called_once_with("alice", "groq-key")
        runtime.llm.test_groq.assert_not_called()
        runtime.llm.set_provider.assert_called_once_with("groq")
        self.assertIn("doğrulan", result["msg"].casefold())

    def test_llm_measure_without_evidence_does_not_generate(self):
        bridge, runtime = self.bridge()
        runtime.llm.model_names.return_value = ["gem-model"]
        runtime.llm.gemini_client.side_effect = AssertionError("measure must stop before generation client")
        denied = {
            "ok": False,
            "reason_code": "PROVIDER_FREE_TIER_EVIDENCE_MISSING",
            "reason": "Geçerli ücretsiz katman kanıtı yok; yeniden doğrulama gerekli.",
        }
        with patch.object(router, "provider_allowed", return_value=denied), \
             patch.object(ui_jobs, "start", side_effect=lambda owner, kind, fn: {"owner": owner, "kind": kind, "data": fn()}):
            result = bridge.llm_measure()
        runtime.llm.gemini_client.assert_not_called()
        self.assertFalse(result["data"]["gem-model"]["ok"])
        self.assertEqual(
            result["data"]["gem-model"]["reason_code"],
            "PROVIDER_FREE_TIER_EVIDENCE_MISSING",
        )


if __name__ == "__main__":
    unittest.main()
