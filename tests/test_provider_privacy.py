import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from modules import cloudflare_chat, provider_privacy as pp, smart_router as router

ROOT = pathlib.Path(__file__).resolve().parent.parent
INSIDE = pp._VERIFIED_AT + 3600
PUB, PRIV = pp.ROUTE_PUBLIC_RESEARCH, pp.ROUTE_PRIVATE_GENERAL


class BundleTests(unittest.TestCase):
    def test_groq_and_cloudflare_serve_both_routes(self):
        for provider in ("groq", "cloudflare"):
            for route in (PUB, PRIV, None):
                self.assertTrue(pp.privacy_gate(provider, route, now=INSIDE)["ok"], (provider, route))

    def test_gemini_is_public_research_only(self):
        self.assertTrue(pp.privacy_gate("gemini", PUB, now=INSIDE)["ok"])
        denied = pp.privacy_gate("gemini", PRIV, now=INSIDE)
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["reason_code"], "PROVIDER_ROUTE_NOT_ALLOWED")

    def test_training_provider_requires_an_explicit_route(self):
        denied = pp.privacy_gate("gemini", None, now=INSIDE)
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["reason_code"], "PROVIDER_ROUTE_REQUIRED")
        forged = {"nvidia_like": dict(pp.PROVIDER_BUNDLE["gemini"])}
        self.assertEqual(pp.privacy_gate("nvidia_like", None, now=INSIDE, bundle=forged)["reason_code"],
                         "PROVIDER_ROUTE_REQUIRED")
        self.assertTrue(pp.privacy_gate("gemini", PUB, now=INSIDE)["ok"])

    def test_training_provider_never_serves_private_even_if_listed(self):
        bundle = {"x": dict(pp.PROVIDER_BUNDLE["gemini"], allowed_routes=(PUB, PRIV))}
        self.assertFalse(pp.privacy_gate("x", PRIV, now=INSIDE, bundle=bundle)["ok"])
        self.assertTrue(pp.privacy_gate("x", PUB, now=INSIDE, bundle=bundle)["ok"])

    def test_nvidia_is_excluded_everywhere_even_with_a_forged_bundle_entry(self):
        forged = {"nvidia": dict(pp.PROVIDER_BUNDLE["groq"]), "nvidia_nim": dict(pp.PROVIDER_BUNDLE["groq"])}
        for name in ("nvidia", "nvidia_nim"):
            for route in (PUB, PRIV, None):
                result = pp.privacy_gate(name, route, now=INSIDE, bundle=forged)
                self.assertEqual(result["reason_code"], "PROVIDER_PRIVACY_EXCLUDED", (name, route))
        for chain in pp.CHAINS.values():
            self.assertFalse(set(chain) & pp.EXCLUDED_PROVIDERS)

    def test_unknown_and_malformed_providers_are_not_eligible(self):
        for name in ("openrouter", "openai", "", "GROQ", None, 5, ("groq",)):
            self.assertFalse(pp.privacy_gate(name, PUB, now=INSIDE)["ok"], repr(name))

    def test_stale_evidence_is_not_eligible(self):
        late = pp._EXPIRES_AT + 1
        for provider in ("groq", "cloudflare", "gemini"):
            result = pp.privacy_gate(provider, PUB, now=late)
            self.assertEqual(result["reason_code"], "PROVIDER_PRIVACY_EVIDENCE_STALE", provider)

    def test_missing_source_url_or_ref_is_not_eligible(self):
        for field, value in (("source_url", ""), ("source_url", None), ("source_url", "http://insecure"),
                             ("source_url", 7), ("evidence_ref", "")):
            bundle = {"x": dict(pp.PROVIDER_BUNDLE["groq"], **{field: value})}
            result = pp.privacy_gate("x", PUB, now=INSIDE, bundle=bundle)
            self.assertFalse(result["ok"], (field, value))
            self.assertEqual(result["reason_code"], "PROVIDER_PRIVACY_EVIDENCE_MISSING")

    def test_unknown_training_status_is_not_eligible(self):
        for value in (None, "false", 0, "unknown"):
            bundle = {"x": dict(pp.PROVIDER_BUNDLE["groq"], trains_on_data=value)}
            result = pp.privacy_gate("x", PUB, now=INSIDE, bundle=bundle)
            self.assertEqual(result["reason_code"], "PROVIDER_PRIVACY_TRAINING_UNKNOWN", repr(value))

    def test_missing_timestamps_and_bad_route_lists_are_not_eligible(self):
        base = pp.PROVIDER_BUNDLE["groq"]
        for change in ({"expires_at": None}, {"verified_at": "x"}, {"allowed_routes": None},
                       {"allowed_routes": ("PUBLIC",)}, {"allowed_routes": ("ANYTHING",)}):
            bundle = {"x": dict(base, **change)}
            self.assertFalse(pp.privacy_gate("x", PUB, now=INSIDE, bundle=bundle)["ok"], change)

    def test_unknown_route_is_denied(self):
        for route in ("PUBLIC", "private", "", 3):
            self.assertFalse(pp.privacy_gate("groq", route, now=INSIDE)["ok"], repr(route))

    def test_bundle_content_is_sound(self):
        for name, facts in pp.PROVIDER_BUNDLE.items():
            self.assertTrue(facts["source_url"].startswith("https://"), name)
            self.assertGreater(facts["expires_at"], facts["verified_at"], name)
            self.assertIs(type(facts["trains_on_data"]), bool, name)
            self.assertTrue(facts["free_no_card"], name)

    def test_chains_follow_policy(self):
        self.assertEqual(pp.CHAINS[PUB], ("gemini", "groq", "cloudflare", "ollama"))
        self.assertEqual(pp.CHAINS[PRIV], ("groq", "cloudflare", "ollama"))
        self.assertNotIn("gemini", pp.CHAINS[PRIV])
        for chain in pp.CHAINS.values():
            for name in chain:
                self.assertTrue(name == "ollama" or name in pp.PROVIDER_BUNDLE, name)
            self.assertNotIn("openrouter", chain)


class RouterGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target, value in [("_STORE", pathlib.Path(self.tmp.name)), ("_HEALTH", {}), ("_LAST", {})]:
            patcher = patch.object(router, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(router.time, "time", return_value=INSIDE)
        patcher.start()
        self.addCleanup(patcher.stop)

    def evidence(self, provider):
        return router.set_free_tier_evidence(
            "alice", provider=provider, model="m", free_tier_verified=True, source="test-fixture",
            evidence_ref="test://free-tier", verified_at=INSIDE - 60, ttl_seconds=3600,
            eligibility="eligible", quota_state="available", quota_remaining=5,
            hard_stop_guaranteed=True, verification_status="verified", reason="fixture")

    def test_cloudflare_is_a_recordable_cloud_provider(self):
        self.assertIn("cloudflare", router._CLOUD_PROVIDERS)
        self.evidence("cloudflare")
        self.assertTrue(router._evidence_gate("alice", "cloudflare", "m", route=PRIV)["ok"])

    def test_gate_without_route_denies_gemini(self):
        self.evidence("gemini")
        denied = router._evidence_gate("alice", "gemini", "m")
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["reason_code"], "PROVIDER_ROUTE_REQUIRED")

    def test_default_route_is_private_and_legacy_route_is_gone(self):
        self.assertEqual(router._DEFAULT_ROUTE, PRIV)
        self.assertFalse(hasattr(router, "_LEGACY_ROUTE"))

    def test_owner_evidence_alone_is_not_enough_without_privacy_bundle(self):
        with self.assertRaises(ValueError):
            self.evidence("openrouter")
        result = router._evidence_gate("alice", "openrouter", "m")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason_code"], "PROVIDER_PRIVACY_EVIDENCE_MISSING")

    def test_gemini_with_valid_owner_evidence_still_denied_for_private_route(self):
        self.evidence("gemini")
        self.assertTrue(router._evidence_gate("alice", "gemini", "m", route=PUB)["ok"])
        denied = router._evidence_gate("alice", "gemini", "m", route=PRIV)
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["reason_code"], "PROVIDER_ROUTE_NOT_ALLOWED")

    def test_expired_bundle_blocks_even_fresh_owner_evidence(self):
        self.evidence("groq")
        result = router._evidence_gate("alice", "groq", "m", now=pp._EXPIRES_AT + 10)
        self.assertEqual(result["reason_code"], "PROVIDER_PRIVACY_EVIDENCE_STALE")

    def test_owner_state_cannot_override_provider_privacy_facts(self):
        self.evidence("gemini")
        state = json.loads(router.owner_path("alice").read_text(encoding="utf-8"))
        state["free_tier_evidence"]["gemini"]["m"].update(trains_on_data=False, allowed_routes=[PUB, PRIV])
        router.owner_path("alice").write_text(json.dumps(state), encoding="utf-8")
        self.assertFalse(router._evidence_gate("alice", "gemini", "m", route=PRIV)["ok"])


