"""Imperative spelling must not become an article topic requirement."""
import unittest
from unittest.mock import patch

from modules import acceptance_checks, llm, model_free_news, news_pipeline
from test_model_independent_news import article, istanbul_today


class GenericNewsRelevanceTests(unittest.TestCase):
    def test_turkish_research_imperative_has_no_topic(self):
        self.assertEqual(model_free_news.terms('Son 7 gün güncel haberleri araştır'), [])
        self.assertEqual(model_free_news.terms('Son 7 gün güncel haberleri arastir'), [])
        self.assertEqual(model_free_news.terms('son dakika haber lerini araştır'), [])
        self.assertEqual(model_free_news.terms('Deprem haber lerini araştır'), ['deprem'])

    def test_generic_news_accepts_real_sentence_without_research_word(self):
        article = {
            'title': 'Şehirde yeni ulaşım hattı hizmete açıldı',
            'text': 'Şehirde yeni ulaşım hattı hizmete açıldı. '
                    'Belediye yeni ulaşım hattının güzergahını ve sefer saatlerini kamuoyuna duyurdu.',
        }
        result = model_free_news.quotes(article, 'Son 7 gün güncel haberleri araştır')
        self.assertTrue(result)
        self.assertIn(result[0], article['text'])

    def test_research_as_subject_and_explicit_topic_are_preserved(self):
        self.assertIn('araştirma', model_free_news.terms('Araştırma laboratuvarı haberleri'))
        article = {'title': 'Yeni ulaşım hattı',
                   'text': 'Belediye yeni ulaşım hattının güzergahını ve sefer saatlerini kamuoyuna duyurdu.'}
        with self.assertRaisesRegex(ValueError, 'konu'):
            model_free_news.quotes(article, 'Deprem haberlerini araştır')

    def test_external_discovery_reads_and_verifies_generic_article_without_research_word(self):
        url = 'https://outside-catalog.example.org/news/transit-opening'
        body = ('Belediye yeni ulaşım hattının güzergahını ve sefer saatlerini kamuoyuna duyurdu. '
                'İlk sefer sabah saatlerinde başladı ve yolcular yeni hat üzerinden seyahat etti. '
                'Hat üzerindeki duraklar erişilebilir olarak düzenlendi ve yolcu kapasitesi artırıldı.')
        page = article(url, 'Şehirde yeni ulaşım hattı hizmete açıldı', istanbul_today().isoformat(), body)
        news_pipeline.cache_clear()
        self.addCleanup(news_pipeline.cache_clear)
        with llm.owner_context('alice'), patch('modules.privacy.blocked', return_value=None), \
                patch('modules.research_providers.search_news_public', return_value=[{'url': url}]), \
                patch('modules.public_sources.fetch', return_value=page) as fetch, \
                patch('modules.llm.ask', side_effect=AssertionError('No generation in discovery')):
            state, detail = acceptance_checks._news_external_discovery('alice')
        self.assertEqual(state, 'passed', detail)
        self.assertIn('katalog_dışı_doğrulanan=1', detail)
        fetch.assert_called_once_with(url)


if __name__ == '__main__':
    unittest.main()
