"""User attestation is not independently verified billing evidence."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from modules import llm, smart_router as router
from web_models import WebModels


class FreeAccountConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for obj, name, value in [(router, '_STORE', Path(self.tmp.name)),
                                  (router, '_HEALTH', {}), (router, '_LAST', {})]:
            p = patch.object(obj, name, value); p.start(); self.addCleanup(p.stop)
        for obj, name, value in [(router.privacy, 'mode', 'normal'),
                                  (llm, 'user_key', 'gem-secret'),
                                  (llm, 'user_groq_key', 'groq-secret'),
                                  (llm, 'active_model', 'gem-model'),
                                  (llm, 'groq_model', 'groq-model'),
                                  (llm, 'ollama_models', [])]:
            p = patch.object(obj, name, return_value=value); p.start(); self.addCleanup(p.stop)

    def save_from_ui(self, confirmed=True):
        runtime = SimpleNamespace(_p=lambda: SimpleNamespace(slug='alice'),
                                  llm=llm, _live=lambda: SimpleNamespace(get=lambda: None))
        bridge = SimpleNamespace(_runtime=runtime)
        return WebModels.smart_router_save(bridge, '', None, confirmed)

    def test_ui_confirmation_opens_cloud_without_fabricating_evidence(self):
        self.save_from_ui()
        self.assertEqual(router.candidates('alice', 'chat'), ['groq', 'gemini', 'ollama'])
        raw = json.loads(router.owner_path('alice').read_text())
        self.assertEqual(raw['free_tier_evidence'], {})
        status = router.status('alice')
        policy = next(x['policy'] for x in status['capabilities'] if x['provider'] == 'gemini')
        self.assertIn('Kullanıcı beyanı', policy)
        self.assertNotIn('Kanıtlı ücretsiz', policy)
        self.assertNotIn('gem-secret', json.dumps(raw))
        self.assertNotIn('groq-secret', json.dumps(status))

    def test_key_change_requires_confirmation_for_only_that_provider(self):
        self.save_from_ui()
        with patch.object(llm, 'user_key', return_value='new-key'):
            self.assertEqual(router.candidates('alice', 'chat'), ['groq', 'ollama'])
            self.save_from_ui()
            self.assertIn('gemini', router.candidates('alice', 'chat'))

    def test_owner_revocation_and_restart_preserve_policy(self):
        self.save_from_ui()
        router._LAST.clear(); router._HEALTH.clear()
        self.assertIn('gemini', router.candidates('alice', 'chat'))
        self.assertEqual(router.candidates('bob', 'chat'), ['ollama'])
        self.save_from_ui(False)
        self.assertEqual(router.candidates('alice', 'chat'), ['ollama'])

    def test_old_checkbox_alone_is_not_silently_migrated(self):
        router.configure('alice', True)
        self.assertEqual(router.candidates('alice', 'chat'), ['ollama'])

    def test_no_key_at_confirmation_does_not_authorize_later_key(self):
        with patch.object(llm, 'user_key', return_value=''):
            self.save_from_ui()
        self.assertEqual(router.candidates('alice', 'chat'), ['groq', 'ollama'])

    def test_local_mode_and_paid_exclusion_still_apply(self):
        self.save_from_ui()
        with patch.object(router.privacy, 'mode', return_value='yerel'):
            self.assertEqual(router.candidates('alice', 'chat'), ['ollama'])
        self.assertNotIn('openai', router.candidates('alice', 'code'))
        self.assertNotIn('anthropic', router.candidates('alice', 'code'))

    def test_confirmation_does_not_bypass_provider_cooldown(self):
        self.save_from_ui()
        router._HEALTH[('alice','groq')] = {'until':router.time.monotonic()+30}
        self.assertEqual(router.candidates('alice','chat'), ['gemini','ollama'])
        policy = next(x['policy'] for x in router.status('alice')['capabilities'] if x['provider']=='groq')
        self.assertIn('Kullanıcı beyanı',policy)
        self.assertNotIn('Kanıtlı',policy)

    def test_enable_message_does_not_claim_independent_billing_verification(self):
        with patch.object(llm,'set_provider'):
            reply = router.handle('alice','smart router aç')
        self.assertNotIn('kanıtlı',reply.casefold())

    def test_key_mismatch_has_structured_user_action_reason(self):
        self.save_from_ui()
        with patch.object(llm,'user_key',return_value='new-key'), \
             patch.object(llm,'user_groq_key',return_value='new-groq'), \
             patch.object(router,'selection',wraps=router.selection) as select:
            row = select('alice','chat')
        self.assertTrue(all(x['reason_code']=='PROVIDER_FREE_ACCOUNT_RECONFIRM_REQUIRED' for x in row['skipped']))


if __name__ == '__main__':
    unittest.main()
