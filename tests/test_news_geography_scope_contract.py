import unittest

from modules import model_free_news


class NewsGeographyScopeContractTests(unittest.TestCase):
    def test_turkiye_ai_request_rejects_foreign_topical_story_without_turkiye_evidence(self):
        article = {
            'title': 'ABD şirketi yeni yapay zekâ modelini açıkladı',
            'text': (
                'ABD merkezli şirket yeni yapay zekâ modelini California’da tanıttı. '
                'Sistem gelecek ay Amerika Birleşik Devletleri müşterilerine açılacak.'
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

    def test_same_contract_applies_to_non_ai_subject_and_other_country(self):
        article = {
            'title': 'ABD otomotiv üreticisi yeni elektrikli araç hattını açıkladı',
            'text': (
                'ABD otomotiv sektörü için yeni elektrikli araç üretim hattı Detroit’te açıklandı. '
                'Şirket üretimi gelecek yıl artırmayı planlıyor.'
            ),
        }
        with self.assertRaisesRegex(ValueError, 'Almanya'):
            model_free_news.quotes(article, 'Almanya otomotiv sektöründeki son gelişmeleri araştır')

    def test_recovery_can_preserve_selected_evidence_without_geography_recheck(self):
        article = {
            'title': 'Yapay zekâ araştırmasında yeni model açıklandı',
            'text': 'Yeni yapay zekâ modeli araştırmacılar tarafından bu hafta yayımlandı.',
        }
        quotes = model_free_news.quotes(
            article,
            'Türkiye yapay zekâ gelişmeleri',
            enforce_geography=False,
        )
        self.assertTrue(quotes)


if __name__ == '__main__':
    unittest.main()
