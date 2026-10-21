import unittest

from modules import news_receipts


class NewsReceiptTests(unittest.TestCase):
    def trt(self, **overrides):
        data = dict(
            provider_id='trt_haber',
            url='https://www.trthaber.com/haber/gundem/ornek-haber-123.html',
            title='Örnek TRT Haber',
            published='2026-10-21',
            summary='Makbuzun kısa içerik özeti.',
            source_summary='TRT Haber RSS girdisinden alındı.',
        )
        data.update(overrides)
        return news_receipts.seal(**data)

    def aa(self, **overrides):
        data = dict(
            provider_id='aa_teyit',
            url='https://www.aa.com.tr/tr/gundem/ornek-haber/1234567',
            title='Örnek AA Haber',
            published='2026-10-21',
            summary='Makbuzun kısa içerik özeti.',
            source_summary='AA RSS girdisinden alındı.',
        )
        data.update(overrides)
        return news_receipts.seal(**data)

    def test_seal_is_stable_and_tampering_is_rejected(self):
        receipt = self.trt()
        self.assertEqual(news_receipts.validate(receipt), receipt)
        receipt['title'] = 'Değiştirilmiş başlık'
        with self.assertRaises(ValueError):
            news_receipts.validate(receipt)

    def test_feed_date_falls_back_only_for_same_url(self):
        receipt = self.trt()
        self.assertEqual(news_receipts.article_date({'url': receipt['url']}, receipt), '2026-10-21')
        with self.assertRaises(ValueError):
            news_receipts.article_date({'url': 'https://www.trthaber.com/baska'}, receipt)

    def test_page_and_feed_date_conflict_is_rejected(self):
        receipt = self.trt()
        with self.assertRaises(ValueError):
            news_receipts.article_date({'url': receipt['url'], 'published': '2026-10-20'}, receipt)

    def test_two_distinct_publishers_are_required(self):
        one = self.trt()
        two_same = self.trt(url='https://www.trthaber.com/haber/gundem/ikinci-haber-456.html', title='İkinci TRT Haber')
        with self.assertRaises(ValueError):
            news_receipts.require_two_publishers([one, two_same])
        result = news_receipts.require_two_publishers([one, self.aa()])
        self.assertEqual(len(result), 2)

    def test_model_payload_contains_only_verified_receipt_fields(self):
        payload = news_receipts.model_payload([self.trt(), self.aa()])
        self.assertEqual(set(payload[0]), {'url','title','published','summary','source_summary','publisher'})
        self.assertNotIn('provider_id', payload[0])
        self.assertNotIn('seal', payload[0])


if __name__ == '__main__':
    unittest.main()
