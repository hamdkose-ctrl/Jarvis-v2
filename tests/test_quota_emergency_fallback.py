"""Quota fallback regressions. No live provider calls. OpenRouter and the emergency route are gone."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from modules import smart_router as router, llm
from provider_fixture import fresh_bundle


class QuotaFallbackTests(unittest.TestCase):
    def setUp(self):
        fresh_bundle(self)
        p=patch.object(llm,'_ollama_effective_model',return_value='local-test');p.start();self.addCleanup(p.stop)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        for target,value in [('_STORE',Path(self.tmp.name)),('_HEALTH',{}),('_LAST',{})]:
            p=patch.object(router,target,value);p.start();self.addCleanup(p.stop)
        p=patch.object(router.privacy,'mode',return_value='normal');p.start();self.addCleanup(p.stop)
        p=patch.object(llm,'user_key',return_value='gem-key');p.start();self.addCleanup(p.stop)
        p=patch.object(llm,'user_groq_key',return_value='groq-key');p.start();self.addCleanup(p.stop)

    def allow(self, provider, model):
        now=router.time.time()
        router.set_free_tier_evidence(
            'alice',provider=provider,model=model,free_tier_verified=True,source='test-fixture',
            evidence_ref='test://official-free-tier',verified_at=now,ttl_seconds=3600,
            eligibility='eligible',quota_state='available',quota_remaining=10,
            hard_stop_guaranteed=True,verification_status='verified',reason='quota fallback fixture')

    def allow_main_pool(self):
        router.configure('alice',True)
        self.allow('gemini',llm.active_model('alice'))
        self.allow('groq',llm.groq_model())

    def test_exhausted_pool_stops_at_the_configured_chain_with_no_extra_route(self):
        self.allow_main_pool()
        call=Mock(side_effect=[RuntimeError('429 quota'),RuntimeError('429 quota'),RuntimeError('ollama down')])
        with self.assertRaises(RuntimeError):router.run('alice','araştırma raporu',call,route='PUBLIC_RESEARCH')
        self.assertEqual([c.args[0] for c in call.call_args_list],['gemini','groq'])

    def test_private_chain_never_falls_to_gemini(self):
        self.allow_main_pool()
        private=Mock(side_effect=[RuntimeError('429'),RuntimeError('down')])
        with self.assertRaises(RuntimeError):router.run('alice','özel not',private)
        self.assertEqual([c.args[0] for c in private.call_args_list],['groq','ollama'])

    def test_paid_providers_never_enter_automatic_attempts(self):
        self.allow_main_pool()
        call=Mock(side_effect=[RuntimeError('a'),RuntimeError('b'),RuntimeError('c')])
        with self.assertRaises(RuntimeError):router.run('alice','kod hatasını düzelt',call,route='PUBLIC_RESEARCH')
        names=[c.args[0] for c in call.call_args_list]
        self.assertEqual(names,['gemini','groq'])
        self.assertNotIn('openai',names);self.assertNotIn('anthropic',names)

    def test_local_privacy_never_uses_cloud(self):
        self.allow_main_pool()
        with patch.object(router.privacy,'mode',return_value='yerel'):
            call=Mock(side_effect=RuntimeError('ollama down'))
            with self.assertRaises(RuntimeError):router.run('alice','araştırma raporu',call)
        self.assertEqual([c.args[0] for c in call.call_args_list],['ollama'])

    def test_without_confirmation_only_local_is_tried(self):
        call=Mock(side_effect=[RuntimeError('a')])
        with self.assertRaises(RuntimeError):router.run('alice','araştırma raporu',call)
        self.assertEqual([c.args[0] for c in call.call_args_list],['ollama'])


if __name__=='__main__':
    unittest.main()
