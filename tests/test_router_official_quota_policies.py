"""Production POLICIES rows are dated official free-tier facts, not provider guesses.

Groq's rate-limits page publishes Free plan base RPM/RPD for the exact models
Jarvis routes. Gemini/Cloudflare publish no static free-tier request ceilings, so
those providers must stay policy-less. This suite guards the registry itself and
the request-count window math against the REAL entries; reserve() mechanics with
injected synthetic policies live in test_router_atomic_quota.py.
"""
import contextlib
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from modules import llm, router_quota as quota

GROQ_TEXT_MODELS = ('openai/gpt-oss-120b', 'openai/gpt-oss-20b', 'qwen/qwen3.8-27b')
OFFICIAL = 'https://console.groq.com/docs/rate-limits'
# Inside the verified/expired interval of every shipped entry (16→23 Nov 2026).
IN_WINDOW = 1794900000.0


class OfficialRegistryGuardTests(unittest.TestCase):
    def test_every_routed_groq_text_model_carries_the_official_base_caps(self):
        self.assertEqual(tuple(llm.GROQ_MODELS), GROQ_TEXT_MODELS)
        for model in GROQ_TEXT_MODELS:
            with self.subTest(model=model):
                self.assertEqual(quota._policy('groq', model, IN_WINDOW), (30, 1000, None, None))

    def test_no_unverified_provider_or_extra_model_is_silently_governed(self):
        self.assertEqual({key for key in quota.POLICIES},
                         {('groq', model) for model in GROQ_TEXT_MODELS})

    def test_each_entry_is_https_official_source_inside_a_limited_window(self):
        now = time.time()
        for (provider, model), row in quota.POLICIES.items():
            with self.subTest(provider=provider, model=model):
                self.assertEqual(row['source_url'], OFFICIAL)
                self.assertLessEqual(row['verified_at'], now, 'gelecekte doğrulanmış kota')
                self.assertGreater(row['expires_at'], now,
                                   'süresi dolmuş kota: resmî sayfadan yeniden doğrula')
                self.assertLessEqual(row['expires_at'] - row['verified_at'], 31 * 86400)

    def test_token_caps_are_not_reserved_without_a_trusted_upper_bound(self):
        # Groq Free TPM exists (8K) but no caller provides ModelRequest.token_budget;
        # a tpm policy without it would fail-closed every Groq send.
        for (provider, model), row in quota.POLICIES.items():
            with self.subTest(provider=provider, model=model):
                self.assertNotIn('tpm', row)
                self.assertNotIn('tpd', row)


class RealEntryReservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def reserve(self, owner='alice', model='openai/gpt-oss-120b', now=IN_WINDOW, **kwargs):
        return quota.reserve(owner, 'groq', model, directory=self.dir, now=now, **kwargs)

    def seed(self, stamps, owner='alice', model='openai/gpt-oss-120b', units=-1):
        with contextlib.closing(sqlite3.connect(self.dir / 'atomic_requests.sqlite3')) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS requests (owner TEXT NOT NULL,'
                       ' provider TEXT NOT NULL, model TEXT NOT NULL, stamp REAL NOT NULL,'
                       ' token_units INTEGER NOT NULL DEFAULT -1, quota_scope TEXT,'
                       ' attempt_id TEXT, cost_units INTEGER, actual_tokens INTEGER)')
            db.executemany('INSERT INTO requests(owner,provider,model,stamp,token_units)'
                           ' VALUES(?,?,?,?,?)',
                           [(owner, 'groq', model, stamp, units) for stamp in stamps])

    def test_thirtieth_request_passes_and_the_next_minute_slot_waits_shortly(self):
        for index in range(30):
            self.assertTrue(self.reserve(now=IN_WINDOW + index * 0.5))
        with self.assertRaises(quota.ReservationExhausted) as caught:
            self.reserve(now=IN_WINDOW + 10)
        self.assertEqual(caught.exception.reason_code, 'PROVIDER_LOCAL_QUOTA_EXHAUSTED')
        self.assertLessEqual(caught.exception.retry_after, 60)
        self.assertTrue(self.reserve(now=IN_WINDOW + 61))

    def test_rolling_day_window_blocks_at_one_thousand_even_when_the_minute_is_free(self):
        self.seed([IN_WINDOW - 100 - index * 85 for index in range(1000)])
        with self.assertRaises(quota.ReservationExhausted) as caught:
            self.reserve()
        self.assertLessEqual(caught.exception.retry_after, 86400)
        self.assertTrue(self.reserve(now=IN_WINDOW + caught.exception.retry_after + 5))

    def test_unknown_token_rows_from_the_legacy_schema_do_not_block_a_request_only_policy(self):
        self.seed([IN_WINDOW - 300], units=-1)
        self.assertTrue(self.reserve())

    def test_one_shared_org_scope_spends_one_budget_across_local_users(self):
        for index in range(29):
            self.assertTrue(self.reserve(now=IN_WINDOW + index * 0.5,
                                         quota_scope='project:shared-org'))
        self.assertTrue(self.reserve(owner='bob', now=IN_WINDOW + 15,
                                     quota_scope='project:shared-org'))
        with self.assertRaises(quota.ReservationExhausted):
            self.reserve(owner='carol', now=IN_WINDOW + 20, quota_scope='project:shared-org')
        self.assertTrue(self.reserve(owner='carol', now=IN_WINDOW + 20,
                                     quota_scope='project:other-org'))

    def test_expired_entry_blocks_before_any_network_send(self):
        row = dict(quota.POLICIES[('groq', 'openai/gpt-oss-120b')])
        row.update(verified_at=int(time.time()) - 20 * 86400, expires_at=int(time.time()) - 3600)
        with patch.dict(quota.POLICIES, {('groq', 'openai/gpt-oss-120b'): row}):
            with self.assertRaises(quota.ReservationUnavailable):
                quota.reserve('alice', 'groq', 'openai/gpt-oss-120b', directory=self.dir)

    def test_future_dated_or_overlong_review_window_is_not_trusted(self):
        base = dict(quota.POLICIES[('groq', 'openai/gpt-oss-120b')])
        for bad, label in (({'verified_at': int(time.time()) + 3600}, 'future verify'),
                           ({'expires_at': base['verified_at'] + 40 * 86400}, 'overlong span')):
            with self.subTest(case=label):
                row = dict(base)
                row.update(bad)
                with patch.dict(quota.POLICIES, {('groq', 'openai/gpt-oss-120b'): row}):
                    with self.assertRaises(quota.ReservationUnavailable):
                        quota.reserve('alice', 'groq', 'openai/gpt-oss-120b',
                                      directory=self.dir, now=time.time())


