import unittest

from modules import model_free_news


class NewsGeographyScopeContractTests(unittest.TestCase):
    def test_turkiye_ai_request_rejects_foreign_ai_story_without_turkiye_evidence(self):
        article = {
            'title': 'US company announces new artificial intelligence model',
            'text': (
                'The artificial intelligence company announced a new model in California. '
                'The system will be released to customers in the United States next month.'
            ),
        }
        with self.assertRaisesRegex(ValueError, 'Türkiye'):
            model_free_news.quotes(article, 'Son 7 gündeki Türkiye yapay zekâ gelişmelerini araştır')

    def test_turkiye_ai_request_accepts_article_with_turkiye_evidence(self):
        article = {
            'title': 'Türkiye yapay zekâ merkezi yeni programını açıkladı',
            'text': (
                'Türkiye yapay zekâ ekosistemi için yeni araştırma programı Ankara’da açıklandı. '
                'Program üniversiteler ve teknoloji şirketleriyle ortak projeler yürütecek.'
            ),
        }
        quotes = model_free_news.quotes(
            article,
            'Son 7 gündeki Türkiye yapay zekâ gelişmelerini araştır',
        )
        self.assertTrue(quotes)


if __name__ == '__main__':
    unittest.main()
