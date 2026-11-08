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

    def test_transport_read_timeout_is_capped_by_the_active_budget_never_waisted(self):
        # Bütçe yoksa taşıma kendi sınırında kalır; bütçe varsa okuma o sınırın üstüne çıkamaz.
        self.assertEqual(llm.transport_timeout(30),30)
        with requests_state.budget(12):
            self.assertLessEqual(llm.transport_timeout(30),12)
            self.assertEqual(llm.transport_timeout(5),5)
        with requests_state.budget(.1):
            self.assertEqual(llm.transport_timeout(30),1.0)

    def test_groq_is_posted_with_the_budgeted_read_timeout(self):
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
            self.assertEqual(connect,5);self.assertLessEqual(read,3.0)

    def test_a_response_arriving_after_the_budget_is_dropped_not_applied(self):
        # Hatanın gerçek yeri: taşıma yanıtı döndürdükten SONRAKI kontrol. Geç yanıt kullanılmaz.
        def late():
            time.sleep(.08)
            return '{"operation":"direct_action","actions":[{"capability_id":"documents.export"}]}'
        with requests_state.budget(.02):
            with self.assertRaises(requests_state.LocalDeadline):llm._timed('groq',late)
