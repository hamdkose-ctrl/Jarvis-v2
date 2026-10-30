import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import config
from modules import llm, user_models, gemini_billing, model_health, diagnostics
from web_models import WebModels


class GeminiAccountsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        for obj,name,value in [(config,'DATA_DIR',Path(self.tmp.name)),(user_models,'DATA_DIR',Path(self.tmp.name))]:
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
        for obj,name,value in [(llm,'current_user','alice'),(llm.privacy,'mode','normal')]:
            p=patch.object(obj,name,return_value=value);p.start();self.addCleanup(p.stop)
        self.bridge=SimpleNamespace(_runtime=SimpleNamespace(_p=lambda:SimpleNamespace(slug='alice'),llm=llm))

    def session(self, enabled=False):
        session=Mock()
        def response(data):
            r=Mock(status_code=200);r.json.return_value=data;return r
        session.get.side_effect=[response({'parent':'projects/123/locations/global','name':'projects/123/locations/global/keys/key-id'}),response({'projectId':'actual-project','name':'projects/123'}),response({'projectId':'actual-project','billingEnabled':enabled})]
        return session

    def test_billing_disabled_belongs_to_exact_key_project(self):
        s=self.session()
        with patch.object(gemini_billing,'_session',return_value=s):r=gemini_billing.verify('alice','secret-key')
        self.assertEqual(r,{'state':'billing_disabled','project_id':'actual-project','billing_enabled':False})
        self.assertEqual(s.get.call_args_list[0].kwargs['params'],{'keyString':'secret-key'})
        self.assertTrue(s.get.call_args_list[2].args[0].endswith('/actual-project/billingInfo'))

    def test_paid_project_not_free(self):
        with patch.object(gemini_billing,'_session',return_value=self.session(True)):
            self.assertEqual(gemini_billing.verify('alice','key')['state'],'billing_enabled')

    def test_owner_mismatch_no_auth(self):
        with patch.object(gemini_billing,'_session') as auth:
            with self.assertRaises(PermissionError):gemini_billing.verify('bob','key')
        auth.assert_not_called()

    def test_redirect_and_http_errors_unverified(self):
        for code in (302,401,403,429,500):
            with self.subTest(code=code):
                s=Mock();s.get.return_value=Mock(status_code=code)
                with patch.object(gemini_billing,'_session',return_value=s):r=gemini_billing.verify('alice','secret-key')
                self.assertEqual(r['state'],'unverified');self.assertNotIn('secret-key',str(r));self.assertEqual(s.get.call_count,1)

    def test_wrong_project_rejected(self):
        s=self.session();rows=list(s.get.side_effect);rows[1].json.return_value={'projectId':'other-project','name':'projects/999'};s.get.side_effect=rows
        with patch.object(gemini_billing,'_session',return_value=s):self.assertEqual(gemini_billing.verify('alice','key')['state'],'unverified')
        self.assertEqual(s.get.call_count,2)

    def test_missing_boolean_not_false(self):
        s=self.session();rows=list(s.get.side_effect);rows[2].json.return_value={'projectId':'actual-project'};s.get.side_effect=rows
        with patch.object(gemini_billing,'_session',return_value=s):self.assertEqual(gemini_billing.verify('alice','key')['state'],'unverified')

    def test_transport_diagnostics_redacted(self):
        s=Mock();s.get.side_effect=RuntimeError('https://apikeys.googleapis.com/?keyString=private-secret')
        with patch.dict(diagnostics._recent,{},clear=True),patch.object(gemini_billing,'_session',return_value=s),self.assertLogs('jarvis',level='ERROR') as logs:r=gemini_billing.verify('alice','private-secret')
        self.assertNotIn('private-secret',str(r)+str(logs.output));self.assertEqual(r['state'],'unverified')

    def test_keys_independent_and_owner_scoped(self):
        llm.set_user_key('alice','free-secret');llm.set_user_key('alice','paid-secret',tier='paid')
        self.assertEqual(llm.user_key('alice'),'free-secret');self.assertEqual(llm.user_key('alice',tier='paid'),'paid-secret');self.assertEqual(llm.user_key('bob',tier='paid'),'')
        llm.set_user_key('alice',None,tier='paid');self.assertEqual(llm.user_key('alice'),'free-secret')

    def test_paid_key_not_free_fallback(self):
        llm.set_user_key('alice','paid-secret',tier='paid');self.assertEqual(llm.user_key('alice'),'')

    def test_model_lists_independent(self):
        llm.model_settings('alice','gemini-free-model',[]);llm.model_settings('alice','gemini-paid-model',['gemini-paid-backup'],tier='paid')
        self.assertEqual(llm.model_names('alice'),['gemini-free-model']);self.assertEqual(llm.model_names('alice',tier='paid'),['gemini-paid-model','gemini-paid-backup']);self.assertEqual(llm.model_names('bob',tier='paid'),[])

    def test_invalid_tier_no_write(self):
        with self.assertRaises(ValueError):llm.set_user_key('alice','secret',tier='other')
        self.assertFalse(list(Path(self.tmp.name).rglob('*.txt')))

    def test_ui_paid_save_no_activation(self):
        llm.set_user_key('alice','free-secret')
        with patch.object(llm,'set_provider') as activate:r=WebModels.gemini_profile_save(self.bridge,'paid','paid-secret','gemini-paid-model','')
        activate.assert_not_called();self.assertTrue(r['ok']);self.assertNotIn('paid-secret',str(r));self.assertEqual(llm.user_key('alice'),'free-secret')

    def test_blank_key_preserved(self):
        llm.set_user_key('alice','paid-secret',tier='paid');WebModels.gemini_profile_save(self.bridge,'paid','','gemini-paid-model','');self.assertEqual(llm.user_key('alice',tier='paid'),'paid-secret')

    def test_ui_billing_uses_free_key(self):
        llm.set_user_key('alice','free-secret')
        with patch.object(gemini_billing,'verify',return_value={'state':'billing_disabled'}) as check:r=WebModels.gemini_billing_check(self.bridge)
        check.assert_called_once_with('alice','free-secret',interactive=True);self.assertTrue(r['ok']);self.assertIn('kota',r['msg'])

    def test_ui_billing_failed_not_free(self):
        with patch.object(gemini_billing,'verify',return_value={'state':'unverified'}):r=WebModels.gemini_billing_check(self.bridge)
        self.assertFalse(r['ok']);self.assertIn('doğrulanamadı',r['msg'])

    def test_ui_paid_billing_uses_paid_key(self):
        llm.set_user_key('alice','paid-secret',tier='paid')
        with patch.object(gemini_billing,'verify',return_value={'state':'billing_enabled'}) as check:r=WebModels.gemini_billing_check(self.bridge,'paid')
        check.assert_called_once_with('alice','paid-secret',interactive=True);self.assertTrue(r['ok']);self.assertIn('izni açılmadı',r['msg'])

    def test_catalog_generation_only_no_generation_call(self):
        c=Mock();c.models.list.return_value=[SimpleNamespace(name='models/gemini-chat',supported_actions=['generateContent']),SimpleNamespace(name='models/embed',supported_actions=['embedContent'])]
        r=model_health.check('catalog-test','key',[],Mock(return_value=c),force=True)
        self.assertEqual(r['available_models'],['gemini-chat']);c.models.generate_content.assert_not_called();c.close.assert_called_once()

    def test_paid_catalog_uses_paid_key(self):
        llm.set_user_key('alice','paid-key',tier='paid')
        with patch.object(model_health,'check',return_value={'state':'ok','available_models':['gemini-chat']}) as check:r=WebModels.gemini_profile_models(self.bridge,'paid')
        self.assertEqual(check.call_args.args[1],'paid-key');self.assertEqual(r['models'],['gemini-chat']);self.assertNotIn('paid-key',str(r))

    def test_catalog_new_key_not_saved(self):
        with patch.object(llm,'set_user_key') as save,patch.object(model_health,'check',return_value={'state':'ok','available_models':['gemini-chat']}) as check:r=WebModels.gemini_profile_models(self.bridge,'paid','new-key')
        save.assert_not_called();self.assertTrue(r['ok']);self.assertEqual(check.call_args.args[1],'new-key')
