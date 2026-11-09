"""Real bounded workers, concurrent research and source evidence contracts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from modules import llm,model_wait,nxapi,task_agents,research_evidence,requests_state

class ModelWaitTests(unittest.TestCase):
    def setUp(self):
        token=llm._key_context.set('wait-tests');self.addCleanup(llm._key_context.reset,token)

    def test_legitimate_parallel_model_requests_are_serialized_without_rejection(self):
        lock=threading.Lock();active=0;maximum=0
        def model(*args,**kwargs):
            nonlocal active,maximum
            with lock:active+=1;maximum=max(maximum,active)
            time.sleep(.02)
            with lock:active-=1
            return 'answer'
        def call():
            token=llm._key_context.set('parallel-tests')
            try:return model_wait.ask('question',seconds=1)
            finally:llm._key_context.reset(token)
        with patch.object(llm,'ask',side_effect=model),ThreadPoolExecutor(max_workers=3) as pool:
            self.assertEqual(list(pool.map(lambda _:call(),range(3))),['answer']*3)
        self.assertEqual(maximum,1)

    def test_research_and_writer_timeout_do_not_seal_or_write_late_delivery(self):
        for kind,data in [('research',{'url':'https://example.org/'}),('writer',{'instruction':'rapor','filename':'rapor.md'})]:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                release=threading.Event();exited=threading.Event()
                def model(*args,**kwargs):
                    try:release.wait(1);return 'late answer'
                    finally:exited.set()
                with patch.object(model_wait,'DEFAULT_SECONDS',.03),patch.object(llm,'ask',side_effect=model),patch.object(nxapi,'FILES_DIR',Path(tmp)),patch('modules.browser.page_text',return_value='Actual fetched source evidence. '*20):
                    try:
                        with self.assertRaisesRegex(RuntimeError,'Geç yanıt'):
                            task_agents.worker('wait-tests',{'agent':kind,'input':data},{})
                        with self.assertRaisesRegex(RuntimeError,'henüz kapanmadı'):model_wait.ask('second',seconds=.1)
                    finally:
                        release.set();self.assertTrue(exited.wait(1))
                        deadline=time.monotonic()+1
                        while model_wait._PENDING.get('wait-tests') and time.monotonic()<deadline:time.sleep(.001)
                    self.assertEqual(list(Path(tmp).rglob('*.md')),[])

    def test_date_is_present_in_research_and_writer_prompts(self):
        quote='Gerçek kaynakta bulunan doğrulanabilir uzun alıntı.'
        source=quote*4
        answer=json.dumps({'supported':True,'answer':'Kaynakla sınırlı yanıt','quotes':[quote]})
        with tempfile.TemporaryDirectory() as tmp,patch.object(nxapi,'FILES_DIR',Path(tmp)),patch('modules.browser.page_text',return_value=source),patch.object(llm,'ask',side_effect=[answer,'Rapor']) as model:
            task_agents.worker('wait-tests',{'agent':'research','input':{'url':'https://example.org/'}},{})
            task_agents.worker('wait-tests',{'agent':'writer','input':{'instruction':'Rapor yaz','filename':'rapor.md'}},{})
        today=datetime.now(timezone(timedelta(hours=3))).date().isoformat()
        for call in model.call_args_list:self.assertIn(today,call.args[0])

    def test_no_information_or_invented_quotes_are_not_research_evidence(self):
        source='This is a real source page containing one supported statement.'
        for answer in ['Bu sayfa soruya yanıt vermiyor','No relevant information was found.',
                       json.dumps({'supported':False,'answer':'','quotes':[]}),
                       json.dumps({'supported':True,'answer':'Uydurma','quotes':['This quote does not appear in the source.']})]:
            with self.subTest(answer=answer),self.assertRaises(ValueError):research_evidence.parse(answer,source)

    def test_cancelled_model_budget_blocks_fallback_without_cancelling_another_request(self):
        stop=threading.Event()
        with requests_state.budget(5,cancel=stop):
            requests_state.check();stop.set()
            with self.assertRaises(requests_state.Cancelled):requests_state.check()
        requests_state.check()

    def test_local_budget_expiry_is_its_own_cause_and_keeps_timeout_compatibility(self):
        # Yerel süre aşımı kullanıcı iptali de sağlayıcı zaman aşımı da değildir; fakat eski
        # `except TimeoutError` yollarını kırmamak için o türün alt sınıfı olarak kalır.
        with requests_state.budget(0):
            with self.assertRaises(requests_state.LocalDeadline) as caught:
                requests_state.check()
        self.assertIsInstance(caught.exception,TimeoutError)
        self.assertNotIsInstance(caught.exception,requests_state.Cancelled)

    def test_budget_remaining_is_visible_only_while_a_budget_is_active_and_nests_tighter(self):
        self.assertIsNone(requests_state.budget_remaining())
        with requests_state.budget(30):
            self.assertLess(requests_state.budget_remaining(),30)
            self.assertGreater(requests_state.budget_remaining(),20)
            with requests_state.budget(5):
                self.assertLessEqual(requests_state.budget_remaining(),5)
        self.assertIsNone(requests_state.budget_remaining())

    def test_socket_timeouts_follow_the_remaining_budget_without_beating_the_deadline(self):
        # Soket zaman aşımları toplam deadline değildir: bütçe yoksa kendi sabitleri kalır,
        # bütçe varsa hiçbiri kalan sürenin üstüne çıkmaz. 30 sn'lik ortak politika varken
        # okuma, gerçek koşuda kanıtlanan 13 sn'lik yanıtı kesmeyecek kadar geniştir.
        self.assertEqual(llm.transport_timeouts(5,30),(5,30))
        with requests_state.budget(30):
            remaining=requests_state.budget_remaining()
            connect,read=llm.transport_timeouts(5,30)
            self.assertGreaterEqual(read,13)
            self.assertLessEqual(connect,remaining)
            self.assertLessEqual(read,remaining)
        with requests_state.budget(12):
            connect,read=llm.transport_timeouts(5,30)
            self.assertLessEqual(max(connect,read),12)
        with requests_state.budget(.01):
            connect,read=llm.transport_timeouts(5,30)
            self.assertGreater(connect,0);self.assertGreater(read,0)

    def test_groq_is_posted_with_socket_timeouts_inside_the_active_budget(self):
        seen=[]
        def post(url,**kwargs):
            seen.append(kwargs['timeout']);raise llm.requests.ConnectionError('test: ağ yok')
        with patch.object(llm,'user_groq_key',return_value='test-only'), \
                patch.object(llm,'groq_model',return_value='test-model'), \
                patch.object(llm,'_limited',return_value=None), \
                patch.object(llm,'_fallback_states',{}), \
                patch('modules.smart_router.settings',return_value={}), \
                patch('modules.usage_meter.record'),patch('modules.usage_meter.observe_limits'), \
                patch('modules.failure_policy.backoff_sleep'), \
                patch.object(llm.requests,'post',side_effect=post), \
                requests_state.budget(3):
            with self.assertRaises(llm.CloudError):llm._groq([{'role':'user','content':'x'}],'',8)
        self.assertTrue(seen)
        for connect,read in seen:
            self.assertLessEqual(connect,3.0);self.assertLessEqual(read,3.0)

    def test_a_provider_http_timeout_is_not_turned_into_our_local_deadline(self):
        # Sağlayıcının soketi gerçekten zaman aşımına uğrarsa hatanın türü CloudError kalır;
        # kendi bütçemizin dolmasıyla aynı kök neden gibi etiketlenmez.
        from modules import failure_policy
        def post(url,**kwargs):
            raise llm.requests.exceptions.ReadTimeout('simulated provider read timeout')
        with patch.object(llm,'user_groq_key',return_value='test-only'), \
                patch.object(llm,'groq_model',return_value='test-model'), \
                patch.object(llm,'_limited',return_value=None), \
                patch.object(llm,'_fallback_states',{}), \
                patch('modules.smart_router.settings',return_value={}), \
                patch('modules.usage_meter.record'),patch('modules.usage_meter.observe_limits'), \
                patch('modules.failure_policy.backoff_sleep'), \
                patch.object(llm.requests,'post',side_effect=post), \
                requests_state.budget(30):
            with self.assertRaises(llm.CloudError) as caught:
                llm._groq([{'role':'user','content':'x'}],'',8)
        self.assertNotIsInstance(caught.exception,requests_state.LocalDeadline)
        self.assertEqual(failure_policy.classify(caught.exception),failure_policy.TIMEOUT)

    def test_a_response_arriving_after_the_budget_is_dropped_not_applied(self):
        # Hatanın gerçek yeri: taşıma yanıtı döndürdükten SONRAKI kontrol. Geç yanıt kullanılmaz.
        def late():
            time.sleep(.08)
            return '{"operation":"direct_action","actions":[{"capability_id":"documents.export"}]}'
        with requests_state.budget(.02):
            with self.assertRaises(requests_state.LocalDeadline):llm._timed('groq',late)

    def test_an_error_raised_after_the_budget_is_named_by_our_deadline_not_the_transport(self):
        # Denetim bulgusu: bütçe/iptal kontrolü yalnız başarılı dönüşteydi, hata çıkışında yoktu.
        # Bütçe dolduktan sonra patlayan bir taşıma hatası eskisi gibi sağlayıcı hatası olarak
        # çıkıyor ve sağlayıcıyı cooldown + sıradaki aday yoluna sokuyordu.
        from modules import failure_policy
        def late_failure():
            time.sleep(.08)
            raise llm.CloudError('Groq bağlantısı kurulamadı (ReadTimeout)')
        with requests_state.budget(.02):
            with self.assertRaises(requests_state.LocalDeadline) as caught:llm._timed('groq',late_failure)
        self.assertEqual(failure_policy.classify(caught.exception),failure_policy.LOCAL_TIMEOUT)
        self.assertEqual(failure_policy.cooldown_seconds('groq',caught.exception),0)
        self.assertFalse(failure_policy.network_unavailable(caught.exception))
        # Asıl HTTP hatası kaybolmaz: kök nedenin altında türü ve mesajıyla durur.
        self.assertIsInstance(caught.exception.__cause__,llm.CloudError)
        self.assertEqual(str(caught.exception.__cause__),'Groq bağlantısı kurulamadı (ReadTimeout)')

    def test_a_provider_error_inside_a_live_budget_keeps_its_own_type_and_message(self):
        # Bütçe dolmamışsa hata çıkışı hükmü vermez: gerçek HTTP hatası aynen yukarı çıkar,
        # LocalDeadline'e dönüştürülmez ve yutulmaz.
        from modules import failure_policy
        boom=llm.CloudError('Groq bağlantısı kurulamadı (ReadTimeout)')
        def raiser():raise boom
        with requests_state.budget(30):
            with self.assertRaises(llm.CloudError) as caught:llm._timed('groq',raiser)
        self.assertIs(caught.exception,boom)
        self.assertNotIsInstance(caught.exception,requests_state.LocalDeadline)
        self.assertEqual(failure_policy.classify(caught.exception),failure_policy.TIMEOUT)
        self.assertGreater(failure_policy.cooldown_seconds('groq',caught.exception),0)

    def test_a_late_key_rejection_is_not_buried_under_our_local_deadline(self):
        # Denetim bulgusu P2-1: bütçe dolduktan sonra gelen 401/403 taşımanın KESIN bulgusudur.
        # LocalDeadline'e çevrilirse router kimlik yolunu hiç işlemez, bozuk anahtar sıradaki
        # turda yeniden denenir ve kullanıcıya yanlış "bekleme süresi doldu" tanısı görünür.
        from modules import failure_policy
        late_401=llm.CloudError('Groq API anahtarı geçersiz ya da yetkisiz.')
        def raiser():
            time.sleep(.08)
            raise late_401
        with requests_state.budget(.02):
            with self.assertRaises(llm.CloudError) as caught:llm._timed('groq',raiser)
        self.assertIs(caught.exception,late_401)
        self.assertNotIsInstance(caught.exception,requests_state.LocalDeadline)
        self.assertEqual(failure_policy.classify(caught.exception),failure_policy.AUTH)
        self.assertGreater(failure_policy.cooldown_seconds('groq',caught.exception),0)

    def test_a_late_rate_limit_keeps_the_quota_diagnosis_and_its_wait(self):
        # 429 da kesin bir yanıttır: bekleme/kota müdahalesi yerel bütçe kararının altında kaybolmaz.
        from modules import failure_policy
        late_429=llm.CloudError('Groq yanıt vermedi (HTTP 429, bekleme süresi dolmadı)')
        def raiser():
            time.sleep(.08)
            raise late_429
        with requests_state.budget(.02):
            with self.assertRaises(llm.CloudError) as caught:llm._timed('groq',raiser)
        self.assertIs(caught.exception,late_429)
        self.assertEqual(failure_policy.classify(caught.exception),failure_policy.RATE_LIMIT)
        self.assertGreater(failure_policy.cooldown_seconds('groq',caught.exception),0)

    def test_a_late_plain_wait_still_ends_as_our_local_deadline(self):
        # Ayıran regresyon: beklemenin kendisi bütçeyi aştıysa hüküm yerel deadline'dır ve
        # sağlıklı sağlayıcı ceza almaz. Kimlik/kota bulgusundan farkı burada test edilir.
        from modules import failure_policy
        def raiser():
            time.sleep(.08)
            raise llm.CloudError('Groq bağlantısı kurulamadı (ReadTimeout)')
        with requests_state.budget(.02):
            with self.assertRaises(requests_state.LocalDeadline) as caught:llm._timed('groq',raiser)
        self.assertEqual(failure_policy.classify(caught.exception),failure_policy.LOCAL_TIMEOUT)
        self.assertEqual(failure_policy.cooldown_seconds('groq',caught.exception),0)

    def test_the_budget_check_never_reinterprets_process_control_signals(self):
        # Yakalama bilerek Exception ile sınırlı: SystemExit/KeyboardInterrupt bir model
        # bulgusu değildir, bütçe dolmuş olsa bile kendi gibi yukarı çıkar.
        for signal in (KeyboardInterrupt('iptal'),SystemExit(2)):
            with self.subTest(signal=type(signal).__name__):
                def raiser():
                    time.sleep(.08)
                    raise signal
                with requests_state.budget(.02):
                    with self.assertRaises(type(signal)) as caught:llm._timed('groq',raiser)
                self.assertIs(caught.exception.__class__,type(signal))
                self.assertNotIsInstance(caught.exception,requests_state.LocalDeadline)
