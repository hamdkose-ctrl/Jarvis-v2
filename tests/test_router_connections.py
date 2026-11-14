"""Real owner metadata/secret migration and SQLite ceilings; fake HTTP boundary only."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_engine_modular  # noqa: F401
from modules import (
    provider_protocols,
    router_connections as connections,
    router_quota,
    smart_router,
    user_models,
)


class ConnectionsTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for target, name, value in (
            (connections, "DATA_DIR", self.root),
            (user_models, "DATA_DIR", self.root),
            (smart_router, "_STORE", self.root / "router"),
        ):
            p = patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        for name, value in (
            ("protect", lambda text: "protected:" + text),
            ("unprotect", lambda text: text.removeprefix("protected:")),
        ):
            p = patch.object(connections.privacy, name, side_effect=value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(connections.privacy, "mode", return_value="normal")
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(connections.sys, "platform", "linux")
        p.start()
        self.addCleanup(p.stop)
        self.record = {
            "name": "Benim API",
            "protocol": "openai_compatible",
            "base_url": "https://api.example.org/v1",
            "model": "actual-model",
            "role": "conversation",
            "billing": "paid",
            "enabled": True,
            "paid_enabled": True,
            "data_scopes": ["conversation"],
            "daily_requests": 2,
            "max_output_tokens": 4096,
        }

    def save(self, owner="alice", **changes):
        return connections.save(
            owner, {**self.record, **changes}, secret="secret-" + owner
        )

    def test_role_connection_is_owner_bound_and_snapshot_never_exposes_secret(self):
        row = self.save()
        self.assertNotIn("secret-", str(connections.snapshot("alice")))
        self.assertEqual(connections.snapshot("bob"), [])
        with self.assertRaises(ValueError):
            connections.resolve("bob", row["id"])
        spec = smart_router.plan(
            smart_router.ModelRequest(owner="alice", profile="conversation")
        ).candidates[0]
        self.assertEqual(spec.connection_id, row["id"])
        self.assertEqual(spec.provider, "custom")

    def test_paid_binding_never_becomes_a_free_provider_fallback(self):
        row = self.save(role="long_worker")
        plan = smart_router.plan(
            smart_router.ModelRequest(owner="alice", profile="conversation")
        )
        self.assertNotIn(row["id"], [spec.connection_id for spec in plan.candidates])

    def test_save_is_not_a_connection_test_and_new_revision_invalidates_old_plan(self):
        with patch.object(
            provider_protocols.requests,
            "request",
            side_effect=AssertionError("save sent HTTP"),
        ):
            row = self.save()
            snapshot = connections.snapshot("alice")
        self.assertTrue(snapshot)
        spec = smart_router.plan(smart_router.ModelRequest(owner="alice")).candidates[0]
        self.save(id=row["id"], model="changed-model")
        self.assertFalse(
            smart_router._current_admission(
                smart_router.ModelRequest(owner="alice"), spec
            )
        )

    def test_trial_paid_unknown_require_explicit_billing_preference(self):
        for billing in ("paid", "trial", "unknown"):
            with self.subTest(billing=billing), self.assertRaises(ValueError):
                self.save(billing=billing, paid_enabled=False)

    def test_endpoint_secret_scope_rejects_redirect_credentials_and_nvidia_alias(self):
        for url in (
            "http://api.example.org",
            "https://name:secret@api.example.org",
            "https://api.example.org/?api_key=secret",
            "https://integrate.api.nvidia.com./v1",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.save(base_url=url)
        self.assertEqual(
            connections.endpoint("http://127.0.0.1:1234/v1"), "http://127.0.0.1:1234/v1"
        )

    def test_explicit_image_challenge_records_scoped_capability_and_revision_revokes_it(
        self,
    ):
        from web_models import WebModels
        from types import SimpleNamespace

        bridge = WebModels()
        bridge._runtime = SimpleNamespace(_p=lambda: SimpleNamespace(slug="alice"))
        row = self.save(role="vision", data_scopes=["selected_content"])
        request = smart_router.ModelRequest(
            owner="alice",
            profile="vision",
            data_scope="selected_content",
            features=frozenset({"vision"}),
        )
        self.assertFalse(smart_router.plan(request).candidates)
        response = Mock(status_code=200, headers={})
        response.json.return_value = {
            "choices": [{"message": {"content": "77777777"}, "finish_reason": "stop"}]
        }
        with (
            patch("secrets.choice", return_value="7"),
            patch.object(
                provider_protocols.requests, "request", return_value=response
            ) as send,
        ):
            result = bridge.router_connection_vision_test(row["id"], True, "alice")
        self.assertTrue(result["ok"])
        send.assert_called_once()
        body = send.call_args.kwargs["json"]
        parts = body["messages"][-1]["content"]
        self.assertTrue(
            parts[1]["image_url"]["url"].startswith("data:image/png;base64,iVBOR")
        )
        self.assertNotIn("77777777", parts[0]["text"])
        self.assertEqual(
            smart_router.plan(request).candidates[0].connection_id, row["id"]
        )
        self.save(id=row["id"], role="vision", data_scopes=["selected_content"])
        self.assertFalse(smart_router.plan(request).candidates)

    def test_wrong_image_answer_or_missing_explicit_preference_never_qualifies_vision(
        self,
    ):
        from web_models import WebModels
        from types import SimpleNamespace

        bridge = WebModels()
        bridge._runtime = SimpleNamespace(_p=lambda: SimpleNamespace(slug="alice"))
        row = self.save(role="vision", data_scopes=["selected_content"])
        with patch.object(provider_protocols.requests, "request") as send:
            with self.assertRaises(ValueError):
                bridge.router_connection_vision_test(row["id"], False, "alice")
            send.assert_not_called()
            send.return_value.status_code = 200
            send.return_value.headers = {}
            send.return_value.json.return_value = {
                "choices": [{"message": {"content": "wrong"}, "finish_reason": "stop"}]
            }
            with self.assertRaises(ValueError):
                bridge.router_connection_vision_test(row["id"], True, "alice")
        self.assertFalse(
            connections.vision_ready("alice", connections.records("alice")[row["id"]])
        )

    def test_same_custom_account_shares_quota_across_owner_connection_ids(self):
        rows = [
            connections.save(
                owner, {**self.record, "daily_requests": 1}, secret="shared-key"
            )
            for owner in ("alice", "bob")
        ]
        router_quota.reserve_custom(
            "alice", rows[0]["id"], rows[0]["revision"], directory=self.root / "router"
        )
        with self.assertRaises(router_quota.ReservationExhausted):
            router_quota.reserve_custom(
                "bob",
                rows[1]["id"],
                rows[1]["revision"],
                directory=self.root / "router",
            )

    def test_custom_daily_ceiling_is_real_sqlite_and_does_not_reset_with_model_change(
        self,
    ):
        row = self.save()
        directory = self.root / "router"
        router_quota.reserve_custom(
            "alice", row["id"], row["revision"], directory=directory
        )
        row = self.save(id=row["id"], model="other-model")
        router_quota.reserve_custom(
            "alice", row["id"], row["revision"], directory=directory
        )
        with self.assertRaises(router_quota.ReservationExhausted):
            router_quota.reserve_custom(
                "alice", row["id"], row["revision"], directory=directory
            )

    def test_old_paid_keys_are_preserved_and_migrated_disabled_without_network(self):
        folder = self.root / "keys"
        folder.mkdir()
        secret = folder / "alice.openai.txt"
        secret.write_text("protected:old-secret", encoding="utf-8")
        (folder / "alice.openai.json").write_text(
            json.dumps({"model": "old-model"}), encoding="utf-8"
        )
        user_models._write("alice", provider="openai")
        with patch.object(
            provider_protocols.requests,
            "request",
            side_effect=AssertionError("migration sent HTTP"),
        ):
            rows = connections.snapshot("alice")
            choice = user_models.choice("alice")
        self.assertEqual(secret.read_text(encoding="utf-8"), "protected:old-secret")
        self.assertEqual(rows[0]["protocol"], "responses")
        self.assertFalse(rows[0]["enabled"])
        self.assertTrue(rows[0]["migration_pending"])
        self.assertEqual(choice["provider"], "auto")

    def test_resolve_never_pairs_a_new_secret_with_an_old_endpoint_snapshot(self):
        row = self.save()
        old = user_models.routing("alice")
        self.save(id=row["id"], base_url="https://other.example.org/v1")
        new = user_models.routing("alice")
        new["secrets"][row["id"]] = "protected:new-key"
        with patch.object(user_models, "routing", side_effect=[old, old, new]):
            connection, key = connections.resolve(
                "alice", row["id"], revision=row["revision"]
            )
        self.assertEqual(
            connection["base_url"], old["connections"][row["id"]]["base_url"]
        )
        self.assertEqual(key, "secret-alice")

    def test_single_protocol_attempt_pins_endpoint_model_secret_and_reports_real_usage(
        self,
    ):
        row = self.save()
        record, secret = connections.resolve("alice", row["id"])
        response = Mock(status_code=200, headers={})
        response.json.return_value = {
            "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 5,
                "completion_tokens_details": {"reasoning_tokens": 2},
            },
        }
        with patch.object(
            provider_protocols.requests, "request", return_value=response
        ) as send:
            answer = provider_protocols.generate(
                "alice", record, secret, [{"role": "user", "content": "Test"}], "", 20
            )
        send.assert_called_once()
        self.assertEqual(
            send.call_args.args, ("POST", "https://api.example.org/v1/chat/completions")
        )
        self.assertFalse(send.call_args.kwargs["allow_redirects"])
        self.assertEqual(send.call_args.kwargs["json"]["model"], "actual-model")
        self.assertEqual(answer.usage["reasoning_tokens"], 2)


if __name__ == "__main__":
    unittest.main()
