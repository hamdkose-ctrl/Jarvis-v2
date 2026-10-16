import unittest

from modules import research_evidence


class NewsRenderReadabilityTests(unittest.TestCase):
    def setUp(self):
        self.url='https://example.org/news/example'
        self.source={'url':self.url,'title':'Örnek yapay zekâ haberi','published':'2026-10-16','text':'Yapay zekâ hakkında yeterli kaynak metni.'}

    def test_single_article_preview_keeps_plain_full_url_without_counter(self):
        text=research_evidence.preview({'news_article':self.source})
        self.assertNotIn('haber,',text)
        self.assertNotIn('farklı yayıncı',text)
        self.assertIn('Kaynak: '+self.url,text)
        self.assertNotIn('Kaynak: <'+self.url+'>',text)

    def test_file_backed_report_preview_is_silent(self):
        output={'file':'C:/rapor.md','news_report_evidence':{'sources':{'s1':{'news_article':self.source}}}}
        self.assertEqual(research_evidence.preview(output),'')

    def test_legacy_report_preview_without_file_keeps_old_contract(self):
        output={'news_report_evidence':{'sources':{'s1':{'news_article':self.source}}}}
        text=research_evidence.preview(output)
        self.assertIn('1 haber, 1 farklı yayıncı',text)
        self.assertIn(self.url,text)


if __name__=='__main__':
    unittest.main()
