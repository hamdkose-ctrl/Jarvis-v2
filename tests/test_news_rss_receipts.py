"""RSS makbuzu yalnız aynı tekil haber bağlantısına tarih sağlayabilir."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class NewsRssReceiptTests(unittest.TestCase):
    def test_registered_feed_entry_binds_date_to_exact_article_url(self):
        from modules import news_rss_receipts
        receipt = news_rss_receipts.receipt(
            provider_id='trt_haber', feed_url='https://www.trthaber.com/sondakika_articles.rss',
            entry={'url':'https://www.trthaber.com/haber/gundem/ornek-1.html',
                   'title':'Örnek haber', 'published':'2026-10-21T09:00:00+03:00'},
            article_url='https://www.trthaber.com/haber/gundem/ornek-1.html')
        self.assertEqual(receipt['published'],'2026-10-21')
        self.assertEqual(receipt['article_url'],'https://www.trthaber.com/haber/gundem/ornek-1.html')

    def test_registered_aa_feed_is_available_for_chat_recovery(self):
        from modules import news_rss_receipts, publisher_news
        self.assertEqual(
            publisher_news.chat_recovery_index('https://www.aa.com.tr/tr/gundem'),
            news_rss_receipts.PROVIDERS['anadolu_ajansi']['feed_url'])

    def test_rfc2822_feed_date_is_normalized_for_a_bound_article(self):
        from modules import news_rss_receipts
        result=news_rss_receipts.receipt(
            provider_id='anadolu_ajansi', feed_url='https://www.aa.com.tr/tr/rss/default?cat=guncel',
            entry={'url':'https://www.aa.com.tr/tr/gundem/ornek/1', 'title':'Örnek',
                   'published':'Thu, 22 Oct 2026 09:02:35 +0300'},
            article_url='https://www.aa.com.tr/tr/gundem/ornek/1')
        self.assertEqual(result['published'],'2026-10-22')

    def test_general_chat_prioritizes_registered_feeds_within_four_slots(self):
        from modules import publisher_news
        selected=publisher_news.chat_recovery_indexes('son dakika haberleri',[])
        self.assertEqual(len(selected),4)
        self.assertEqual(selected[:2],[
            'https://www.ntv.com.tr/turkiye.rss',
            'https://www.trthaber.com/sondakika_articles.rss'])
        self.assertIn('https://www.aa.com.tr/tr/rss/default?cat=guncel',selected)
        self.assertIn('https://www.ntv.com.tr/turkiye.rss',selected)
        self.assertIn('https://www.trthaber.com/sondakika_articles.rss',selected)

    def test_chat_recovery_research_keeps_its_headlines_dependency(self):
        from modules import news_recovery
        runtime=SimpleNamespace(profile=SimpleNamespace(slug='alice'),emit=lambda *_args:None)
        job={'owner':'alice','request':'son dakika haberleri','state':'running',
             'goals':[{'text':'son dakika haberleri','state':'pending','evidence':[]}],
             'steps':[],'outputs':{}}
        headlines={'state':'done','structured':{'items':[{'url':'https://example.test/haber/1','title':'Örnek'}]},
                   'local_evidence':'data'}
        article={'state':'done','news_article':{'url':'https://example.test/haber/1'},'source_quotes':['Kanıt']}
        with patch('modules.publisher_news.chat_recovery_indexes',return_value=['https://example.test/index']), \
                patch('modules.goal_executor._ensure'), \
                patch('modules.goal_executor._record',side_effect=lambda _runtime,_job,step: _job['outputs'].update(
                    {step['id']: headlines if step['tool']=='data' else article})), \
                patch('modules.goal_tools.verify'), patch('modules.publisher_news.multiple_publishers',return_value=False):
            news_recovery._chat_deliver(runtime,job,max_new_steps=2)
        research=next(step for step in job['steps'] if step['tool']=='research')
        self.assertEqual(research['depends'],['s1'])

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
        feed='https://www.trthaber.com/sondakika_articles.rss'
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
        receipt={'provider_id':'trt_haber','feed_url':'https://www.trthaber.com/sondakika_articles.rss',
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
