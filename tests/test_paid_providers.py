"""No real API requests: ownership, opt-in, payloads, privacy and billing-safe failures."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from modules import paid_providers as paid, llm

class PaidProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.p=patch.object(paid,'DATA_DIR',self.root);self.p.start();self.addCleanup(self.p.stop)
        from modules import user_models
        self.models=patch.object(user_models,'DATA_DIR',self.root);self.models.start();self.addCleanup(self.models.stop)
        self.privacy=patch.object(paid.privacy,'mode',return_value='normal');self.privacy.start();self.addCleanup(self.privacy.stop)
        self.net=patch.object(paid.requests,'request');self.request=self.net.start();self.addCleanup(self.net.stop)
        self.response=Mock(status_code=200);self.request.return_value=self.response
    def configure(self,provider='openai',owner='alice'):
        paid.configure(owner,provider,api_key='test-secret-'+owner,model='account-model')
    def test_keys_are_separate_public_status_has_no_key_and_no_network_save(self):
        self.configure();self.configure(owner='bob')
        self.assertEqual(paid.key('alice','openai'),'test-secret-alice')
        self.assertEqual(paid.key('bob','openai'),'test-secret-bob')
        self.assertEqual(paid.key('charlie','openai'),'')
        self.assertNotIn('test-secret',str(paid.status('alice','openai')))
        self.request.assert_not_called()
        paid.configure('alice','openai',api_key='')
        self.assertEqual(paid.key('alice','openai'),'');self.assertTrue(paid.key('bob','openai'))
    def test_corrupt_profile_path_and_failed_windows_protection_do_not_save(self):
        with self.assertRaises(ValueError):paid.configure('../alice','openai',api_key='secret')
        with patch.object(paid.sys,'platform','win32'),patch.object(paid.privacy,'protect',return_value='b64:unsafe'):
            with self.assertRaises(ValueError):self.configure()
        self.assertFalse(paid.key('alice','openai'))
    def test_openai_wire_format_replays_history_store_false_and_no_temperature(self):
        self.configure();self.response.json.return_value={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'Yanıt'}]}]}
        result=paid.generate('alice','openai',[{'role':'user','content':'Önceki'},{'role':'assistant','content':'Önceki cevap'},{'role':'user','content':'Yeni'}],'Talimat',1800)
        self.assertEqual(result,'Yanıt')
        args=self.request.call_args
        self.assertEqual(args.args,('POST','https://api.openai.com/v1/responses'))
        body=args.kwargs['json'];self.assertIs(body['store'],False)
        self.assertEqual(body['input'][1]['role'],'assistant');self.assertEqual(body['max_output_tokens'],1800)
        self.assertNotIn('temperature',body)
        self.assertEqual(args.kwargs['headers']['Authorization'],'Bearer test-secret-alice')
    def test_claude_image_version_workspace_and_content(self):
        self.configure('anthropic');paid.configure('alice','anthropic',workspace='wrkspc_example')
        image=self.root/'shot.png';image.write_bytes(b'png')
        self.response.json.return_value={'stop_reason':'end_turn','content':[{'type':'text','text':'Görsel yanıt'}]}
        result=paid.generate('alice','anthropic',[{'role':'user','content':'Resmi oku'}],'Türkçe',1000,image)
        self.assertEqual(result,'Görsel yanıt')
        kw=self.request.call_args.kwargs
        self.assertEqual(kw['headers']['anthropic-version'],'2023-06-01')
        self.assertEqual(kw['headers']['anthropic-workspace-id'],'wrkspc_example')
        self.assertEqual(kw['json']['messages'][0]['content'][0]['source']['media_type'],'image/png')
    def test_private_missing_key_and_model_never_send(self):
        with self.assertRaises(paid.ProviderError):paid.generate('alice','openai',[{'role':'user','content':'x'}],'',20)
        self.configure()
        for mode in ('gizli','yerel'):
            with patch.object(paid.privacy,'mode',return_value=mode):
                with self.assertRaises(paid.ProviderError):paid.generate('alice','openai',[{'role':'user','content':'x'}],'',20)
        self.request.assert_not_called()
    def test_quota_and_timeout_not_retried_or_key_leaked(self):
        self.configure();self.response.status_code=429;self.response.json.return_value={'error':{'message':'test-secret-alice'}}
        with self.assertRaises(paid.ProviderError) as e:paid.generate('alice','openai',[{'role':'user','content':'x'}],'',20)
        self.assertNotIn('test-secret',str(e.exception));self.assertEqual(self.request.call_count,1)
        self.request.reset_mock();self.request.side_effect=paid.requests.Timeout('test-secret-alice')
        with self.assertRaises(paid.ProviderError) as e:paid.generate('alice','openai',[{'role':'user','content':'x'}],'',20)
        self.assertNotIn('test-secret',str(e.exception));self.assertEqual(self.request.call_count,1)
    def test_incomplete_response_is_not_success(self):
        self.configure();self.response.json.return_value={'status':'incomplete','output':[{'type':'message','content':[{'type':'output_text','text':'Yarım'}]}]}
        with self.assertRaises(paid.ProviderError):paid.generate('alice','openai',[{'role':'user','content':'x'}],'',20)
    def test_account_models_get_without_generation_and_claude_pagination(self):
        self.configure('anthropic')
        self.response.json.side_effect=[{'data':[{'id':'model-a','display_name':'A'}],'has_more':True,'last_id':'model-a'},
                                        {'data':[{'id':'model-b'}],'has_more':False}]
        result=paid.models('alice','anthropic');self.assertEqual([x['id'] for x in result],['model-a','model-b'])
        self.assertTrue(all(x.args[0]=='GET' for x in self.request.call_args_list))
        self.assertTrue(self.request.call_args.args[1].endswith('after_id=model-a'))
    def test_paid_dispatch_never_falls_back_to_gemini(self):
        with patch.object(llm,'provider',return_value='openai'),patch.object(llm,'current_user',return_value='alice'),patch.object(paid,'generate',side_effect=paid.ProviderError('Kota')) as generate,patch.object(llm,'_cli') as gemini:
            with self.assertRaises(paid.ProviderError):llm._send('Merhaba','',500,[])
        generate.assert_called_once();gemini.assert_not_called()
    def test_saved_candidate_does_not_change_active_model(self):
        self.configure();paid.configure('alice','openai',candidate_model='new-choice')
        self.assertEqual(paid.settings('alice','openai')['model'],'account-model')
        with patch.object(llm,'current_user',return_value='alice'),patch.object(llm,'save_settings'):
            llm.set_provider('openai')
        self.assertEqual(paid.settings('alice','openai')['model'],'new-choice')
    def test_selecting_paid_requires_own_key_and_model(self):
        with patch.object(llm,'current_user',return_value='alice'),patch.object(llm,'save_settings') as save:
            with self.assertRaises(ValueError):llm.set_provider('openai')
            save.assert_not_called();self.configure();llm.set_provider('openai')
            # Seçim yalnız bu kullanıcıya yazılır; kurulumun genel sağlayıcısı değişmez.
            self.assertNotIn('provider',save.call_args.kwargs)
            from modules import user_models
            self.assertEqual(user_models.choice('alice')['provider'],'openai')
            self.assertEqual(user_models.choice('bob'),{})

if __name__=='__main__':unittest.main()
