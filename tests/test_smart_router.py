import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from modules import smart_router as router, llm, requests_state
from provider_fixture import fresh_bundle


class SmartRouterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        for target,value in [('_STORE',Path(self.tmp.name)),('_HEALTH',{}),('_LAST',{})]:
            p=patch.object(router,target,value);p.start();self.addCleanup(p.stop)
        fresh_bundle(self)
        p=patch.object(router.privacy,'mode',return_value='normal');p.start();self.addCleanup(p.stop)
        p=patch.object(llm,'user_key',return_value='gem-key');p.start();self.addCleanup(p.stop)
        p=patch.object(llm,'user_groq_key',return_value='groq-key');p.start();self.addCleanup(p.stop)
        self.crypto=patch.object(router.privacy,'protect',side_effect=lambda s:'enc:'+s);self.crypto.start();self.addCleanup(self.crypto.stop)
        p=patch.object(router.privacy,'unprotect',side_effect=lambda s:s.removeprefix('enc:'));p.start();self.addCleanup(p.stop)
        real_configure=router.configure
        def configure_with_evidence(owner, cloud_free_confirmed=None):
            result=real_configure(owner,cloud_free_confirmed)
            if cloud_free_confirmed is True:
                now=router.time.time()
                for provider, model_name in [('gemini',llm.active_model(owner)),('groq',llm.groq_model())]:
                    router.set_free_tier_evidence(
                        owner,provider=provider,model=model_name,free_tier_verified=True,
                        source='test-fixture',evidence_ref='test://official-free-tier',verified_at=now,
                        ttl_seconds=3600,eligibility='eligible',quota_state='available',quota_remaining=10,
                        hard_stop_guaranteed=True,verification_status='verified',reason='router regression fixture')
            return result
        p=patch.object(router,'configure',side_effect=configure_with_evidence);p.start();self.addCleanup(p.stop)

    def test_no_assumption_key_means_free_account(self):
        self.assertEqual(router.candidates('alice','chat'),['ollama'])
        router.configure('alice',True)
        self.assertEqual(router.candidates('alice','chat'),['groq','ollama'])   # PRIVATE_GENERAL: Gemini yok
        self.assertEqual(router.candidates('alice','chat',route='PUBLIC_RESEARCH'),['gemini','groq','ollama'])
        self.assertEqual(router.candidates('bob','chat'),['ollama'])

    def test_paid_model_rejected_and_paid_provider_never_fallback(self):
        with self.assertRaises(TypeError): router.configure('alice',model='openai/gpt-paid')
        router.configure('alice',True)
        self.assertEqual(router.candidates('alice','vision'),['ollama'])   # görüntü özel: yalnız yerel
        self.assertNotIn('openai',router.candidates('alice','code'))
        self.assertNotIn('anthropic',router.candidates('alice','code'))

    def test_status_reflects_owner_confirmation_and_missing_key(self):
        router.configure('alice',True)
        def policy(owner,provider):
            return next(r['policy'] for r in router.status(owner)['capabilities'] if r['provider']==provider)
        self.assertIn('Kanıtlı ücretsiz rota',policy('alice','gemini'))
        self.assertNotIn('onayı gerekli',policy('alice','gemini'))
        self.assertIn('onayı gerekli',policy('bob','gemini'))
        with patch.object(llm,'user_groq_key',return_value=''):
            self.assertIn('anahtarı eksik',policy('alice','groq'))
        self.assertNotIn('gem-key',json.dumps(router.status('alice')))

    def test_local_deadline_ends_the_pool_without_punishing_the_provider(self):
        # Yerel süre bütçesi dolduğunda yeni aday boşuna denenmez ve sağlıklı sağlayıcı
        # cooldown'a düşürülmez: kök neden taşıma değil, çağıranın kendi sınırıdır.
        calls=[]
        def callback(provider):
            calls.append(provider)
            raise requests_state.LocalDeadline('Model bekleme süresi doldu; geç yanıt uygulanmadı.')
        with patch.object(router,'selection',return_value={'candidates':['groq','gemini'],'skipped':[]}):
            with self.assertRaises(requests_state.LocalDeadline):
                router.run('alice','merhaba dünya',callback)
        self.assertEqual(calls,['groq'])
        self.assertEqual(router._HEALTH,{})

    def test_a_provider_error_that_arrives_after_the_budget_uses_the_same_no_cooldown_path(self):
        # Yalnız callback'in kendi deadline'i değil: taşıma hatası bütçe dolduktan SONRA
        # çıkarsa llm._timed'in hata çıkışı onu LocalDeadline'e çevirir ve router bu kök nedeni
        # taşıma hatası saymaz — sağlıklı aday cezalanmaz, sıradaki aday boşuna denenmez.
        from types import SimpleNamespace
        clock={'t':1000.0}
        stub=SimpleNamespace(monotonic=lambda:clock['t'])
        calls=[]
        def late():
            clock['t']+=5.0    # taşıma bütçeden uzun yaşadı: hata bütçe dolduktan sonra çıktı
            raise llm.CloudError('Groq bağlantısı kurulamadı (ReadTimeout)')
        def callback(provider):
            calls.append(provider)
            return llm._timed(provider,late)
        with patch.object(requests_state,'time',stub), \
                patch.object(router,'selection',return_value={'candidates':['groq','gemini'],'skipped':[]}):
            with requests_state.budget(1):
                with self.assertRaises(requests_state.LocalDeadline) as caught:
                    router.run('alice','merhaba dünya',callback)
        self.assertEqual(calls,['groq'])
        self.assertEqual(router._HEALTH,{})
        self.assertIsInstance(caught.exception.__cause__,llm.CloudError)

    def test_status_shows_owner_cooldown_without_claiming_live_success(self):
        router.configure('alice',True)
        router._HEALTH[('alice','gemini')]={'until':router.time.monotonic()+300}
        router._HEALTH[('bob','groq')]={'until':router.time.monotonic()+300}
        status=router.status('alice')
        policies={r['provider']:r['policy'] for r in status['capabilities']}
        self.assertIn('beklemede',policies['gemini'])
        self.assertNotIn('beklemede',policies['groq'])
        self.assertIn('strict zero-cost',policies['groq'])

    def test_quota_fallback_cooldown_and_routing_trace(self):
        router.configure('alice',True)
        call=Mock(side_effect=[RuntimeError('quota PRIVATE'), 'ollama answer'])
        self.assertEqual(router.run('alice','merhaba',call),'ollama answer')
        self.assertEqual([c.args[0] for c in call.call_args_list],['groq','ollama'])   # Gemini PRIVATE zincirde hiç denenmez
        trace=router.status('alice')['last']
        self.assertEqual(trace['provider'],'ollama');self.assertNotIn('PRIVATE',json.dumps(trace))
        self.assertNotIn('groq',router.candidates('alice','chat'))
        router.configure('bob',True)
        self.assertIn('groq',router.candidates('bob','chat'))

    def test_cooldown_depends_on_error_kind(self):
        class Coded(Exception):
            def __init__(self,code):super().__init__('x');self.code=code
        self.assertEqual(router.cooldown('gemini',Coded(401)),1800)
        self.assertEqual(router.cooldown('groq',llm.LocalModelError('Groq API anahtarı geçersiz ya da yetkisiz.')),1800)
        self.assertEqual(router.cooldown('gemini',Coded(429)),300)
        self.assertEqual(router.cooldown('groq',llm.LocalModelError('Groq yanıt vermedi (429 rate limit)')),300)
        self.assertEqual(router.cooldown('ollama',llm.LocalModelError('Ollama çalışmıyor')),30)
        self.assertEqual(router.cooldown('gemini',ConnectionError('down')),60)

    def test_failed_run_reports_safe_provider_reasons_without_reasking_confirmation(self):
        router.configure('alice',True)
        response=Mock(status_code=429)
        errors=[router.requests.HTTPError('PRIVATE body gem-key',response=response),
                router.requests.ReadTimeout('PRIVATE prompt'),ConnectionError('PRIVATE url')]
        with self.assertRaises(RuntimeError) as caught:
            router.run('alice','python',Mock(side_effect=errors),route='PUBLIC_RESEARCH')
        message=str(caught.exception)
        self.assertIn('gemini: kota veya hız sınırı (HTTPError, HTTP 429)',message)
        self.assertIn('groq: zaman aşımı',message)
        self.assertIn('ollama: bağlantı',message)
        self.assertNotIn('kutusunu işaretle',message)
        self.assertNotIn('PRIVATE',message)
        self.assertNotIn('gem-key',json.dumps(router.status('alice')))
        self.assertEqual(router.cooldown('gemini',errors[0]),300)

    def test_no_candidates_is_distinct_from_failed_call_and_does_not_call_model(self):
        call=Mock(side_effect=AssertionError('no call'))
        with patch.object(router,'selection',return_value={'candidates':[],'skipped':[]}):
            with self.assertRaisesRegex(RuntimeError,'denenecek sağlayıcı yok'):
                router.run('alice','python',call)
        call.assert_not_called()

    def test_router_status_exposes_only_current_owner_safe_last_attempts(self):
        with self.assertRaises(RuntimeError):
            router.run('alice','python',Mock(side_effect=TimeoutError('PRIVATE')))
        with patch.object(router.requests,'post',side_effect=AssertionError('no network')):
            self.assertIn('ollama: zaman aşımı (TimeoutError)',router.handle('alice','router durumu'))
            self.assertNotIn('Son çağrı denemeleri',router.handle('bob','router durumu'))
        self.assertNotIn('PRIVATE',router.handle('alice','router durumu'))

    def test_gemini_quota_never_falls_to_groq_or_ollama_inside_llm(self):
        quota=llm.errors.ClientError(429,{'error':{'message':'quota','status':'RESOURCE_EXHAUSTED'}})
        with patch.object(llm,'current_user',return_value='alice'),patch.object(llm,'_cli',return_value=Mock()), \
             patch.object(llm,'_with_models',side_effect=quota), \
             patch.object(llm,'_groq',side_effect=AssertionError('cross fallback')),patch.object(llm,'_ollama',side_effect=AssertionError('cross fallback')):
            with self.assertRaises(llm.errors.ClientError):llm._send_provider('gemini','merhaba','',100,None)
        with patch.object(llm,'current_user',return_value='alice'),patch.object(llm,'_cli',return_value=Mock()), \
             patch.object(llm,'_with_models',side_effect=llm.errors.ClientError(400,{'error':{'message':'bad'}})),patch.object(llm,'_groq',side_effect=AssertionError('400')):
            with self.assertRaises(llm.errors.ClientError):llm._send_provider('gemini','merhaba','',100,None)

    def test_ollama_uses_big_model_for_code_and_falls_back_to_small(self):
        with patch.object(llm,'_cfg',return_value={'provider':'ollama','url':'http://x','model':'llama3.2'}), \
             patch.object(llm,'load_settings',return_value={}), \
             patch.object(llm,'ollama_models',return_value=['llama3.2','qwen2.5:7b']):
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
             patch.object(llm,'load_settings',return_value={}),patch.object(llm,'ollama_models',return_value=['llama3.2']):
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
        self.assertEqual(route,[('Groq istek/token sınırına takıldı, sıradakine geçildi',False),('Cevap: Gemini',True)])
        self.assertNotIn('secret',str(route));self.assertEqual(llm.take_route(),[])
        llm._timed('groq',lambda:'a');llm._timed('ollama',lambda:'b')
        self.assertEqual(llm.take_route(),[('Cevap: Ollama (yerel)',True)])

    def test_local_mode_never_cloud_and_empty_answer_is_failure(self):
        router.configure('alice',True)
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
            with self.assertRaises(llm.LocalModelError):llm._send_provider('groq','x','',100,None)

    def test_task_classification_and_gizli_image_gate(self):
        self.assertEqual(router.task_type('Python hatasını düzelt'),'code')
        self.assertEqual(router.task_type('PDF belgeyi analiz et'),'analysis')
        self.assertEqual(router.task_type('x',True),'vision')
        with patch.object(llm.privacy,'mode',return_value='gizli'),patch.object(router,'run',side_effect=AssertionError('cloud')):
            self.assertIn('Gizli',llm.ask_image('missing.png','x'))

    def test_auxiliary_gemini_calls_cannot_bypass_budget_policy(self):
        from modules import live
        with patch.object(llm,'provider',return_value='auto'),patch.object(llm,'current_user',return_value='alice'),patch.object(llm,'_cli',side_effect=AssertionError('cloud')):
            self.assertFalse(llm.gemini_aux_allowed());self.assertFalse(live.enabled())
            self.assertEqual(llm.model_check()['state'],'budget')
            with self.assertRaises(ValueError):llm.embed(['x'])
            with self.assertRaises(RuntimeError):llm.transcribe(data=b'wav')
            router.configure('alice',True);self.assertFalse(llm.gemini_aux_allowed())   # onaylı hesapta bile içerik Gemini'ye gitmez

    def test_corrupt_router_state_fails_closed_and_still_allows_local_fallback(self):
        for content in ('[]','null','"invalid"','{"cloud_free_confirmed":"false","key":42}'):
            router.owner_path('alice').write_text(content)
            self.assertFalse(router.settings('alice')['cloud_free_confirmed'])
            self.assertEqual(router.candidates('alice','chat'),['ollama'])
            self.assertNotIn('model',router.status('alice'))

    def test_cancellation_after_provider_response_is_not_success(self):
        with patch.object(router.requests_state,'check',side_effect=[None,requests_state.Cancelled()]):
            with self.assertRaises(requests_state.Cancelled):router.run('alice','test',lambda p:'late answer')
        self.assertEqual(router.status('alice')['last'],{})

    def test_ui_auto_now_calls_auto_provider(self):
        from modules import nxapi
        with patch.object(llm,'set_provider') as choose,patch.object(nxapi,'save_settings'),patch.object(nxapi,'ui_settings',return_value={}):
            nxapi.ui_set('ai_mode','auto');choose.assert_called_once_with('auto')

    def test_missing_groq_key_is_reported_without_reading_or_exposing_a_key(self):
        router.configure('alice',True)
        with patch.object(llm,'user_groq_key',return_value=''):
            with self.assertRaises(RuntimeError) as caught:
                router.run('alice','araştırma raporu',Mock(side_effect=TimeoutError('PRIVATE')))
            last=router.status('alice')['last']
        self.assertIn('groq: Bu kullanıcı için API anahtarı eksik',str(caught.exception))
        groq_skip=next(row for row in last['skipped'] if row['provider']=='groq')
        self.assertEqual(groq_skip['reason'],'Bu kullanıcı için API anahtarı eksik')
        self.assertEqual(groq_skip['reason_code'],'PROVIDER_CONFIGURATION_REQUIRED')
        self.assertEqual(groq_skip['seconds'],0)
        self.assertNotIn('PRIVATE',json.dumps(last))

    def test_groq_cooldown_is_visible_and_expiry_makes_it_eligible(self):
        router.configure('alice',True)
        router._HEALTH[('alice','groq')]={'until':router.time.monotonic()+300}
        selected=router.selection('alice','analysis')
        self.assertNotIn('groq',selected['candidates'])
        row=next(r for r in selected['skipped'] if r['provider']=='groq')
        self.assertIn('beklemede',row['reason']);self.assertGreater(row['seconds'],0)
        router._HEALTH[('alice','groq')]['until']=router.time.monotonic()-1
        self.assertIn('groq',router.candidates('alice','analysis'))

    def test_429_label_does_not_claim_daily_quota_was_exhausted(self):
        error=router.requests.HTTPError(response=Mock(status_code=429))
        self.assertEqual(router.failure_kind(error),'quota')
        self.assertIn('istek/token sınır',router.failure_text(error))
        self.assertNotIn('dol',router.failure_text(error))

    def test_ollama_missing_hint_is_safe_and_specific(self):
        from modules import ollama_hint
        with patch.object(router,'candidates',return_value=['ollama']), \
             patch.object(router,'selection',return_value={'candidates':['ollama'],'skipped':[]}):
            with self.assertRaises(RuntimeError) as caught:
                router.run('alice','test',Mock(side_effect=llm.LocalModelError(ollama_hint.need('Yerel model'))))
        message=str(caught.exception)
        self.assertIn('ollama: Ollama yüklü değil ya da çalışmıyor (ollama.com adresinden kurup `ollama serve` ile başlat)',message)
        self.assertIn('(LocalModelError)',message)
        self.assertEqual(router.status('alice')['last']['attempts'][0].get('hint'),'ollama_missing')

    def test_ollama_model_missing_does_not_get_install_hint(self):
        error=llm.LocalModelError('Model bulunamadı; ollama pull llama3.2 çalıştır.')
        with patch.object(router,'candidates',return_value=['ollama']), \
             patch.object(router,'selection',return_value={'candidates':['ollama'],'skipped':[]}):
            with self.assertRaises(RuntimeError) as caught:
                router.run('alice','test',Mock(side_effect=error))
        self.assertNotIn('Ollama yüklü değil',str(caught.exception))
        self.assertNotIn('hint',router.status('alice')['last']['attempts'][0])
        self.assertIn('ollama: çağrı başarısız (LocalModelError)',str(caught.exception))

    def test_groq_429_detail_is_unchanged(self):
        attempt={'provider':'groq','ok':False,'error':'HTTPError','kind':'quota','status':429}
        self.assertEqual(router.failure_detail(attempt),'groq: kota veya hız sınırı (HTTPError, HTTP 429)')

    def test_ollama_hint_never_exposes_raw_error_text(self):
        from modules import ollama_hint
        secret='PRIVATE'
        error=llm.LocalModelError(ollama_hint.need('Yerel model') + secret)
        with patch.object(router,'candidates',return_value=['ollama']), \
             patch.object(router,'selection',return_value={'candidates':['ollama'],'skipped':[]}):
            with self.assertRaises(RuntimeError) as caught:
                router.run('alice','test',Mock(side_effect=error))
        self.assertNotIn(secret,str(caught.exception))
        self.assertNotIn(secret,json.dumps(router.status('alice')['last']))

    def test_caller_can_only_narrow_router_candidates_and_exclude_local_fallback(self):
        router.configure('alice', True)
        calls = []
        def answer(provider):
            calls.append(provider)
            return provider
        self.assertEqual(router.run('alice', 'brain semantic proposal', answer,
                                    exclude_providers={'ollama'}), 'groq')
        self.assertEqual(calls, ['groq'])
        with self.assertRaises(ValueError):
            router.run('alice', 'brain semantic proposal', answer,
                       exclude_providers={'invented-provider'})

if __name__=='__main__':unittest.main()
