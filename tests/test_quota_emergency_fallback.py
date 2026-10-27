"""Quota fallback regressions. No live provider calls."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from modules import smart_router as router, llm


class QuotaEmergencyFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        for target,value in [('_STORE',Path(self.tmp.name)),('_HEALTH',{}),('_LAST',{})]:
            p=patch.object(router,target,value);p.start();self.addCleanup(p.stop)
        p=patch.object(router.privacy,'mode',return_value='normal');p.start();self.addCleanup(p.stop)
        p=patch.object(llm,'user_key',return_value='gem-key');p.start();self.addCleanup(p.stop)
        p=patch.object(llm,'user_groq_key',return_value='groq-key');p.start();self.addCleanup(p.stop)
        p=patch.object(router.privacy,'protect',side_effect=lambda s:'enc:'+s);p.start();self.addCleanup(p.stop)
        p=patch.object(router.privacy,'unprotect',side_effect=lambda s:s.removeprefix('enc:'));p.start();self.addCleanup(p.stop)

    def allow(self, provider, model):
        now=router.time.time()
        router.set_free_tier_evidence(
            'alice',provider=provider,model=model,free_tier_verified=True,source='test-fixture',
            evidence_ref='test://official-free-tier',verified_at=now,ttl_seconds=3600,
            eligibility='eligible',quota_state='available',quota_remaining=10,
            hard_stop_guaranteed=True,verification_status='verified',reason='quota fallback fixture')

    def allow_main_pool(self):
        self.allow('gemini',llm.active_model('alice'))
        self.allow('groq',llm.groq_model())

    def test_configured_free_openrouter_is_last_resort_after_main_pool(self):
        router.configure('alice',True,key='or-key',model='openrouter/free')
        self.allow_main_pool();self.allow('openrouter','openrouter/free')
        call=Mock(side_effect=[RuntimeError('429 quota'),RuntimeError('429 quota'),RuntimeError('ollama down'),'openrouter answer'])
        self.assertEqual(router.run('alice','araştırma raporu',call),'openrouter answer')
        self.assertEqual([c.args[0] for c in call.call_args_list],['gemini','groq','ollama','openrouter'])
        self.assertEqual(router.status('alice')['last']['provider'],'openrouter')
        self.assertNotIn('openrouter',router.candidates('alice','analysis'))

    def test_emergency_route_is_not_used_without_confirmation_or_key(self):
        call=Mock(side_effect=[RuntimeError('a'),RuntimeError('b'),RuntimeError('c')])
        with self.assertRaises(RuntimeError):router.run('alice','araştırma raporu',call)
        self.assertNotIn('openrouter',[c.args[0] for c in call.call_args_list])
        router.configure('alice',True)
        call=Mock(side_effect=[RuntimeError('a'),RuntimeError('b'),RuntimeError('c')])
        with self.assertRaises(RuntimeError):router.run('alice','araştırma raporu',call)
        self.assertNotIn('openrouter',[c.args[0] for c in call.call_args_list])

    def test_local_privacy_never_uses_emergency_cloud(self):
        router.configure('alice',True,key='or-key',model='openrouter/free')
        self.allow('openrouter','openrouter/free')
        with patch.object(router.privacy,'mode',return_value='yerel'):
            call=Mock(side_effect=RuntimeError('ollama down'))
            with self.assertRaises(RuntimeError):router.run('alice','araştırma raporu',call)
        self.assertEqual([c.args[0] for c in call.call_args_list],['ollama'])

    def test_paid_openrouter_model_cannot_be_configured_for_emergency(self):
        with self.assertRaises(ValueError):router.configure('alice',True,key='or-key',model='openai/gpt-paid')
        router.configure('alice',True,key='or-key',model='vendor/model:free')
        self.allow('openrouter','vendor/model:free')
        self.assertTrue(router._free_emergency('alice',[]))

    def test_paid_providers_never_enter_automatic_attempts(self):
        router.configure('alice',True,key='or-key',model='openrouter/free')
        self.allow_main_pool();self.allow('openrouter','openrouter/free')
        call=Mock(side_effect=[RuntimeError('a'),RuntimeError('b'),RuntimeError('c'),RuntimeError('d')])
        with self.assertRaises(RuntimeError):router.run('alice','kod hatasını düzelt',call)
        names=[c.args[0] for c in call.call_args_list]
        self.assertEqual(names,['gemini','groq','ollama','openrouter'])
        self.assertNotIn('openai',names);self.assertNotIn('anthropic',names)


if __name__=='__main__':
    unittest.main()
