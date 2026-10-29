import copy
import unittest
from datetime import datetime, timezone
from modules import news_temporal, news_policy, task_results

class EventReceiptTests(unittest.TestCase):
    def setUp(self):
        self.reference=datetime(2026,10,29,8,tzinfo=timezone.utc)
        self.request='İstanbul yarın okullar tatil haberi doğru mu'
        quote='İstanbul genelinde 30 Ekim 2026 tarihinde eğitim öğretime bir gün ara verilmiştir.'
        text=quote+' Bu açıklama yetkili makam tarafından yayımlanmıştır.'
        self.output={'state':'done','text':quote,'source':'https://www.istanbul.gov.tr/duyuru',
            'source_chars':len(text),'source_quotes':[quote], 'event_evidence':{
                'claim':{'supported':True,'answer':quote,'quotes':[quote],'event_date':'2026-10-30','scope':'İstanbul'},
                'source_text':text,'request':self.request,'reference':self.reference.isoformat()}}
    def test_persisted_research_receipt_validated(self):
        self.assertTrue(task_results.check('research',self.output))
    def test_quote_tamper_rejected(self):
        self.output['source_quotes']=['başka alıntı']
        with self.assertRaises(ValueError):task_results.check('research',self.output)
    def test_original_request_and_reference_bound(self):
        with self.assertRaises(ValueError):news_temporal.event_receipt(self.output,request='başka istek')
        with self.assertRaises(ValueError):news_temporal.event_receipt(self.output,reference=datetime(2026,10,30,tzinfo=timezone.utc))
    def test_event_completion_uses_primary_evidence_not_two_publishers(self):
        job={'request':self.request,'created':self.reference.timestamp(),'steps':[{'id':'r','tool':'research'}],
             'outputs':{'r':self.output},'state':'running'}
        news_policy.check_completion(job,{'text':self.request},['r'],final=True)
        job['outputs']['r']=copy.deepcopy(self.output)
        job['outputs']['r'].pop('event_evidence')
        with self.assertRaises(ValueError):news_policy.check_completion(job,{'text':self.request},['r'],final=True)
