"""Real discovery ranking and persisted failure diagnostics; no network or model."""
from datetime import date
import unittest
from unittest.mock import patch
from modules import domain_tools, news_pipeline, acceptance_checks


class NewsDiscoveryDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        news_pipeline.cache_clear()
        self.addCleanup(news_pipeline.cache_clear)

    def test_generic_request_does_not_promote_navigation_over_article(self):
        response={'url':'https://example.org/','body':(
            '<div><a href="/son-dakika">Son dakika haberleri</a></div>'
            '<h2><a href="/story">Kentte yeni ulaşım düzenlemesi açıklandı</a></h2>').encode()}
        with patch('modules.service_store.identity'):
            result=domain_tools.headlines('alice',response['url'],query='son dakika haberleri',
                                         fetcher=lambda _:response)
        self.assertEqual(result['items'][0]['url'],'https://example.org/story')
        self.assertIn('https://example.org/son-dakika',[row['url'] for row in result['items']])

    def test_topic_request_still_ranks_related_story(self):
        response={'url':'https://example.org/','body':(
            '<h2><a href="/sports">Futbol maçında sonuçlar açıklandı</a></h2>'
            '<h2><a href="/quake">Deprem sonrası yeni incelemeler tamamlandı</a></h2>').encode()}
        with patch('modules.service_store.identity'):
            result=domain_tools.headlines('alice',response['url'],query='son 7 gün deprem haberleri',
                                         fetcher=lambda _:response)
        self.assertEqual(result['items'][0]['url'],'https://example.org/quake')

    def test_rejection_reason_survives_pipeline_record_and_acceptance(self):
        def fetch(_):
            raise ValueError('Tekil sayfanın yayın tarihi doğrulanamadı.')
        result=news_pipeline.run('son dakika haberleri',
            sources=[{'url':'https://example.org/','name':'Örnek'}],
            reader=lambda _:[{'url':'https://example.org/story','title':'Gerçek haber başlığı'}],
            fetcher=fetch,now=date(2026,10,28))
        job={'state':'paused','goals':[{'state':'pending'}],'steps':[],'outputs':{}}
        news_pipeline._record(job,result)
        saved=job['news_pipeline']
        self.assertEqual(saved['articles_discovered'],1)
        self.assertEqual(saved['articles_read'],1)
        self.assertEqual(saved['articles_rejected'],1)
        self.assertEqual(saved['rejection_reasons'][0]['count'],1)
        self.assertLessEqual(len(saved['rejection_reasons'][0]['reason']),200)
        detail=acceptance_checks._news_failure_detail(job)
        self.assertIn('aday=1; okunan=1',detail)
        self.assertIn('yayın tarihi doğrulanamadı',detail)

    def test_source_failure_reason_is_in_acceptance_detail(self):
        job={'state':'paused','goals':[],'steps':[],'outputs':{},
             'news_pipeline':{'source_health':[{'source':'Örnek','status':'failed',
                                                'reason':'Kaynak HTTP yanıtı başarılı değil: 403'}]}}
        self.assertIn('403',acceptance_checks._news_failure_detail(job))

class TopicBeforeCutoffTests(unittest.TestCase):
    def test_topic_beyond_fifty_story_cards_reaches_headlines(self):
        unrelated=''.join(f'<h2><a href="/sports/{i}">Futbol sonuçları ve maç değerlendirmesi {i}</a></h2>' for i in range(70))
        html=unrelated+'<h2><a href="/ai-story">Türkiye yapay zekâ araştırması duyuruldu</a></h2>'
        response={'url':'https://example.org/','body':html.encode()}
        with patch('modules.service_store.identity'):
            result=domain_tools.headlines('alice',response['url'],query='Türkiye yapay zekâ haberleri',
                                         fetcher=lambda _:response)
        self.assertEqual(result['items'][0]['url'],'https://example.org/ai-story')
        self.assertLessEqual(len(result['items']),20)

    def test_external_discovery_failure_and_rejected_url_are_persisted(self):
        with patch.object(news_pipeline,'catalog',return_value=[]):
            result=news_pipeline.run('AI haberleri',reader=lambda _:[],
                searcher=lambda _:(_ for _ in ()).throw(OSError('search unavailable')))
        job={}
        news_pipeline._record(job,result)
        self.assertEqual(job['news_pipeline']['public_discovery']['state'],'failed')
        self.assertIn('search unavailable',job['news_pipeline']['public_discovery']['reason'])

    def test_rejection_keeps_its_url_without_page_body(self):
        result=news_pipeline.run('son dakika haberleri',sources=[{'url':'https://example.org/'}],
            reader=lambda _:[{'url':'https://example.org/story','title':'Haber başlığı'}],
            fetcher=lambda _:(_ for _ in ()).throw(ValueError('missing article')))
        job={}
        news_pipeline._record(job,result)
        self.assertEqual(job['news_pipeline']['rejected_candidates'][0]['url'],'https://example.org/story')
        self.assertEqual(job['news_pipeline']['rejected_candidates'][0]['reason'],'missing article')