class _Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code, self._payload, self.text, self.headers = status, payload, text, {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Session:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


class CloudflareChatTests(unittest.TestCase):
    def setUp(self):
        # All sessions below are HTTP fakes; unit tests must not write a real
        # user's usage ledger. Individual metering assertions override this mock.
        meter = patch.object(cloudflare_chat.usage_meter, 'record')
        meter.start()
        self.addCleanup(meter.stop)
        for name, value in (("user_cloudflare_account", "acc123"), ("user_cloudflare_token", "tok456")):
            patcher = patch.object(cloudflare_chat, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_chat(self, session, **kwargs):
        return cloudflare_chat.chat([{"role": "user", "content": "selam"}], "sistem", 64, slug="alice",
                                    _session=session, **kwargs)

    def test_success_builds_the_workers_ai_request(self):
        session = _Session(_Resp(payload={"result": {"response": "merhaba"}, "success": True}))
        self.assertEqual(self.run_chat(session), "merhaba")
        url, kwargs = session.calls[0]
        self.assertEqual(url, "https://api.cloudflare.com/client/v4/accounts/acc123/ai/run/" + cloudflare_chat.MODEL)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok456")
        body = json.loads(kwargs["data"])
        self.assertEqual(body["messages"][0], {"role": "system", "content": "sistem"})
        self.assertEqual(body["messages"][1], {"role": "user", "content": "selam"})
        self.assertEqual(body["max_tokens"], 64)

    def assert_error(self, session, code):
        with self.assertRaises(cloudflare_chat.CloudflareChatError) as ctx:
            self.run_chat(session)
        self.assertEqual(ctx.exception.reason_code, code)

    def test_typed_errors(self):
        self.assert_error(_Session(_Resp(401)), "AUTH_FAILED")
        self.assert_error(_Session(_Resp(429)), "QUOTA_EXCEEDED")
        self.assert_error(_Session(_Resp(500)), "PROVIDER_ERROR")
        self.assert_error(_Session(error=TimeoutError("t")), "NETWORK_ERROR")
        self.assert_error(_Session(_Resp(payload={"result": {}})), "UNEXPECTED_FORMAT")
        self.assert_error(_Session(_Resp(payload=None)), "UNEXPECTED_FORMAT")
        self.assert_error(_Session(_Resp(payload={"result": {"response": "  "}})), "EMPTY_RESPONSE")
        self.assert_error(_Session(_Resp(payload={"result": {"response": 5}})), "EMPTY_RESPONSE")

    def test_physical_http_attempt_has_exactly_one_owner_meter_entry(self):
        cases = [
            (_Session(_Resp(payload={"result": {"response": "ok"}})), 'ok', 2),
            (_Session(_Resp(status=401)), '401', 0),
            (_Session(_Resp(status=429)), '429', 0),
            (_Session(_Resp(payload=None)), 'bozuk', 0),
            (_Session(_Resp(payload={"result": {"response": "  "}})), 'bos', 0),
            (_Session(error=TimeoutError("network timeout")), 'baglanti', 0),
        ]
        for session, expected_result, expected_out in cases:
            with self.subTest(result=expected_result), \
                 patch.object(cloudflare_chat.usage_meter, 'record') as record:
                try:
                    self.run_chat(session)
                except cloudflare_chat.CloudflareChatError:
                    pass
                self.assertEqual(len(session.calls), 1)
                record.assert_called_once()
                args = record.call_args.args
                self.assertEqual(args[:2], ('cloudflare', cloudflare_chat.MODEL))
                self.assertEqual(args[2], len('sistem') + len('selam'))
                self.assertEqual(args[3], expected_out)
                self.assertEqual(args[4], expected_result)
                self.assertEqual(record.call_args.kwargs['owner'], 'alice')

    def test_cloudflare_no_network_means_no_usage_meter_record(self):
        session = _Session(_Resp(payload={"result": {"response": "ok"}}))
        with patch.object(cloudflare_chat, 'user_cloudflare_token', return_value=''), \
             patch.object(cloudflare_chat.usage_meter, 'record') as record:
            with self.assertRaises(cloudflare_chat.CloudflareChatError):
                self.run_chat(session)
        record.assert_not_called()
        self.assertEqual(session.calls, [])

    def test_missing_credentials_or_user_never_calls_the_network(self):
        session = _Session(_Resp(payload={"result": {"response": "x"}}))
        with patch.object(cloudflare_chat, "user_cloudflare_token", return_value=""):
            self.assert_error(session, "NO_KEY")
        with self.assertRaises(cloudflare_chat.CloudflareChatError) as ctx:
            cloudflare_chat.chat([{"role": "user", "content": "x"}], slug="", _session=session)
        self.assertEqual(ctx.exception.reason_code, "NO_USER")
        with self.assertRaises(cloudflare_chat.CloudflareChatError) as ctx:
            cloudflare_chat.chat([], slug="alice", _session=session)
        self.assertEqual(ctx.exception.reason_code, "EMPTY_PROMPT")
        self.assertEqual(session.calls, [])

    def test_max_tokens_is_bounded(self):
        session = _Session(_Resp(payload={"result": {"response": "ok"}}))
        cloudflare_chat.chat([{"role": "user", "content": "x"}], max_tokens=10**9, slug="alice", _session=session)
        self.assertEqual(json.loads(session.calls[0][1]["data"])["max_tokens"], 4096)

    def test_adapter_is_a_transport_only(self):
        text = (ROOT / "modules" / "cloudflare_chat.py").read_text(encoding="utf-8")
        for forbidden in ("import llm", "from modules import llm", "smart_router", "gemini", "groq", "ollama"):
            self.assertNotIn(forbidden, text.replace("Provider Routing Policy", ""), forbidden)


if __name__ == "__main__":
    unittest.main()