class RoutedGroqFlowUsesTheOfficialPolicyTests(unittest.TestCase):
    def setUp(self):
        from modules import smart_router
        self.smart_router = smart_router
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.dir = directory
        self.enterContext(patch.object(smart_router, '_STORE', directory))
        self.enterContext(patch.object(smart_router, '_HEALTH', {}))
        from modules import llm
        self.llm = llm
        self.enterContext(patch.object(llm, '_rate_limited', {}))
        self.enterContext(patch.object(llm, 'user_groq_key', return_value='fixture-key'))
        self.enterContext(patch.object(llm.privacy, 'mode', return_value='normal'))
        self.request = smart_router.ModelRequest(owner='alice', profile='conversation',
                                                 max_output_tokens=2048)
        self.spec = smart_router.ModelSpec('groq', 'openai/gpt-oss-120b')
        self.plan = smart_router.RoutePlan((self.spec,), (), 2)

    def send(self):
        result = self.llm.requests.Response()
        result.status_code = 200
        import json
        result._content = json.dumps({
            'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 4, 'completion_tokens': 3, 'total_tokens': 7}}).encode()
        return result

    def seed_minute_rows(self, count):
        base = time.time()
        with contextlib.closing(sqlite3.connect(self.dir / 'atomic_requests.sqlite3')) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS requests (owner TEXT NOT NULL,'
                       ' provider TEXT NOT NULL, model TEXT NOT NULL, stamp REAL NOT NULL,'
                       ' token_units INTEGER NOT NULL DEFAULT -1, quota_scope TEXT,'
                       ' attempt_id TEXT, cost_units INTEGER, actual_tokens INTEGER)')
            db.executemany('INSERT INTO requests(owner,provider,model,stamp,token_units)'
                           ' VALUES(?,?,?,?,?)',
                           [('alice', 'groq', 'openai/gpt-oss-120b', base - index * 0.1, -1)
                            for index in range(count)])

    def test_routed_groq_flow_sends_the_thirtieth_and_blocks_locally_on_the_next(self):
        from modules import failure_policy
        self.seed_minute_rows(29)
        with patch.object(self.smart_router, 'plan', return_value=self.plan), \
                patch.object(self.llm.requests, 'post', return_value=self.send()) as post:
            self.assertEqual(self.smart_router.run_request(
                self.request, lambda spec: self.llm.dispatch(
                    self.request, spec, 'synthetic input', 'synthetic system')).text,
                '{"ok":true}')
            self.assertEqual(post.call_count, 1)
            with self.assertRaises(failure_policy.ProviderExhaustedError) as caught:
                self.smart_router.run_request(
                    self.request, lambda spec: self.llm.dispatch(
                        self.request, spec, 'synthetic input', 'synthetic system'))
            self.assertEqual(post.call_count, 1)
            self.assertIn('Yerel model istek rezervasyon limiti doldu', str(caught.exception))
            self.assertIn('Ücretli modele geçilmedi', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
