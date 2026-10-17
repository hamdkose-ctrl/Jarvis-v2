import unittest

from modules import research_evidence


class ChatFirstResearchTests(unittest.TestCase):
    def test_news_does_not_create_file_without_explicit_file_request(self):
        request='İstanbul’da sel oldu, son durum ne? Güncel haberleri araştır.'
        self.assertTrue(research_evidence.news_requested(request))
        self.assertFalse(research_evidence.file_requested(request))
        with self.assertRaisesRegex(ValueError,'doğrudan sohbette'):
            research_evidence.news_report_requested(request,'Özet rapor hazırla',{})

    def test_explicit_file_request_keeps_news_report_flow(self):
        request='Son 7 gündeki Türkiye yapay zekâ gelişmelerini araştır ve raporu dosyaya kaydet'
        self.assertTrue(research_evidence.file_requested(request))
        source={'state':'done','news_article':{'url':'https://example.org/haber','title':'Haber','published':'2026-10-17','text':'Kaynak metni'}}
        self.assertTrue(research_evidence.news_report_requested(request,'Raporu yaz',{'s1':source}))

    def test_single_news_preview_shows_finding_not_only_title_and_link(self):
        finding='Kadıköy ve Üsküdar için ulaşımda aksama bildirildi. Kaynak açıklaması güncel durumu doğruluyor.'
        output={
            'state':'done','text':finding+'\nKaynak: https://example.org/sel',
            'news_article':{'url':'https://example.org/sel','title':'İstanbul sel son durum','published':'2026-10-17','text':'Kaynak metni'},
        }
        preview=research_evidence.preview(output)
        self.assertIn('Kadıköy ve Üsküdar',preview)
        self.assertIn('https://example.org/sel',preview)


if __name__=='__main__':
    unittest.main()
