import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modules import llm, smart_router as router
from provider_fixture import fresh_bundle


class FreeTierEvidenceRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target, value in [('_STORE', Path(self.tmp.name)), ('_HEALTH', {})]:
            p = patch.object(router, target, value)
            p.start(); self.addCleanup(p.stop)
        for target, name, value in [
            (router.privacy, 'mode', 'normal'),
            (llm, 'user_key', 'gem-key'),
            (llm, 'user_groq_key', 'groq-key'),
            (llm, 'active_model', 'gem-model'),
            (llm, 'groq_model', 'groq-model'),
        ]:
            p = patch.object(target, name, return_value=value)
            p.start(); self.addCleanup(p.stop)
        p = patch.object(router.privacy, 'protect', side_effect=lambda s: 'enc:' + s)
        p.start(); self.addCleanup(p.stop)
        p = patch.object(router.privacy, 'unprotect', side_effect=lambda s: s.removeprefix('enc:'))
        p.start(); self.addCleanup(p.stop)
        self.now = 1_794_700_000.0  # inside the provider privacy bundle window
        p = patch.object(router.time, 'time', return_value=self.now)
        p.start(); self.addCleanup(p.stop)

        fresh_bundle(self)
        router.configure('alice', True)

    def evidence(self, provider, model, **overrides):
        row = dict(
            provider=provider,
            model=model,
            free_tier_verified=True,
            source='official_provider_docs',
            evidence_ref='https://example.invalid/free-tier',
            verified_at=self.now - 60,
            ttl_seconds=3600,
            eligibility='eligible',
            quota_state='available',
            quota_remaining=10,
            hard_stop_guaranteed=True,
            verification_status='verified',
            reason='official free tier with hard stop',
        )
        row.update(overrides)
        return router.set_free_tier_evidence('alice', **row)

    def skip(self, provider, task='chat', route=None):
        return next(row for row in router.selection('alice', task, route)['skipped'] if row['provider'] == provider)

    def test_valid_evidence_allows_only_verified_cloud_route(self):
        self.evidence('groq', 'groq-model')
        self.assertEqual(router.candidates('alice', 'chat'), ['groq', 'ollama'])
        self.assertEqual(self.skip('gemini')['reason_code'], 'PROVIDER_ROUTE_NOT_ALLOWED')   # PRIVATE zincirde Gemini yok
        missing = self.skip('gemini', route='PUBLIC_RESEARCH')
        self.assertEqual(missing['reason_code'], 'PROVIDER_FREE_TIER_EVIDENCE_MISSING')
        self.assertIn('kanıt', missing['reason'].casefold())

    def test_confirmation_without_evidence_fails_closed(self):
        self.assertEqual(router.candidates('alice', 'chat'), ['ollama'])
        row = self.skip('groq')
        self.assertEqual(row['reason_code'], 'PROVIDER_FREE_TIER_EVIDENCE_MISSING')
        self.assertNotIn('openai', router.candidates('alice', 'code'))
        self.assertNotIn('anthropic', router.candidates('alice', 'code'))

    def test_stale_evidence_requires_revalidation(self):
        self.evidence('groq', 'groq-model', verified_at=self.now - 7200, ttl_seconds=300)
        self.assertNotIn('groq', router.candidates('alice', 'chat'))
        row = self.skip('groq')
        self.assertEqual(row['reason_code'], 'PROVIDER_FREE_TIER_EVIDENCE_STALE')
        self.assertIn('yeniden doğrulama', row['reason'].casefold())

    def test_unverified_or_ineligible_evidence_never_allows_cloud(self):
        self.evidence('groq', 'groq-model', free_tier_verified=False, verification_status='unknown')
        self.assertEqual(self.skip('groq')['reason_code'], 'PROVIDER_FREE_TIER_EVIDENCE_MISSING')
        self.evidence('groq', 'groq-model', eligibility='not_eligible')
        self.assertEqual(self.skip('groq')['reason_code'], 'PROVIDER_FREE_TIER_NOT_ELIGIBLE')

    def test_hard_stop_must_be_verified(self):
        self.evidence('groq', 'groq-model', hard_stop_guaranteed=False)
        self.assertNotIn('groq', router.candidates('alice', 'chat'))
        self.assertEqual(self.skip('groq')['reason_code'], 'PROVIDER_FREE_TIER_HARD_STOP_UNVERIFIED')

    def test_exhausted_quota_skips_to_next_verified_free_provider(self):
        self.evidence('groq', 'groq-model', quota_state='exhausted', quota_remaining=0)
        self.evidence('gemini', 'gem-model')
        self.assertEqual(router.candidates('alice', 'chat', route='PUBLIC_RESEARCH'), ['gemini', 'ollama'])
        row = self.skip('groq')
        self.assertEqual(row['reason_code'], 'PROVIDER_FREE_TIER_QUOTA_EXHAUSTED')
        self.assertIn('kota', row['reason'].casefold())

    def test_evidence_is_persisted_with_provenance_and_expiry(self):
        saved = self.evidence('groq', 'groq-model')
        self.assertEqual(saved['provider'], 'groq')
        self.assertEqual(saved['source'], 'official_provider_docs')
        self.assertEqual(saved['evidence_ref'], 'https://example.invalid/free-tier')
        self.assertEqual(saved['expires_at'], self.now - 60 + 3600)
        raw = json.loads(router.owner_path('alice').read_text(encoding='utf-8'))
        self.assertEqual(raw['free_tier_evidence']['groq']['groq-model']['verification_status'], 'verified')


if __name__ == '__main__':
    unittest.main()
