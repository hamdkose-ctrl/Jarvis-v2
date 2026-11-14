"""Router V2 user-flow seams: real owner state, plans and accounting; no live provider."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_engine_modular  # noqa: F401
from modules import llm, model_capabilities, provider_privacy, smart_router as router
from provider_fixture import fresh_bundle


class RouterV2Tests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for name, value in (("_STORE", self.root), ("_HEALTH", {})):
            p = patch.object(router, name, value)
            p.start()
            self.addCleanup(p.stop)
        for target, name, value in (
            (router.privacy, "mode", "normal"),
            (llm, "user_key", "gem-key"),
            (llm, "user_groq_key", "groq-key"),
            (llm, "active_model", "gemini-3.5-flash-lite"),
            (llm, "groq_model", "openai/gpt-oss-120b"),
        ):
            p = patch.object(target, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        fresh_bundle(self)
        p = patch("modules.usage_meter.observed_exhaustion", return_value=None)
        p.start()
        self.addCleanup(p.stop)
        router.configure("alice", True)
        for provider, model in (
            ("gemini", "gemini-3.5-flash-lite"),
            ("groq", "openai/gpt-oss-120b"),
        ):
            import time

            router.set_free_tier_evidence(
                "alice",
                provider=provider,
                model=model,
                free_tier_verified=True,
                source="reviewed official model facts",
                evidence_ref="https://example.org/evidence",
                verified_at=time.time(),
                ttl_seconds=3600,
                eligibility="eligible",
                quota_state="not_reported",
                hard_stop_guaranteed=True,
                verification_status="verified",
            )

    def request(self, **fields):
        return router.ModelRequest(
            owner="alice", profile="conversation", request_id="turn-alice", **fields
        )

    def test_private_conversation_gemini_requires_owner_scope_and_preserves_training_fact(
        self,
    ):
        self.assertNotEqual(
            router.plan(self.request()).candidates[0].provider, "gemini"
        )
        router.configure("alice", gemini_scopes=["conversation"])
        self.assertEqual(router.plan(self.request()).candidates[0].provider, "gemini")
        self.assertTrue(provider_privacy.PROVIDER_BUNDLE["gemini"]["trains_on_data"])
        self.assertNotIn(
            "gemini",
            [
                s.provider
                for s in router.plan(
                    router.ModelRequest(owner="bob", profile="conversation")
                ).candidates
            ],
        )

    def test_scope_revocation_between_plan_and_send_blocks_gemini(self):
        router.configure("alice", gemini_scopes=["conversation"])
        plan = router.plan(self.request())
        router.configure("alice", gemini_scopes=[])
        calls = []
        with patch.object(router, "plan", return_value=plan):
            result = router.run_request(
                self.request(), lambda spec: calls.append(spec.provider) or "cevap"
            )
        self.assertNotIn("gemini", calls)
        self.assertEqual(result.model.provider, "groq")

    def test_vision_has_real_gemini_model_and_one_eligible_local_backup(self):
        router.configure("alice", gemini_scopes=["selected_content"])
        request = router.ModelRequest(
            owner="alice",
            profile="vision",
            data_scope="selected_content",
            features=frozenset({"vision"}),
        )
        plan = router.plan(request)
        self.assertEqual(plan.candidates[0].provider, "gemini")
        self.assertIn("verified_vision", plan.candidates[0].features)
        self.assertFalse({"groq", "cloudflare"} & {s.provider for s in plan.candidates})

    def test_conversation_permission_cannot_authorize_selected_image(self):
        router.configure("alice", gemini_scopes=["conversation"])
        request = router.ModelRequest(
            owner="alice",
            profile="vision",
            data_scope="selected_content",
            features=frozenset({"vision"}),
        )
        self.assertNotIn(
            "gemini", [s.provider for s in router.plan(request).candidates]
        )

    def test_unknown_profile_rejected_without_transport(self):
        adapter = Mock()
        with self.assertRaises(ValueError):
            router.run_request(
                router.ModelRequest(owner="alice", profile="invented"), adapter
            )
        adapter.assert_not_called()

    def test_local_privacy_remains_local_after_scope_consent(self):
        router.configure("alice", gemini_scopes=["conversation", "selected_content"])
        with patch.object(router.privacy, "mode", return_value="yerel"):
            self.assertFalse(
                {"gemini", "groq", "cloudflare"}
                & {s.provider for s in router.plan(self.request()).candidates}
            )

    def test_result_contains_real_usage_and_parallel_request_trace_identity(self):
        usage = {
            "input_tokens": 12,
            "output_tokens": 5,
            "reasoning_tokens": None,
            "cached_tokens": None,
        }
        result = router.run_request(
            self.request(),
            lambda spec: router.AdapterResponse(
                "cevap", usage=usage, finish_reason="stop"
            ),
        )
        self.assertEqual(result.request_id, "turn-alice")
        self.assertEqual(result.usage, usage)
        second = router.ModelRequest(
            owner="alice", profile="conversation", request_id="turn-second"
        )
        router.run_request(second, lambda spec: "başka cevap")
        trace = router.trace("alice", "turn-alice")
        self.assertEqual(trace["request_id"], "turn-alice")
        self.assertEqual(trace["attempts"][0]["model"], result.model.model)
        self.assertNotIn("cevap", str(trace))
        self.assertIsNone(router.trace("bob", "turn-alice"))

    def test_truncation_cannot_be_adopted_as_valid_answer(self):
        adapter = Mock(
            return_value=router.AdapterResponse("yarım", finish_reason="length")
        )
        with self.assertRaises(Exception):
            router.run_request(self.request(), adapter)
        self.assertLessEqual(adapter.call_count, 2)

    def test_public_source_gate_is_not_relabelled_by_owner_consent(self):
        from modules import privacy_sources

        content = privacy_sources.mark_private("mail", "özel")
        router.configure("alice", gemini_scopes=["conversation", "selected_content"])
        self.assertIs(
            privacy_sources.classify([content]), privacy_sources.RouteClass.PRIVATE
        )

    def test_snapshot_read_does_not_consume_a_model_call(self):
        with patch.object(
            llm, "_send_provider", side_effect=AssertionError("status invoked provider")
        ):
            router.status("alice")

    def test_selected_image_reaches_exact_gemini_transport_once_and_reports_usage(self):
        from types import SimpleNamespace
        from PIL import Image

        router.configure("alice", gemini_scopes=["selected_content"])
        path = self.root / "selected.png"
        Image.new("RGB", (4, 4), "red").save(path)
        response = SimpleNamespace(
            text="Kırmızı kare.",
            candidates=[SimpleNamespace(finish_reason="STOP")],
            usage_metadata=SimpleNamespace(
                prompt_token_count=12,
                candidates_token_count=5,
                thoughts_token_count=None,
                cached_content_token_count=None,
            ),
        )
        cli = Mock()
        cli.models.generate_content.return_value = response
        with (
            patch.object(llm, "current_user", return_value="alice"),
            patch.object(llm, "provider", return_value="auto"),
            patch.object(llm, "_cli", return_value=cli),
        ):
            answer = llm.ask_image(str(path), "Görselde ne var?", strict=True)
        self.assertEqual(answer, "Kırmızı kare.")
        cli.models.generate_content.assert_called_once()
        self.assertEqual(
            cli.models.generate_content.call_args.kwargs["model"],
            "gemini-3.5-flash-lite",
        )
        self.assertEqual(
            len(cli.models.generate_content.call_args.kwargs["contents"]), 2
        )


if __name__ == "__main__":
    unittest.main()
