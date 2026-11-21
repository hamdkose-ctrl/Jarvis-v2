"""V2 shared SQLite/OS claims, cancellation, qualification and monetary uncertainty."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import test_engine_modular  # noqa: F401
from modules import (
    llm,
    router_quota as quota,
    smart_router as router,
    router_connections as connections,
    user_models,
    model_capabilities,
)


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        from modules import requests_state

        for name, value in (
            ("_journal", self.root / "requests.json"),
            ("_records", {}),
        ):
            p = patch.object(requests_state, name, value)
            p.start()
            self.addCleanup(p.stop)
        for obj, name, value in [
            (router, "_STORE", self.root / "router"),
            (router, "_HEALTH", {}),
            (connections, "DATA_DIR", self.root),
            (user_models, "DATA_DIR", self.root),
        ]:
            p = patch.object(obj, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(router.privacy, "mode", return_value="normal")
        p.start()
        self.addCleanup(p.stop)

    def test_dispatch_restores_context_on_success_failure_and_parallel_owners(self):
        previous = llm.set_user_context("before")
        self.addCleanup(llm.set_user_context, None)
        requests = [router.ModelRequest(owner=owner) for owner in ("alice", "bob")]
        spec = router.ModelSpec("groq", "exact")
        reached = threading.Barrier(2)

        def send(*args, **kwargs):
            owner = llm.current_user()
            reached.wait(2)
            return owner

        def call(request):
            with llm.owner_context("caller-" + request.owner):
                result = llm.dispatch(request, spec, "x", "")
                self.assertEqual(llm.current_user(), "caller-" + request.owner)
                return result

        with (
            patch.object(llm, "_send_provider", side_effect=send),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            self.assertEqual(list(pool.map(call, requests)), ["alice", "bob"])
        self.assertEqual(llm.current_user(), "before")
        with patch.object(llm, "_send_provider", side_effect=RuntimeError("synthetic")):
            with self.assertRaises(RuntimeError):
                llm.dispatch(requests[0], spec, "x", "")
        self.assertEqual(llm.current_user(), "before")

    def test_plan_uses_request_owners_real_model_preference_and_restores_reader(self):
        user_models.save_choice("alice", provider="auto", groq_model="model-a")
        user_models.save_choice("bob", provider="auto", groq_model="model-b")
        router.configure('alice', gemini_scopes=['conversation'])
        llm.set_user_context("bob")
        self.addCleanup(llm.set_user_context, None)
        with (
            patch.object(llm, "user_key", return_value=""),
            patch.object(llm, "user_groq_key", return_value="key"),
            patch("modules.cloudflare_chat.configured", return_value=False),
        ):
            plan = router.plan(router.ModelRequest(owner="alice"))
        self.assertEqual(plan.candidates[0].model, "model-a")
        self.assertEqual(llm.current_user(), "bob")

    def test_model_wait_carries_foreground_or_background_class_into_research(self):
        from contextlib import nullcontext
        from modules import model_wait, requests_state

        observed = []

        def ask_fn(*args, **kwargs):
            observed.append(llm._request(32, profile="public_research").work_class)
            return "reply"

        with llm.owner_context("alice"), patch.object(model_wait, "_PENDING", {}):
            self.assertEqual(model_wait.ask("query", seconds=2, ask_fn=ask_fn), "reply")
            with model_wait.foreground(nullcontext):
                self.assertEqual(
                    model_wait.ask("query", seconds=2, ask_fn=ask_fn), "reply"
                )
        self.assertEqual(observed, ["background", "interactive"])
        self.assertIsNone(requests_state.model_work_class())

    def test_vision_preserves_runtime_request_identity_and_background_class(self):
        from provider_fixture import routed_plan
        from modules import requests_state

        requests_state.register("alice", "actual-image-turn")
        seen = []

        def transport(*args, **kwargs):
            seen.append(requests_state.model_work_class())
            return "image answer"

        with (
            routed_plan(provider="gemini", model="vision-fixture"),
            llm.owner_context("alice"),
            requests_state.activate("alice", "actual-image-turn"),
            requests_state.model_work_scope("background"),
            patch.object(llm, "_image_transport", side_effect=transport),
        ):
            self.assertEqual(
                llm.ask_image("unused.png", "read", strict=True), "image answer"
            )
            trace = router.trace("alice", "actual-image-turn")
        self.assertEqual(trace["request_id"], "actual-image-turn")
        self.assertEqual(seen, ["background"])

    def test_models_and_owners_share_the_last_project_request_atomically(self):
        start = threading.Barrier(2)

        def reserve(owner, model):
            start.wait()
            try:
                return quota.reserve(
                    owner,
                    "gemini",
                    model,
                    directory=self.root,
                    quota_scope="project:shared",
                    application_limit=1,
                )
            except quota.ReservationExhausted:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(
                pool.map(
                    lambda args: reserve(*args),
                    [("alice", "model-a"), ("bob", "model-b")],
                )
            )
        self.assertEqual(sorted(outcomes), [False, True])
        with closing(sqlite3.connect(self.root / "atomic_requests.sqlite3")) as db:
            self.assertEqual(
                db.execute("SELECT count(*) FROM requests").fetchone()[0], 1
            )

    def test_background_cannot_take_interactive_reserved_slot(self):
        request = router.ModelRequest(
            owner="alice", call_id="bg", work_class="background"
        )
        spec = router.ModelSpec("groq", "m")
        with quota.admission(request, spec, directory=router._STORE):
            with self.assertRaises(quota.ReservationUnavailable):
                with quota.admission(
                    replace(request, call_id="bg2"), spec, directory=router._STORE
                ):
                    pass
            with quota.admission(
                replace(request, call_id="fg", work_class="interactive"),
                spec,
                directory=router._STORE,
            ):
                pass

    def test_local_loopback_models_and_protocols_share_one_physical_claim(self):
        row = connections.save(
            "bob",
            dict(
                name="Local",
                protocol="openai_compatible",
                base_url="http://127.0.0.1:1234/v1",
                model="other-local",
                role="conversation",
                billing="free",
                enabled=True,
                paid_enabled=False,
                data_scopes=["conversation"],
            ),
        )
        custom = router.ModelSpec(
            "custom",
            "other-local",
            connection_id=row["id"],
            connection_revision=row["revision"],
        )
        with patch.object(
            llm,
            "provider_configuration",
            return_value={"url": "http://localhost:11434", "backend": "ollama"},
        ):
            with quota.admission(
                router.ModelRequest(owner="alice", call_id="local-a"),
                router.ModelSpec("ollama", "local-a"),
                directory=router._STORE,
            ):
                with self.assertRaises(quota.ReservationUnavailable):
                    with quota.admission(
                        router.ModelRequest(owner="bob", call_id="local-b"),
                        custom,
                        directory=router._STORE,
                    ):
                        pass

    def test_cancelled_slow_call_holds_its_claim_until_transport_really_returns(self):
        entered = threading.Event()
        release = threading.Event()
        cancelled = threading.Event()
        request = router.ModelRequest(
            owner="alice", request_id="slow", cancelled=cancelled
        )
        plan = router.RoutePlan((router.ModelSpec("ollama", "m"),), (), 1)

        def adapter(spec):
            entered.set()
            release.wait(3)
            return "late"

        with (
            patch.object(router, "plan", return_value=plan),
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            future = pool.submit(router.run_request, request, adapter)
            try:
                self.assertTrue(entered.wait(2))
                cancelled.set()
                with self.assertRaises(quota.ReservationUnavailable):
                    with quota.admission(
                        router.ModelRequest(owner="alice", call_id="another"),
                        plan.candidates[0],
                        directory=router._STORE,
                    ):
                        pass
            finally:
                release.set()
            from modules import requests_state

            with self.assertRaises(requests_state.Cancelled):
                future.result(3)
        self.assertEqual(
            router.trace("alice", "slow")["attempts"][0]["state"], "unknown"
        )
        with quota.admission(
            router.ModelRequest(owner="alice", call_id="after"),
            plan.candidates[0],
            directory=router._STORE,
        ):
            pass

    def test_unknown_usage_holds_token_reservation_and_exact_total_reconciles(self):
        now = time.time()
        policy = {
            ("groq", "m"): {
                "rpm": 10,
                "rpd": 100,
                "tpm": 100,
                "tpd": 1000,
                "source_url": "https://example.org/limits",
                "verified_at": now - 1,
                "expires_at": now + 100,
            }
        }
        with patch.object(quota, "POLICIES", policy):
            quota.reserve(
                "alice",
                "groq",
                "m",
                directory=self.root,
                token_budget=40,
                attempt_id="one",
            )
            quota.reconcile(
                "alice",
                "one",
                {"input_tokens": 2, "output_tokens": 3},
                directory=self.root,
            )
            with closing(sqlite3.connect(self.root / "atomic_requests.sqlite3")) as db:
                self.assertEqual(
                    db.execute(
                        "SELECT token_units,actual_tokens FROM requests"
                    ).fetchone(),
                    (40, None),
                )
            quota.reconcile("alice", "one", {"total_tokens": 7}, directory=self.root)
            with closing(sqlite3.connect(self.root / "atomic_requests.sqlite3")) as db:
                self.assertEqual(
                    db.execute(
                        "SELECT token_units,actual_tokens FROM requests"
                    ).fetchone(),
                    (7, 7),
                )

    def test_monetary_cap_never_assumes_unknown_price_is_zero(self):
        with self.assertRaises(quota.ReservationUnavailable):
            quota.reserve(
                "alice",
                "custom:a",
                "m",
                directory=self.root,
                application_limit=10,
                cost_limit=100,
            )
        quota.reserve(
            "alice",
            "custom:a",
            "m",
            directory=self.root,
            application_limit=10,
            cost_limit=100,
            cost_bound=80,
        )
        with self.assertRaises(quota.ReservationExhausted):
            quota.reserve(
                "alice",
                "custom:a",
                "m",
                directory=self.root,
                application_limit=10,
                cost_limit=100,
                cost_bound=30,
            )

    def test_ui_free_label_cannot_put_unknown_connection_in_automatic_pool(self):
        row = connections.save(
            "alice",
            dict(
                name="Free claim",
                protocol="responses",
                base_url="https://api.example.org/v1",
                model="m",
                role="conversation",
                billing="free",
                enabled=True,
                paid_enabled=False,
                free_pool=True,
                data_scopes=["conversation"],
            ),
            secret="key",
        )
        request = router.ModelRequest(owner="alice")
        with patch.object(
            router, "selection", return_value={"candidates": [], "skipped": []}
        ):
            plan = router.plan(request)
        self.assertFalse(plan.candidates)
        self.assertIn(
            "CUSTOM_FREE_EVIDENCE_MISSING", [r["reason_code"] for r in plan.skipped]
        )
        facts = {
            "features": frozenset(),
            "source_url": "https://example.org/free",
            "verified_at": time.time() - 1,
            "expires_at": time.time() + 100,
            "account_eligible": True,
            "no_paid_billing": True,
            "data_scopes": ["conversation"],
        }
        key = ("alice", row["base_url"], hashlib.sha256(b"key").hexdigest(), "m")
        with (
            patch.object(model_capabilities, "CUSTOM_FREE_ACCOUNTS", {key: facts}),
            patch.object(
                router, "selection", return_value={"candidates": [], "skipped": []}
            ),
        ):
            self.assertEqual(
                router.plan(request).candidates[0].connection_id, row["id"]
            )
        self.assertFalse(connections.free_pool_eligible("bob", row))

    def test_role_gate_requires_full_corpus_and_is_invalidated_by_source_or_binding(
        self,
    ):
        spec = router.ModelSpec("groq", "m", binding="account-v1")
        report = {
            "state": "passed",
            "scope": "holdout",
            "semantic_acceptance": True,
            "corpus_sha256": "corpus",
            "head": "a" * 40,
            "accuracy": 0.95,
            "incorrect_action_proposals": 0,
            "attempted_effects": 0,
            "planned_cases": 20,
            "provider_responses": 20,
            "qualified_target": {
                "provider": "groq",
                "model": "m",
                "connection_id": None,
            },
            "results": [{"responded": True, "correct": i < 19} for i in range(20)],
        }
        for changes in (
            {"planned_cases": 1},
            {"accuracy": float("nan")},
            {"incorrect_action_proposals": 1},
            {"scope": "connection"},
            {"results": []},
        ):
            with self.assertRaises(ValueError):
                quota.qualify_role(
                    "alice",
                    spec,
                    {**report, **changes},
                    fingerprint="source",
                    directory=self.root,
                    corpus_sha256="corpus",
                    expected_cases=20,
                )
        quota.qualify_role(
            "alice",
            spec,
            report,
            fingerprint="source",
            directory=self.root,
            corpus_sha256="corpus",
            expected_cases=20,
        )
        self.assertTrue(
            quota.role_qualified(
                "alice",
                "groq",
                "m",
                None,
                fingerprint="source",
                binding="account-v1",
                directory=self.root,
            )
        )
        for owner, source, binding in [
            ("bob", "source", "account-v1"),
            ("alice", "new-source", "account-v1"),
            ("alice", "source", "new-key"),
        ]:
            self.assertFalse(
                quota.role_qualified(
                    owner,
                    "groq",
                    "m",
                    None,
                    fingerprint=source,
                    binding=binding,
                    directory=self.root,
                )
            )

    def test_runtime_vision_facts_are_not_inferred_from_the_model_name(self):
        response = patch.object(llm.requests, "post")
        with (
            response as post,
            patch.object(
                llm,
                "provider_configuration",
                return_value={"url": "http://localhost:11434", "backend": "ollama"},
            ),
            patch.object(model_capabilities, "_LOCAL_FACTS", {}),
        ):
            post.return_value.json.return_value = {
                "capabilities": ["completion", "vision"]
            }
            self.assertFalse(
                model_capabilities.check(
                    "ollama", "looks-like-vision", native_features={"verified_vision"}
                )["ok"]
            )
            model_capabilities.refresh_local(
                "actual-model", llm.provider_configuration()
            )
            self.assertTrue(
                model_capabilities.check(
                    "ollama", "actual-model", native_features={"verified_vision"}
                )["ok"]
            )
            self.assertFalse(
                model_capabilities.check(
                    "ollama", "different-model", native_features={"verified_vision"}
                )["ok"]
            )
            post.assert_called_once()
            self.assertFalse(post.call_args.kwargs["allow_redirects"])


if __name__ == "__main__":
    unittest.main()
