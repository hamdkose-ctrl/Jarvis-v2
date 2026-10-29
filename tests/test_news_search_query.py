import unittest
from modules import research_providers as rp
class NewsSearchQuery(unittest.TestCase):
    def test_generic_task_becomes_search_terms(self):
        self.assertEqual(rp.news_search_query('Son 7 gün güncel haberleri araştır'),'güncel haberler')
    def test_topic_geography_and_historical_year_retained(self):
        result=rp.news_search_query('Türkiye 2025 yapay zekâ haberlerini araştır ve raporu dosyaya kaydet')
        self.assertEqual(result,'Türkiye 2025 yapay zekâ')
    def test_delivery_does_not_replace_topic(self):
        self.assertEqual(rp.news_search_query('Almanya son 7 gün enerji haberlerini araştır ve Türkçe rapor dosyası oluştur'),'Almanya enerji')
    def test_topic_without_commands_unchanged(self):
        self.assertEqual(rp.news_search_query('Türkiye yapay zeka'),'Türkiye yapay zeka')
