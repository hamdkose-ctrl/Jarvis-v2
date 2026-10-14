import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from modules import smart_router as router, llm, requests_state


class SmartRouterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        for target,value in [('_STORE',Path(self.tmp.name)),('_HEALTH',{}),('_LAST',{})]:
            p=patch.object(router,target,value);p.start();self.addCleanup(p.stop)
        p=patch.object(router.privacy,'mode',return_value='normal');p.start();self.addCleanup(p.stop)
        p=patch.object(llm,'user_key',return_value='gem-key');p.start();self.addCleanup(p.stop)
        p=patch.object(llm,'user_groq_key',return_value='groq-key');p.start();self.addCleanup(p.stop)
        self.crypto=patch.object(router.privacy,'protect',side_effect=lambda s:'enc:'+s);self.crypto.start();self.addCleanup(self.crypto.stop)
        p=patch.object(router.privacy,'unprotect',side_effect=lambda s:s.removeprefix('enc:'));p.start();self.addCleanup(p.stop)

    def test_no_assumption_key_means_free_account(self):
        self.assertEqual(router.candidates('alice','chat'),['ollama'])
        router.configure('alice',True,key='abc')
        self.assertEqual(router.candidates('alice','chat'),['groq','gemini','ollama'])
        self.assertEqual(router.candidates('bob','chat'),['ollama'])
        self.assertNotIn('abc',json.dumps(router.status('alice')))
        self.assertIn('enc:abc',router.owner_path('alice').read_text())

    def test_paid_model_rejected_and_paid_provider_never_fallback(self):
        with self.assertRaises(ValueError): router.configure('alice',model='openai/gpt-paid')
        router.configure('alice',True,model='x/y:free',key='abc')
        self.assertEqual(router.candidates('alice','vision'),['gemini','ollama'])
        self.assertNotIn('openai',router.candidates('alice','code'))
        self.assertNotIn('anthropic',router.candidates('alice','code'))

    def test_status_reflects_owner_confirmation_and_missing_key(self):
        router.configure('alice',True)
        def policy(owner,provider):
            return next(r['policy'] for r in router.status(owner)['capabilities'] if r['provider']==provider)
        self.assertIn('onaylı',policy('alice','gemini'))
        self.assertNotIn('onayı gerekli',policy('alice','gemini'))
        self.assertIn('onayı gerekli',policy('bob','gemini'))
        with patch.object(llm,'user_groq_key',return_value=''):
            self.assertIn('anahtarı eksik',policy('alice','groq'))
        self.assertNotIn('gem-key',json.dumps(router.status('alice')))

    def test_status_shows_owner_cooldown_without_claiming_live_success(self):
        router.configure('alice',True)
        router._HEALTH[('alice','gemini')]={'until':router.time.monotonic()+300}
        router._HEALTH[('bob','groq')]={'until':router.time.monotonic()+300}
        status=router.status('alice')
        policies={r['provider']:r['policy'] for r in status['capabilities']}
        self.assertIn('beklemede',policies['gemini'])
        self.assertNotIn('beklemede',policies['groq'])
        self.assertIn('canlı çağrı sınanmadı',policies['groq'])

    def test_quota_fallback_cooldown_and_routing_trace(self):
        router.configure('alice',True)
        call=Mock(side_effect=[RuntimeError('quota PRIVATE'), 'gemini answer'])
        self.assertEqual(router.run('alice','merhaba',call),'gemini answer')
        self.assertEqual([c.args[0] for c in call.call_args_list],['groq','gemini'])
        trace=router.status('alice')['last']
        self.assertEqual(trace['provider'],'gemini');self.assertNotIn('PRIVATE',json.dumps(trace))
        self.assertNotIn('groq',router.candidates('alice','chat'))
        router.configure('bob',True)
        self.assertIn('groq',router.candidates('bob','chat'))

    def test_openrouter_key_never_joins_automatic_pool(self):
        router.configure('alice',True,key='abc')
        for task in ('chat','code','analysis','vision'):
            self.assertNotIn('openrouter',router.candidates('alice',task))

    def test_cooldown_depends_on_error_kind(self):
        class Coded(Exception):
            def __init__(self,code):super().__init__('x');self.code=code
        self.assertEqual(router.cooldown('gemini',Coded(401)),1800)
        self.assertEqual(router.cooldown('groq',llm.LocalModelError('Groq API anahtarı geçersiz ya da yetkisiz.')),1800)
        self.assertEqual(router.cooldown('gemini',Coded(429)),300)
        self.assertEqual(router.cooldown('groq',llm.LocalModelError('Groq yanıt vermedi (429 rate limit)')),300)
        self.assertEqual(router.cooldown('ollama',llm.LocalModelError('Ollama çalışmıyor')),30)
        self.assertEqual(router.cooldown('gemini',ConnectionError('down')),60)

    def test_gemini_mode_falls_back_to_own_groq_then_ollama_on_quota(self):
        quota=llm.errors.ClientError(429,{'error':{'message':'quota','status':'RESOURCE_EXHAUSTED'}})
        with patch.object(llm,'current_user',return_value='alice'),patch.object(llm,'_cli',return_value=Mock()), \
             patch.object(llm,'_with_models',side_effect=quota):
            with patch.object(llm,'_groq',return_value='groq answer') as groq:
                self.assertEqual(llm._send('merhaba','',100,None,'gemini'),'groq answer');groq.assert_called_once()
            with patch.object(llm,'_groq',side_effect=llm.CloudError('quota')),patch.object(llm,'_ollama',return_value='yerel'):
                self.assertEqual(llm._send('merhaba','',100,None,'gemini'),'yerel')
            with patch.object(llm,'user_groq_key',return_value=''),patch.object(llm,'_groq',side_effect=AssertionError('no key')), \
                 patch.object(llm,'_ollama',side_effect=llm.LocalModelError('yok')):
                with self.assertRaises(llm.errors.ClientError):llm._send('merhaba','',100,None,'gemini')
            # Auto mode (strict) leaves fallback to the router; a non-quota error is not hidden.
            with patch.object(llm,'_groq',side_effect=AssertionError('strict')):
                with self.assertRaises(llm.errors.ClientError):llm._send('merhaba','',100,None,'gemini',True)
        with patch.object(llm,'current_user',return_value='alice'),patch.object(llm,'_cli',return_value=Mock()), \
             patch.object(llm,'_with_models',side_effect=llm.errors.ClientError(400,{'error':{'message':'bad'}})),patch.object(llm,'_groq',side_effect=AssertionError('400')):
            with self.assertRaises(llm.errors.ClientError):llm._send('merhaba','',100,None,'gemini')

    def test_ollama_uses_big_model_for_code_and_falls_back_to_small(self):
        with patch.object(llm,'_cfg',return_value={'provider':'ollama','url':'http://x','model':'llama3.2'}), \
             patch.object(llm,'load_settings',return_value={}), \
             patch.object(llm,'ollama_models',return_value=['llama3.2:latest','qwen2.5:7b']):
            self.assertEqual(llm.ollama_model_for('merhaba nasılsın'),'llama3.2')
            self.assertEqual(llm.ollama_model_for('Python hatasını düzelt'),'qwen2.5:7b')
            with patch.object(llm,'_ollama',return_value='ok') as call:
                llm._ollama_task([],'',100,'bu pdf belgeyi analiz et')
                self.assertEqual(call.call_args.kwargs['model'],'qwen2.5:7b')
            with patch.object(llm,'_ollama',side_effect=[llm.LocalModelError('bellek'),'küçük']) as call:
                self.assertEqual(llm._ollama_task([],'',100,'kod yaz'),'küçük')
                self.assertEqual([c.kwargs['model'] for c in call.call_args_list],['qwen2.5:7b','llama3.2'])
            with patch.object(llm,'_ollama',side_effect=llm.ImageCapabilityError('x')) as call:
                with self.assertRaises(llm.ImageCapabilityError):llm._ollama_task([],'',100,'kod yaz')
                self.assertEqual(call.call_count,1)
        with patch.object(llm,'_cfg',return_value={'provider':'ollama','url':'http://x','model':'llama3.2'}), \
             patch.object(llm,'load_settings',return_value={}),patch.object(llm,'ollama_models',return_value=['llama3.2:latest']):
            self.assertEqual(llm.ollama_model_for('kod yaz'),'llama3.2')   # 7b yüklü değil
        llm.take_route()

    def test_route_trace_names_answering_model_and_fallbacks_only(self):
        llm.take_route()
        router.configure('alice',True)
        quota=type('Q',(Exception,),{})('429 RESOURCE_EXHAUSTED secret prompt')
        def answer(provider):
            if provider=='groq':raise quota
            return llm._timed('gemini',lambda:'cevap')
        self.assertEqual(router.run('alice','merhaba',answer),'cevap')
        route=llm.take_route()
        self.assertEqual(route,[('Groq kotası dolu, sıradakine geçildi',False),('Cevap: Gemini',True)])
        self.assertNotIn('secret',str(route));self.assertEqual(llm.take_route(),[])
        llm._timed('groq',lambda:'a');llm._timed('ollama',lambda:'b')
        self.assertEqual(llm.take_route(),[('Cevap: Ollama (yerel)',True)])

    def test_local_mode_never_cloud_and_empty_answer_is_failure(self):
        router.configure('alice',True,key='abc')
        with patch.object(router.privacy,'mode',return_value='yerel'):
            self.assertEqual(router.candidates('alice','vision'),['ollama'])
            with self.assertRaises(RuntimeError):router.run('alice','x',lambda p:'')
        with self.assertRaises(requests_state.Cancelled):router.run('bob','x',Mock(side_effect=requests_state.Cancelled()))

    def test_actual_llm_auto_dispatch_preserves_history_and_strict_no_legacy_fallback(self):
        router.configure('alice',True)
        with patch.object(llm,'current_user',return_value='alice'),patch.object(llm,'provider',return_value='auto'),patch.object(llm,'_groq',return_value='fast') as groq:
            self.assertEqual(llm.ask('test'),'fast')
            self.assertEqual(groq.call_args.args[0][-1]['content'],'test')
        with patch.object(llm,'_groq',side_effect=llm.CloudError('quota')),patch.object(llm,'_cli',side_effect=AssertionError('legacy fallback')):
            with self.assertRaises(llm.LocalModelError):llm._send('x','',100,None,'groq',True)

    def test_task_classification_and_gizli_image_gate(self):
        self.assertEqual(router.task_type('Python hatasını düzelt'),'code')
        self.assertEqual(router.task_type('PDF belgeyi analiz et'),'analysis')
        self.assertEqual(router.task_type('x',True),'vision')
        with patch.object(llm.privacy,'mode',return_value='gizli'),patch.object(router,'run',side_effect=AssertionError('cloud')):
            self.assertIn('Gizli',llm.ask_image('missing.png','x'))

    def test_openrouter_payload_and_secrets_not_in_status(self):
        router.configure('alice',key='secret',model='openrouter/free')
        response=Mock();response.json.return_value={'choices':[{'message':{'content':'answer'}}]}
        with patch.object(router.requests,'post',return_value=response) as post:
            self.assertEqual(router.openrouter('alice',[{'role':'user','content':'hi'}],'sys',200),'answer')
            self.assertEqual(post.call_args.kwargs['json']['model'],'openrouter/free')
            self.assertEqual(post.call_args.kwargs['headers']['Authorization'],'Bearer secret')
        router.configure('alice',key='');self.assertFalse(router.status('alice')['key'])

    def test_auxiliary_gemini_calls_cannot_bypass_budget_policy(self):
        from modules import live
        with patch.object(llm,'provider',return_value='auto'),patch.object(llm,'current_user',return_value='alice'),patch.object(llm,'_cli',side_effect=AssertionError('cloud')):
            self.assertFalse(llm.gemini_aux_allowed());self.assertFalse(live.enabled())
            self.assertEqual(llm.model_check()['state'],'budget')
            with self.assertRaises(ValueError):llm.embed(['x'])
            with self.assertRaises(RuntimeError):llm.transcribe(data=b'wav')
            router.configure('alice',True);self.assertTrue(llm.gemini_aux_allowed())

    def test_corrupt_router_state_fails_closed_and_still_allows_local_fallback(self):
        for content in ('[]','null','"invalid"','{"cloud_free_confirmed":"false","key":42,"openrouter_model":"paid-model"}'):
            router.owner_path('alice').write_text(content)
            self.assertFalse(router.settings('alice')['cloud_free_confirmed'])
            self.assertEqual(router.candidates('alice','chat'),['ollama'])
            self.assertEqual(router.status('alice')['model'],'openrouter/free')

    def test_cancellation_after_provider_response_is_not_success(self):
        with patch.object(router.requests_state,'check',side_effect=[None,requests_state.Cancelled()]):
            with self.assertRaises(requests_state.Cancelled):router.run('alice','test',lambda p:'late answer')
        self.assertEqual(router.status('alice')['last'],{})

    def test_ui_auto_now_calls_auto_provider(self):
        from modules import nxapi
        with patch.object(llm,'set_provider') as choose,patch.object(nxapi,'save_settings'),patch.object(nxapi,'ui_settings',return_value={}):
            nxapi.ui_set('ai_mode','auto');choose.assert_called_once_with('auto')


if __name__=='__main__':unittest.main()
