"""RSS makbuzu yalnız aynı tekil haber bağlantısına tarih sağlayabilir."""
import unittest


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


if __name__ == '__main__':
    unittest.main()
