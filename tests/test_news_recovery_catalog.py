"""Recovery must persist pipeline receipts, never restart legacy catalog traversal."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from modules import news_recovery


class NewsRecoveryCatalogTests(unittest.TestCase):
    def test_broad_recovery_scans_registered_catalog_after_two_publishers(self):
        job = {
            'id': 'a' * 16, 'owner': 'alice', 'state': 'running',
            'request': 'Türkiye yapay zekâ gelişmelerini araştır',
            'goals': [{'state': 'pending'}], 'steps': [], 'outputs': {},
        }
        rows = [
            {'news_article': {'url': 'https://aa.com.tr/haber', 'title': 'AI',
                              'published': __import__('datetime').datetime.now(__import__('datetime').timezone(__import__('datetime').timedelta(hours=3))).date().isoformat(), 'text': 'Türkiye yapay zekâ projesinde yeni sonuçlar kamuoyuna ayrıntılarıyla açıklandı. Araştırmacılar çalışmanın teknik bulgularını ve yöntemini yayımladı.'}},
            {'news_article': {'url': 'https://ntv.com.tr/haber', 'title': 'AI',
                              'published': __import__('datetime').datetime.now(__import__('datetime').timezone(__import__('datetime').timedelta(hours=3))).date().isoformat(), 'text': 'Türkiye yapay zekâ projesinde yeni sonuçlar kamuoyuna ayrıntılarıyla açıklandı. Araştırmacılar çalışmanın teknik bulgularını ve yöntemini yayımladı.'}},
        ]
        runtime = SimpleNamespace(profile=SimpleNamespace(slug='alice'))

        def record(_runtime, current, step):
            step['state'] = 'done'
            article = next(row['news_article'] for row in rows if row['news_article']['url'] == step['input']['url'])
            current['outputs'][step['id']] = {
                'state': 'done', 'news_article': article,
                'source_quotes': ['Yapay zekâ kanıtı'], 'source': article['url'],
            }

        with patch('modules.news_pipeline.deliver_job', return_value={'verified': rows}) as pipeline, \
             patch('modules.goal_executor._record', side_effect=record), \
             patch('modules.goal_executor._ensure'), patch('modules.goal_executor._save'), \
             patch('modules.goal_tools.verify'):
            news_recovery._chat_deliver(runtime, job, max_new_steps=4)

        pipeline.assert_called_once()
        self.assertEqual([step['tool'] for step in job['steps']], ['research', 'research'])
        self.assertEqual(job['goals'][0]['state'], 'done')
        self.assertEqual(len(job['goals'][0]['evidence']), 2)



class PublisherDiscoveryTests(unittest.TestCase):
    """Navigation-first HTML must not starve real advertised news discoveries."""
    index='https://example.org/news'
    feed='https://example.org/feed'
    html=b'<link type="application/rss+xml" href="/feed"><a href="/politika">Politika haberleri</a><h2><a href="/news/story">Gercek haber basligi</a></h2>'
    rss=b'<rss><channel><item><title>Gercek haber basligi</title><link>https://example.org/news/story</link><pubDate>Wed, 28 Oct 2026 09:00:00 GMT</pubDate></item></channel></rss>'

    def read(self, html=None, failure=None):
        from modules import domain_tools
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==self.index:
                return {'url':url,'body':self.html if html is None else html}
            if failure is not None:
                raise failure
            self.assertEqual(url,self.feed)
            return {'url':url,'body':self.rss}
        with patch('modules.service_store.identity'):
            result=domain_tools.headlines('alice',self.index,fetcher=fetch)
        return result,calls

    def test_advertised_feed_wins_even_when_html_contains_navigation(self):
        result,calls=self.read()
        self.assertEqual(calls,[self.index,self.feed])
        self.assertEqual(result['source'],self.feed)
        self.assertEqual(result['discovered_from'],self.index)
        self.assertEqual([row['url'] for row in result['items']],['https://example.org/news/story'])
        self.assertTrue(result['items'][0]['published'])

    def test_failed_feed_keeps_html_and_prioritizes_story_card(self):
        result,calls=self.read(failure=OSError('offline'))
        self.assertEqual(calls,[self.index,self.feed])
        self.assertEqual(result['source'],self.index)
        self.assertEqual(result['items'][0]['url'],'https://example.org/news/story')
        self.assertIn('https://example.org/politika',[row['url'] for row in result['items']])

    def test_feed_permission_denial_propagates(self):
        with self.assertRaises(PermissionError):
            self.read(failure=PermissionError('privacy'))

    def test_foreign_feed_is_not_fetched(self):
        html=b'<link type="application/rss+xml" href="https://foreign.example/feed"><h2><a href="/news/story">Gercek haber basligi</a></h2>'
        result,calls=self.read(html=html)
        self.assertEqual(calls,[self.index])
        self.assertEqual(result['source'],self.index)


if __name__ == '__main__':
    unittest.main()

