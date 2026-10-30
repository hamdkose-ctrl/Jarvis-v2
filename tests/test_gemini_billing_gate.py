import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import config
from modules import llm, gemini_billing as billing, smart_router, failure_policy

FREE={'state':'billing_disabled','project_id':'actual-project','billing_enabled':False}
PAID={'state':'billing_enabled','project_id':'actual-project','billing_enabled':True}
UNKNOWN={'state':'unverified','reason_code':'PROVIDER_ACCOUNT_ACCESS_REQUIRED'}

class GeminiBillingGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        for obj,name,value in [(config,'DATA_DIR',Path(self.tmp.name)),(llm,'current_user',lambda:'alice'),(llm.privacy,'mode',lambda:'normal')]:
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
        p=patch.dict(llm._user_clients,{},clear=True);p.start();self.addCleanup(p.stop)
        if hasattr(billing,'_verified'):
            p=patch.dict(billing._verified,{},clear=True);p.start();self.addCleanup(p.stop)

    def test_receipt_owner_key_and_tier_binding(self):
        with patch.object(billing,'verify',return_value=FREE):billing.check('alice','key')
        self.assertEqual(billing.receipt('alice','key')['result'],FREE)
        for owner,key,tier in [('bob','key','free'),('alice','other','free'),('alice','key','paid')]:
            self.assertIsNone(billing.receipt(owner,key,tier=tier))
        self.assertNotIn('key',next(Path(self.tmp.name).rglob('free.json')).read_text())

    def test_warm_receipt_reused_restart_rechecks(self):
        with patch.object(billing,'verify',return_value=FREE) as verify:
            billing.check('alice','key');billing.check('alice','key');self.assertEqual(verify.call_count,1)
            billing._verified.clear();billing.check('alice','key');self.assertEqual(verify.call_count,2)

    def test_stale_paid_blocks_cached_client(self):
        with patch.object(billing,'time') as clock,patch.object(billing,'verify',side_effect=[FREE,PAID]),patch.object(llm,'user_key',return_value='key'),patch.object(llm.genai,'Client',return_value=Mock()) as create:
            clock.time.return_value=100;llm._cli()
            clock.time.return_value=131
            with self.assertRaises(failure_policy.ProviderExhaustedError):llm._cli()
            self.assertEqual(create.call_count,1)

    def test_external_key_change_revalidated_before_client_creation(self):
        with patch.object(billing,'verify',side_effect=[FREE,UNKNOWN]) as verify,patch.object(llm,'user_key',side_effect=['key','other']),patch.object(llm.genai,'Client',return_value=Mock()) as create:
            llm._cli()
            with self.assertRaises(failure_policy.ProviderExhaustedError):llm._cli()
            self.assertEqual(verify.call_args.args,('alice','other'));self.assertEqual(create.call_count,1)

    def test_failed_write_cannot_revive_previous_free_receipt(self):
        with patch.object(billing,'verify',return_value=FREE):billing.check('alice','key')
        with patch.object(billing,'verify',return_value=PAID),patch('modules.publish_services._write_private_json',side_effect=OSError('disk')):
            result=billing.check('alice','key',force=True)
        self.assertEqual(result['state'],'unverified')
        with patch.object(billing,'verify',return_value=PAID) as verify:
            with self.assertRaises(failure_policy.ProviderExhaustedError):billing.require_free('alice','key')
            verify.assert_called_once()

    def test_google_receipt_selection_without_user_checkbox(self):
        with patch.object(billing,'verify',return_value=FREE):billing.check('alice','key')
        with patch.object(llm,'user_key',return_value='key'),patch.object(llm,'user_groq_key',return_value=''),patch.object(smart_router,'settings',return_value={'cloud_free_confirmed':False}),patch.dict(smart_router._HEALTH,{},clear=True):
            self.assertIn('gemini',smart_router.selection('alice','chat')['candidates'])

    def test_receipt_read_has_no_network(self):
        with patch.object(billing,'verify',return_value=FREE):billing.check('alice','key')
        with patch.object(billing,'verify') as verify:
            self.assertEqual(billing.receipt('alice','key')['result'],FREE)
            verify.assert_not_called()

    def test_stale_unknown_is_retry_candidate_not_verified(self):
        with patch.object(billing,'time') as clock,patch.object(billing,'verify',return_value=UNKNOWN):
            clock.time.return_value=100;billing.check('alice','key')
        with patch.object(smart_router.time,'time',return_value=131),patch.object(llm,'user_key',return_value='key'):
            self.assertTrue(smart_router._google_billing_gate('alice')['ok'])
        with patch.object(billing,'verify',return_value=UNKNOWN):
            with self.assertRaises(failure_policy.ProviderExhaustedError):billing.require_free('alice','key')

    def test_no_owner_aux_closed(self):
        with patch.object(llm,'current_user',return_value=None),patch.object(llm,'provider',return_value='auto'),patch.object(smart_router,'settings',return_value={'cloud_free_confirmed':False}):
            self.assertFalse(llm.gemini_aux_allowed())

    def test_receipt_cannot_use_paid_slot_as_free(self):
        with patch.object(billing,'verify',return_value=FREE):billing.check('alice','key',tier='paid')
        self.assertIsNone(billing.receipt('alice','key'))

    def test_router_keeps_recheck_failure_reason_and_safe_message(self):
        for code in ('PROVIDER_BILLING_ENABLED','PROVIDER_ACCOUNT_ACCESS_REQUIRED'):
            with self.subTest(code=code),patch.object(smart_router,'selection',return_value={'candidates':['gemini'],'skipped':[]}),patch.object(smart_router,'_free_emergency',return_value=False),patch.object(llm,'note_route'),patch.dict(smart_router._HEALTH,{},clear=True):
                def fail(provider):raise failure_policy.ProviderExhaustedError('secret-key raw must not appear',reason_code=code,recovery_class='user_action_required')
                with self.assertRaises(failure_policy.ProviderExhaustedError) as raised:smart_router.run('alice','hello',fail)
                self.assertEqual(raised.exception.reason_code,code)
                self.assertEqual(raised.exception.recovery_class,'user_action_required')
                self.assertNotIn('secret-key',str(raised.exception))
                self.assertEqual(smart_router._LAST['alice']['attempts'][0]['reason_code'],code)
                self.assertNotIn('çağrı başarısız (ProviderExhaustedError)',str(raised.exception))

    def test_router_never_copies_arbitrary_exception_metadata(self):
        with patch.object(smart_router,'selection',return_value={'candidates':['gemini'],'skipped':[]}),patch.object(smart_router,'_free_emergency',return_value=False),patch.object(llm,'note_route'),patch.dict(smart_router._HEALTH,{},clear=True):
            def fail(provider):raise failure_policy.ProviderExhaustedError('secret',reason_code='PROVIDER_BILLING_secret-key',recovery_class='raw-secret')
            with self.assertRaises(failure_policy.ProviderExhaustedError) as raised:smart_router.run('alice','hello',fail)
            self.assertEqual(raised.exception.reason_code,'PROVIDER_POOL_EXHAUSTED');self.assertNotIn('secret',str(raised.exception))

if __name__=='__main__':unittest.main()
