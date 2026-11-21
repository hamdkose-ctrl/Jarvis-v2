"""Quota fallback regressions. No live provider calls. OpenRouter and the emergency route are gone."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from modules import smart_router as router, llm


class QuotaFallbackTests(unittest.TestCase):
    def setUp(self):
        p=patch.object(llm,'_ollama_effective_model',return_value='local-test');p.start();self.addCleanup(p.stop)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        for target,value in [('_STORE',Path(self.tmp.name)),('_HEALTH',{})]:
            p=patch.object(router,target,value);p.start();self.addCleanup(p.stop)
        p=patch.object(router.privacy,'mode',return_value='normal');p.start();self.addCleanup(p.stop)
        p=patch.object(llm,'user_key',return_value='gem-key');p.start();self.addCleanup(p.stop)
        p=patch.object(llm,'user_groq_key',return_value='groq-key');p.start();self.addCleanup(p.stop)

    def allow_main_pool(self):
        router.configure('alice', gemini_scopes=[])

    def test_exhausted_pool_stops_at_the_configured_chain_with_no_extra_route(self):
        self.allow_main_pool()
        call=Mock(side_effect=[RuntimeError('429 quota'),RuntimeError('429 quota'),RuntimeError('ollama down')])
        with self.assertRaises(RuntimeError):router.run_request(router.ModelRequest(owner='alice',profile='conversation' ,route='PUBLIC_RESEARCH'),lambda spec, callback=call:callback(spec.provider)).text
        self.assertEqual([c.args[0] for c in call.call_args_list],['gemini','groq'])

    def test_private_chain_never_falls_to_gemini(self):
        self.allow_main_pool()
        private=Mock(side_effect=[RuntimeError('429'),RuntimeError('down')])
        with self.assertRaises(RuntimeError):router.run_request(router.ModelRequest(owner='alice',profile='conversation'),lambda spec, callback=private:callback(spec.provider)).text
        self.assertEqual([c.args[0] for c in private.call_args_list],['groq','ollama'])

    def test_paid_providers_never_enter_automatic_attempts(self):
        self.allow_main_pool()
        call=Mock(side_effect=[RuntimeError('a'),RuntimeError('b'),RuntimeError('c')])
        with self.assertRaises(RuntimeError):router.run_request(router.ModelRequest(owner='alice',profile='conversation' ,route='PUBLIC_RESEARCH'),lambda spec, callback=call:callback(spec.provider)).text
        names=[c.args[0] for c in call.call_args_list]
        self.assertEqual(names,['gemini','groq'])
        self.assertNotIn('openai',names);self.assertNotIn('anthropic',names)

    def test_local_privacy_never_uses_cloud(self):
        self.allow_main_pool()
        with patch.object(router.privacy,'mode',return_value='yerel'):
            call=Mock(side_effect=RuntimeError('ollama down'))
            with self.assertRaises(RuntimeError):router.run_request(router.ModelRequest(owner='alice',profile='conversation'),lambda spec, callback=call:callback(spec.provider)).text
        self.assertEqual([c.args[0] for c in call.call_args_list],['ollama'])

    def test_without_an_api_key_only_local_is_tried(self):
        call=Mock(side_effect=[RuntimeError('a')])
        with patch.object(llm,'user_groq_key',return_value=''), self.assertRaises(RuntimeError):router.run_request(router.ModelRequest(owner='alice',profile='conversation'),lambda spec, callback=call:callback(spec.provider)).text
        self.assertEqual([c.args[0] for c in call.call_args_list],['ollama'])


if __name__=='__main__':
    unittest.main()
