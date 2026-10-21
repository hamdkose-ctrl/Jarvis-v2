"""RSS makbuzu yalnız aynı tekil haber bağlantısına tarih sağlayabilir."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class NewsRssReceiptTests(unittest.TestCase):
    def test_registered_feed_entry_binds_date_to_exact_article_url(self):
        from modules import news_rss_receipts
        receipt = news_rss_receipts.receipt(
            provider_id='trt_haber', feed_url='https://www.trthaber.com/rss.xml',
            entry={'url':'https://www.trthaber.com/haber/gundem/ornek-1.html',
                   'title':'Örnek haber', 'published':'2026-10-21T09:00:00+03:00'},
            article_url='https://www.trthaber.com/haber/gundem/ornek-1.html')
        self.assertEqual(receipt['published'],'2026-10-21')
        self.assertEqual(receipt['article_url'],'https://www.trthaber.com/haber/gundem/ornek-1.html')

    def test_page_without_date_uses_only_its_bound_rss_receipt(self):
        from modules import research_evidence
        response={'url':'https://www.trthaber.com/haber/gundem/ornek-1.html',
                  'body':b'<article><h1>Ornek haber</h1><p>Bu tekil haber govdesi dogrulanabilir uzunlukta metin icerir ve kaynak metni aynen korunur.</p></article>'}
        bound={'article_url':response['url'],'published':'2026-10-21','title':'Ornek haber'}
        result=research_evidence.article(response,rss_receipt=bound)
        self.assertEqual(result['published'],'2026-10-21')
        with self.assertRaises(ValueError):
            research_evidence.article(response,rss_receipt={**bound,'article_url':'https://www.trthaber.com/haber/gundem/diger.html'})

    def test_headlines_seals_registered_rss_receipts(self):
        from modules import domain_tools
        feed='https://www.trthaber.com/rss.xml'
        article='https://www.trthaber.com/haber/gundem/ornek-1.html'
        response={'url':feed,'body':b'<rss></rss>'}
        rows=[{'url':article,'title':'Ornek haber','published':'2026-10-21T09:00:00+03:00'}]
        with patch('modules.service_store.identity'), patch('modules.public_sources.entries',return_value=rows):
            result=domain_tools.headlines('alice',feed,fetcher=lambda _url: response)
        self.assertEqual(result['rss_receipts'][article]['published'],'2026-10-21')
        self.assertEqual(result['rss_receipts'][article]['feed_url'],feed)

    def test_research_receives_only_matching_sealed_headlines_receipt(self):
        from modules import goal_tools, specialist_orchestrator
        article='https://www.trthaber.com/haber/gundem/ornek-1.html'
        other='https://www.trthaber.com/haber/gundem/diger.html'
        receipt={'provider_id':'trt_haber','feed_url':'https://www.trthaber.com/rss.xml',
                 'article_url':article,'title':'Ornek haber','published':'2026-10-21'}
        output=goal_tools.local_result('alice','data','basliklar',structured={
            'items':[{'url':article,'title':'Ornek haber','published':'2026-10-21'}],
            'rss_receipts':{article:receipt}})
        runtime=SimpleNamespace(profile=SimpleNamespace(slug='alice'))
        job={'owner':'alice','request':'guncel haberleri araştır','outputs':{'h':output}}
        step={'tool':'research','input':{'url':article},'depends':['h']}
        expected={'state':'done','text':'kanıt'}
        with patch('modules.model_free_news.run',return_value=expected) as run:
            result=specialist_orchestrator.execute_step(runtime,job,step,{'source_only':True})
        self.assertIs(result,expected)
        self.assertEqual(run.call_args.kwargs['rss_receipt'],receipt)
        step['input']={'url':other}
        with patch('modules.model_free_news.run',return_value=expected) as run:
            specialist_orchestrator.execute_step(runtime,job,step,{'source_only':True})
        self.assertIsNone(run.call_args.kwargs['rss_receipt'])


if __name__ == '__main__':
    unittest.main()
