import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

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

    def test_recovery_revalidates_geography_without_fetch_or_model(self):
        article = {
            'url': 'https://example.org/research',
            'published': datetime.now(timezone(timedelta(hours=3))).date().isoformat(),
            'title': 'Yapay zekâ araştırmasında yeni model açıklandı',
            'text': 'Yeni yapay zekâ modeli araştırmacılar tarafından bu hafta yayımlandı. Modelin değerlendirme sonuçları ve araştırma yöntemi kamuoyuyla paylaşıldı.',
        }
        with patch('modules.privacy.blocked', return_value=None), \
             patch('modules.public_sources.fetch', side_effect=AssertionError('receipt fetched again')), \
             patch('modules.model_wait.ask', side_effect=AssertionError('receipt consumed quota')), \
             self.assertRaisesRegex(ValueError, 'Türkiye'):
            model_free_news.receipt(article, 'Türkiye yapay zekâ gelişmeleri')


if __name__ == '__main__':
    unittest.main()
