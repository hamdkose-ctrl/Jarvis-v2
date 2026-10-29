import unittest
from datetime import datetime,timezone,timedelta
from modules import news_temporal as nt
class EventEvidence(unittest.TestCase):
    def setUp(self):
        self.request='İstanbul yarın okullar tatil mi'
        self.scope=nt.request_scope(self.request,now=datetime(2026,10,29,9,tzinfo=timezone(timedelta(hours=3))))
        self.quote='İstanbul genelinde 30 Ekim 2026 tarihinde eğitim öğretime bir gün ara verilmiştir.'
        self.payload={'supported':True,'answer':self.quote,'quotes':[self.quote],'event_date':'2026-10-30','scope':'İstanbul'}
    def check(self,url='https://www.istanbul.gov.tr/duyuru'):
        return nt.validate_event_evidence(self.payload,source_text=self.quote,source_url=url,request=self.request,scope=self.scope)
    def test_event_date_not_publication_date(self):self.assertEqual(self.check()['quotes'],[self.quote])
    def test_wrong_event_date_rejected(self):
        self.payload['event_date']='2026-10-29'
        with self.assertRaises(ValueError):self.check()
    def test_news_republication_not_official_decision(self):
        with self.assertRaises(ValueError):self.check('https://news.example/story')
    def test_missing_requested_place_not_guessed(self):
        self.request='yarın okullar tatil mi'
        with self.assertRaises(ValueError):self.check()
    def test_date_only_in_metadata_not_quote_rejected(self):
        self.quote='İstanbul genelinde eğitim öğretime bir gün ara verilmiştir.'
        self.payload['quotes']=[self.quote]
        with self.assertRaises(ValueError):self.check()

    def test_missing_scope_has_concrete_question(self):
        self.request='yarın okullar tatil mi'
        with self.assertRaises(nt.EventContextRequired) as caught:self.check()
        self.assertIn('Hangi yer',str(caught.exception))
