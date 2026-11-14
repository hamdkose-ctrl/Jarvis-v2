"""Retired vendor choices exercised through owner custom roles and three wire protocols."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from modules import router_connections as connections,provider_protocols as protocols,llm,user_models,smart_router


class PaidProviderTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.root=Path(folder.name)
        for obj,name,value in [(connections,'DATA_DIR',self.root),(user_models,'DATA_DIR',self.root),(smart_router,'_STORE',self.root/'router'),(smart_router,'_HEALTH',{})]:
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
        p=patch.object(connections.privacy,'mode',return_value='normal');p.start();self.addCleanup(p.stop)
        p=patch.object(protocols.requests,'request');self.request=p.start();self.addCleanup(p.stop)
        self.response=Mock(status_code=200,headers={});self.request.return_value=self.response
        self.record=dict(name='My connection',protocol='responses',base_url='https://api.example.org/v1',model='account-model',
            role='conversation',billing='paid',paid_enabled=True,enabled=True,data_scopes=['conversation'],daily_requests=20,max_output_tokens=4096)

    def configure(self,owner='alice',**changes):
        return connections.save(owner,{**self.record,**changes},secret='test-secret-'+owner)

    def generate(self,row,owner='alice',messages=None,system='',tokens=20,image=None):
        connection,secret=connections.resolve(owner,row['id'])
        return protocols.generate(owner,connection,secret,messages or [{'role':'user','content':'x'}],system,tokens,image_path=image)

    def test_keys_are_separate_public_status_has_no_key_and_no_network_save(self):
        alice=self.configure();bob=self.configure(owner='bob')
        self.assertEqual(connections.resolve('alice',alice['id'])[1],'test-secret-alice')
        self.assertEqual(connections.resolve('bob',bob['id'])[1],'test-secret-bob')
        self.assertNotIn('test-secret',str(connections.snapshot('alice')));self.request.assert_not_called()
        connections.remove('alice',alice['id'])
        self.assertEqual(connections.snapshot('alice'),[]);self.assertTrue(connections.resolve('bob',bob['id'])[1])

    def test_corrupt_profile_path_and_failed_windows_protection_do_not_save(self):
        with self.assertRaises(ValueError):self.configure(owner='../alice')
        with patch.object(connections.sys,'platform','win32'),patch.object(connections.privacy,'protect',return_value='b64:unsafe'):
            with self.assertRaises(ValueError):self.configure()
        self.assertEqual(connections.snapshot('alice'),[])

    def test_responses_wire_format_replays_history_store_false_and_no_temperature(self):
        row=self.configure();self.response.json.return_value={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'Yanıt'}]}]}
        messages=[{'role':'user','content':'Önceki'},{'role':'assistant','content':'Önceki cevap'},{'role':'user','content':'Yeni'}]
        self.assertEqual(self.generate(row,messages=messages,system='Talimat',tokens=1800).text,'Yanıt')
        args=self.request.call_args;self.assertEqual(args.args,('POST','https://api.example.org/v1/responses'))
        body=args.kwargs['json'];self.assertIs(body['store'],False);self.assertEqual(body['input'][1]['role'],'assistant')
        self.assertEqual(body['max_output_tokens'],1800);self.assertNotIn('temperature',body)
        self.assertEqual(args.kwargs['headers']['Authorization'],'Bearer test-secret-alice')
        self.assertFalse(args.kwargs['allow_redirects'])

    def test_messages_image_version_workspace_and_content(self):
        row=self.configure(protocol='anthropic_messages',workspace='wrkspc_example')
        image=self.root/'shot.png';image.write_bytes(b'png')
        self.response.json.return_value={'stop_reason':'end_turn','content':[{'type':'text','text':'Görsel yanıt'}]}
        self.assertEqual(self.generate(row,system='Türkçe',tokens=1000,image=image).text,'Görsel yanıt')
        kw=self.request.call_args.kwargs
        self.assertEqual(kw['headers']['anthropic-version'],'2023-06-01')
        self.assertEqual(kw['headers']['anthropic-workspace-id'],'wrkspc_example')
        self.assertEqual(kw['json']['messages'][0]['content'][0]['source']['media_type'],'image/png')

    def test_private_missing_key_and_model_never_send(self):
        with self.assertRaises(ValueError):connections.resolve('alice','f'*24)
        with self.assertRaises(ValueError):self.configure(model='')
        row=self.configure()
        for mode in ('gizli','yerel'):
            with patch.object(protocols.privacy,'mode',return_value=mode):
                with self.assertRaises(protocols.ProtocolError):self.generate(row)
        self.request.assert_not_called()

    def test_quota_and_timeout_not_retried_or_key_leaked(self):
        row=self.configure();self.response.status_code=429;self.response.json.return_value={'error':{'message':'test-secret-alice'}}
        with self.assertRaises(protocols.ProtocolError) as error:self.generate(row)
        self.assertNotIn('test-secret',str(error.exception));self.assertEqual(self.request.call_count,1)
        self.request.reset_mock();self.request.side_effect=protocols.requests.Timeout('test-secret-alice')
        with self.assertRaises(protocols.ProtocolError) as error:self.generate(row)
        self.assertNotIn('test-secret',str(error.exception));self.assertEqual(self.request.call_count,1)

    def test_incomplete_response_is_not_adopted_by_router(self):
        row=self.configure();self.response.json.return_value={'status':'incomplete','output':[{'type':'message','content':[{'type':'output_text','text':'Yarım'}]}]}
        request=smart_router.ModelRequest(owner='alice',request_id='incomplete')
        with self.assertRaises(RuntimeError):smart_router.run_request(request,lambda spec:llm.dispatch(request,spec,'x',''))
        self.assertEqual(smart_router.trace('alice','incomplete')['attempts'][0]['kind'],'response_validation')
        self.assertLessEqual(self.request.call_count,2)

    def test_account_models_get_without_generation_and_messages_pagination(self):
        row=self.configure(protocol='anthropic_messages');record,secret=connections.resolve('alice',row['id'])
        self.response.json.side_effect=[{'data':[{'id':'model-a','display_name':'A'}],'has_more':True,'last_id':'model-a'},
                                        {'data':[{'id':'model-b'}],'has_more':False}]
        result=protocols.models(record,secret);self.assertEqual([x['id'] for x in result],['model-a','model-b'])
        self.assertTrue(all(x.args[0]=='GET' for x in self.request.call_args_list))
        self.assertTrue(self.request.call_args.args[1].endswith('after_id=model-a'))

    def test_paid_role_dispatch_never_falls_back_to_free_provider(self):
        self.configure();self.response.status_code=429
        request=smart_router.ModelRequest(owner='alice')
        with patch.object(llm,'current_user',return_value='alice'),patch.object(llm,'_cli') as gemini:
            with self.assertRaises(RuntimeError):smart_router.run_request(request,lambda spec:llm.dispatch(request,spec,'Merhaba',''))
        self.request.assert_called_once();gemini.assert_not_called()

    def test_saved_disabled_connection_does_not_change_active_model(self):
        before=user_models.choice('alice');self.configure(enabled=False,model='new-choice')
        self.assertEqual(user_models.choice('alice'),before)
        self.assertEqual(smart_router.plan(smart_router.ModelRequest(owner='alice')).candidates,())
        self.request.assert_not_called()

    def test_legacy_vendor_selection_is_retired_and_paid_role_requires_own_key(self):
        for vendor in ('openai','anthropic'):
            with self.assertRaises(ValueError):llm.set_provider(vendor)
        with self.assertRaises(ValueError):connections.save('alice',self.record)
        self.configure();self.assertEqual(connections.snapshot('bob'),[])
        self.request.assert_not_called()


if __name__=='__main__':unittest.main()
