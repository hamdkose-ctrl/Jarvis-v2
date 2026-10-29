"""Regression tests for the shared news/research evidence contract; no live network."""
from datetime import date
import json
import unittest
from unittest.mock import patch

from modules import news_pipeline,model_free_news,research_evidence,research_providers,publisher_news


class NewsContractClosureTests(unittest.TestCase):
    def setUp(self):
        news_pipeline.cache_clear()
        self.addCleanup(news_pipeline.cache_clear)

    def article(self,url='https://a.example/story',published='2026-10-28'):
        return {'url':url,'title':'Yeni araştırma duyuruldu','published':published,
                'text':('Araştırmacılar yeni çalışmanın bulgularını kamuoyuna açıkladı. '
                        'Çalışmanın yöntemi ve sonuçları ayrıntılarıyla yayımlandı.')}

    def test_foreign_ai_does_not_satisfy_turkey_scope(self):
        source=self.article()
        source.update(title='ABD yapay zekâ programı',text='ABD yapay zekâ programını yalnız Amerikan şirketlerine yönelik yeni fonlarla duyurdu.')
        with self.assertRaisesRegex(ValueError,'Türkiye'):
            model_free_news.quotes(source,'Türkiye yapay zekâ gelişmeleri')

    def test_value_must_match_the_real_quote(self):
        quote='Enerji tüketimi yapılan ölçümlerde yüzde 40 oranında azalmıştır.'
        self.assertIsNone(research_evidence.parse_value_quote(json.dumps({'value':'99','quote':quote}),quote))
        self.assertEqual(research_evidence.parse_value_quote(json.dumps({'value':'40','quote':quote}),quote)['value'],'40')

    def test_single_publisher_cannot_report_complete_for_plural_news(self):
        rows=[{'news_article':self.article()}]
        self.assertEqual(news_pipeline.status([{'status':'ok'}],verified=rows,
                         request='son dakika haberleri')['news_status'],'partial')

    def test_explicit_single_source_can_complete(self):
        rows=[{'news_article':self.article()}]
        self.assertTrue(news_pipeline.enough_evidence(rows,'Sadece https://a.example/story haberini araştır'))
        self.assertFalse(news_pipeline.enough_evidence(rows,'İki farklı yayıncıdan haberleri araştır'))

    def test_same_url_is_not_two_articles(self):
        row={'news_article':self.article()}
        self.assertFalse(news_pipeline.enough_evidence([row,row]))

    def test_two_explicit_sources_cannot_complete_with_one(self):
        request='https://a.example/story ve https://b.example/story haberlerini araştır'
        first={'news_article':self.article()}
        second={'news_article':self.article(url='https://b.example/story')}
        self.assertFalse(news_pipeline.enough_evidence([first],request))
        self.assertTrue(news_pipeline.enough_evidence([first,second],request))

    def test_future_reuse_is_not_fresh(self):
        self.assertFalse(news_pipeline.in_window({'published_at':'2099-01-01'},7,date(2026,10,28)))

    def test_user_window_is_used_by_the_real_run(self):
        for days in (3,7,30):
            result=news_pipeline.run(f'Son {days} gün haberleri',sources=[],reader=lambda _:[],
                                     now=date(2026,10,28))
            self.assertEqual(result['window_days'],days)

    def test_request_reaches_the_headline_reader(self):
        with patch('modules.domain_tools.headlines',return_value={'items':[]}) as headlines:
            news_pipeline.headline_reader('alice','Türkiye yapay zekâ')('https://a.example/')
        headlines.assert_called_once_with('alice','https://a.example/',query='Türkiye yapay zekâ')

    def test_same_publisher_cannot_resolve_its_own_conflict(self):
        comparison={'status':'conflict','comparisons':[{'conflict':True,'values':['40','45']}],
                    'sources':[{'url':'https://a.example/first'},{'url':'https://b.example/first'}]}
        verdict=research_providers.verify_conflict('energy',comparison,
                    search=lambda _:[{'url':'https://a.example/second'}],
                    extract=lambda _:self.fail('same publisher must not be fetched'),read_value=lambda _:['40'])
        self.assertEqual(verdict['status'],'unresolved_conflict')

    def test_extraction_uses_the_guarded_https_reader(self):
        response={'url':'https://a.example/story','body':b'<main><p>Readable public article body.</p></main>'}
        with patch('modules.public_sources.fetch',return_value=response) as fetch:
            result=research_providers.extract_source(response['url'])
        fetch.assert_called_once_with(response['url'])
        self.assertIn('Readable',result['text'])

    def test_news_pipeline_never_calls_a_model(self):
        source=self.article()
        def reader(url):
            return [{'url':url+'story','title':source['title'],'published':source['published']}]
        def fetch(url):
            return dict(source,url=url)
        with patch('modules.llm.ask',side_effect=AssertionError('quota spent')), \
             patch('modules.model_wait.ask',side_effect=AssertionError('quota spent')), \
             patch.object(news_pipeline,'article_reader',side_effect=lambda page:page):
            result=news_pipeline.run('son dakika haberleri',sources=[
                {'url':'https://a.example/','name':'A'},{'url':'https://b.example/','name':'B'}],
                reader=reader,fetcher=fetch,now=date(2026,10,28))
        self.assertEqual(result['articles_verified'],2)
        self.assertEqual(result['news_status'],'complete')

    def test_story_below_fifty_navigation_links_survives_discovery(self):
        from modules import public_sources
        menus=''.join(f'<a href="/menu/{i}">Navigation category {i}</a>' for i in range(70))
        html=menus+'<h2><a href="/story">Actual article headline</a></h2>'
        rows=public_sources.entries({'url':'https://a.example/','body':html.encode()})
        self.assertEqual(rows[0]['url'],'https://a.example/story')

    def test_iha_uses_news_endpoint(self):
        self.assertIn('https://www.iha.com.tr/', [row['url'] for row in publisher_news.sources_for('son dakika haberleri')])

    def test_cache_is_scoped_to_owner_and_query(self):
        from unittest.mock import Mock
        source=[{'url':'https://a.example/','name':'A'}]
        reader=Mock(return_value=[{'url':'https://a.example/story','title':'Actual article headline'}])
        for owner,query in [('alice','AI'),('alice','AI'),('alice','finance'),('bob','AI')]:
            news_pipeline.discover(source,reader=reader,owner=owner,query=query)
        self.assertEqual(reader.call_count,3)

    def test_authorization_and_cancellation_are_not_source_failures(self):
        from modules import requests_state
        for exc in [PermissionError('denied'), requests_state.Cancelled('cancelled')]:
            with self.subTest(exc=exc), self.assertRaises(type(exc)):
                news_pipeline.discover([{'url':'https://a.example/'}],reader=lambda _: (_ for _ in ()).throw(exc))

    def test_public_discovery_is_bounded_and_not_a_whitelist(self):
        source=self.article()
        with patch.object(news_pipeline,'catalog',return_value=[]), \
             patch.object(news_pipeline,'article_reader',side_effect=lambda page: page):
            search=__import__('unittest.mock',fromlist=['Mock']).Mock(return_value=[{'url':'https://new.example/story','title':source['title']}])
            result=news_pipeline.run('son dakika haberleri', reader=lambda _:[],fetcher=lambda url:dict(source,url=url),
                                     searcher=search,now=date(2026,10,28))
        search.assert_called_once()
        self.assertEqual(result['articles_verified'],1)
        self.assertLessEqual(result['articles_read'],news_pipeline.MAX_ARTICLE_READS)

    def test_single_sealed_receipt_does_not_fetch_or_call_a_model(self):
        source=self.article(published=news_pipeline._today().isoformat())
        with patch('modules.public_sources.fetch',side_effect=AssertionError('duplicate fetch')), \
             patch('modules.model_wait.ask',side_effect=AssertionError('quota')), \
             patch('modules.task_results.seal',side_effect=lambda agent,result:result):
            result=model_free_news.receipt(source,'son dakika haberleri')
        self.assertEqual(result['news_article'],source)

    def test_changed_topic_does_not_reuse_old_news(self):
        source=self.article()
        rows=[{'news_article':source,'verification':'verified','published_at':source['published'],'date_status':'present'}]
        result=news_pipeline.run('deprem haberleri',reuse=rows,now=date(2026,10,28))
        self.assertEqual(result['articles_verified'],0)

