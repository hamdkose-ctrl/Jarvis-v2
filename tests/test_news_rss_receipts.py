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

    def test_page_without_date_uses_only_its_bound_rss_receipt(self):
        from modules import research_evidence
        response={'url':'https://www.trthaber.com/haber/gundem/ornek-1.html',
                  'body':b'<article><h1>Ornek haber</h1><p>Bu tekil haber govdesi dogrulanabilir uzunlukta metin icerir ve kaynak metni aynen korunur.</p></article>'}
        bound={'article_url':response['url'],'published':'2026-10-21','title':'Ornek haber'}
        result=research_evidence.article(response,rss_receipt=bound)
        self.assertEqual(result['published'],'2026-10-21')
        with self.assertRaises(ValueError):
            research_evidence.article(response,rss_receipt={**bound,'article_url':'https://www.trthaber.com/haber/gundem/diger.html'})


if __name__ == '__main__':
    unittest.main()
