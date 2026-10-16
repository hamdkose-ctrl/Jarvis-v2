import unittest
from types import SimpleNamespace
from unittest.mock import patch

from modules import publisher_news, research_evidence


class NewsCoverageReadabilityTests(unittest.TestCase):
    def test_broad_research_requires_catalog_scan_at_final_completion(self):
        request='Son 7 gündeki Türkiye yapay zekâ gelişmelerini araştır, doğrulanmış kaynaklarla rapor oluştur ve dosyaya kaydet.'
        job={'request':request,'goals':[{'state':'done'},{'state':'done'}],'steps':[],'news_catalog_attempted':[]}
        fake_context=SimpleNamespace(get=lambda:'alice')
        with patch('modules.llm._key_context',fake_context),patch('modules.goal_executor.latest',return_value=job):
            with self.assertRaisesRegex(ValueError,'0/4'):
                publisher_news.broad_research(request)
            job['news_catalog_attempted']=sorted(publisher_news.catalog_keys())
            self.assertTrue(publisher_news.broad_research(request))

    def test_individual_news_preview_is_hidden_when_chat_should_wait_for_report(self):
        output={'news_article':{'url':'https://example.com/a','title':'Haber','published':'2026-10-16','text':'metin'}}
        self.assertEqual(research_evidence.preview(output),'')

    def test_report_preview_is_balanced_and_readable(self):
        source={'url':'https://example.com/a','title':'Yapay zekâ gelişmesi','published':'2026-10-16','text':'Yapay zekâ hakkında yeterli ve doğrulanmış kaynak metni.'}
        child={'news_article':source}
        output={'news_report_evidence':{'sources':{'s1':child}}}
        text=research_evidence.preview(output)
        self.assertIn('Özet',text)
        self.assertIn('Öne çıkan gelişmeler',text)
        self.assertIn('1 doğrulanmış gelişme',text)
        self.assertEqual(text.count('Yapay zekâ gelişmesi'),1)


if __name__=='__main__':
    unittest.main()
