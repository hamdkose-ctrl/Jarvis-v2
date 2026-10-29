import unittest
from datetime import datetime,timezone,timedelta
from modules import news_temporal as nt
class AuthorityReview(unittest.TestCase):
    def test_other_jurisdiction_does_not_become_authority_by_gov_suffix(self):
        text='İstanbul genelinde 30 Ekim 2026 tarihinde eğitim öğretime bir gün ara verilmiştir.'
        data={'supported':True,'answer':text,'quotes':[text],'event_date':'2026-10-30','scope':'İstanbul'}
        scope=nt.request_scope('İstanbul yarın okullar tatil mi',now=datetime(2026,10,29,9,tzinfo=timezone(timedelta(hours=3))))
        with self.assertRaises(ValueError):
            nt.validate_event_evidence(data,source_text=text,source_url='https://www.ankara.gov.tr/duyuru',request='İstanbul yarın okullar tatil mi',scope=scope)
