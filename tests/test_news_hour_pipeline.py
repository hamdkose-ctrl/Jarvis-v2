import unittest
from datetime import datetime,timedelta,timezone
from modules import news_pipeline

class HourPipeline(unittest.TestCase):
    def setUp(self):
        news_pipeline.cache_clear();self.addCleanup(news_pipeline.cache_clear)
    def run_age(self,minutes):
        clock=datetime.now(timezone(timedelta(hours=3)))-timedelta(minutes=minutes)
        sources=[{'url':'https://one.example/','name':'One'},{'url':'https://two.example/','name':'Two'}]
        def reader(url):return [{'url':url+'story','title':'Actual news headline '+url}]
        def fetcher(url):
            html='<article><h1>Actual news headline</h1><time itemprop="datePublished" datetime="'+clock.isoformat()+'"></time><p>'+('Deprem sonrası ekipler çalışmaların sonuçlarını kamuoyuna açıkladı. '*5)+'</p></article>'
            return {'url':url,'body':html.encode()}
        return news_pipeline.run('son dakika haberleri',sources=sources,reader=reader,fetcher=fetcher)
    def test_real_reader_and_pipeline_accept_recent_hour(self):
        result=self.run_age(30)
        self.assertEqual(result['articles_verified'],2,result)
        self.assertIn('Son 1 saat',news_pipeline.report(result))
        self.assertTrue(all('published_at' in row['news_article'] for row in result['verified']))
    def test_real_reader_and_pipeline_reject_older_hour(self):
        result=self.run_age(90)
        self.assertEqual(result['articles_verified'],0)
        self.assertTrue(all(row.get('reason') for row in result['candidates']))
