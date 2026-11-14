"""News workflow acceptance uses canonical ingress; sources are fake only here.

This suite measures no live Brain semantics or provider eligibility.
"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modules import acceptance_checks, engine_runtime, history, llm, news_pipeline
from modules import personalization, requests_state
from test_model_independent_news import istanbul_today, two_source_feeds


class NewsAcceptanceEntryTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        users = root / 'users'
        users.mkdir()
        for module, attr, value in (
            (personalization, 'USERS_DIR', users),
            (personalization, 'ACTIVE_FILE', root / 'active'),
            (engine_runtime, 'DATA_DIR', root),
            (history, 'DIR', root / 'history'),
            (requests_state, '_journal', root / 'requests.json'),
            (requests_state, '_records', {}),
        ):
            self.enterContext(patch.object(module, attr, value))
        personalization.set_active('alice')
        self.enterContext(llm.owner_context('alice'))
        news_pipeline.cache_clear()
        self.addCleanup(news_pipeline.cache_clear)
        _reader, fetcher = two_source_feeds(day=istanbul_today(), article_body=(
            'Türkiye yapay zekâ araştırmaları için yeni bilimsel çalışmalarını duyurdu. '
            'Türkiye içindeki yapay zekâ ekipleri sonuçları ve araştırma ayrıntılarını paylaştı. '
            'Kurumlar Türkiye yapay zekâ projelerinin eğitim ve teknoloji alanındaki '
            'bulgularını kamuoyuna açık ve doğrulanabilir belgelerle açıkladı.'))

        def fetch(url):
            response = fetcher(url)
            return {**response, 'body': response['body'].replace(
                b'deprem haberi', 'Türkiye yapay zekâ haberi'.encode())}

        self.fetch = fetch
        self.enterContext(patch('modules.public_sources.fetch', side_effect=fetch))
        self.enterContext(patch('modules.research_providers.search_news_public', return_value=[]))
        self.enterContext(patch('modules.privacy.blocked', return_value=None))
        logger = engine_runtime.logging.getLogger()
        previous_handlers = set(logger.handlers)

        def close_new_handlers():
            for handler in list(logger.handlers):
                if handler not in previous_handlers:
                    logger.removeHandler(handler)
                    handler.close()

        self.addCleanup(close_new_handlers)

    def test_three_scenarios_reach_real_core_and_verify_news_and_file(self):
        for request, file_report in (
            ('Son 7 gün güncel haberleri araştır', False),
            ('Son 7 gündeki Türkiye yapay zekâ gelişmelerini araştır', False),
            ('Son 7 gündeki Türkiye yapay zekâ gelişmelerini araştır ve raporu dosyaya kaydet', True),
        ):
            with self.subTest(file_report=file_report, request=request):
                state, detail = acceptance_checks._news_scenario(
                    'alice', request, file_report=file_report)
                self.assertEqual(state, 'passed', detail)
                self.assertIn('canlı Brain/Scheduler kabulü değildir', detail)

    def test_missing_second_publisher_still_fails_real_completion_gate(self):
        def one_publisher(url):
            if 'bbc.com' in url:
                raise OSError('Second publisher unavailable in this fixture')
            return self.fetch(url)

        with patch('modules.public_sources.fetch', side_effect=one_publisher):
            state, detail = acceptance_checks._news_scenario(
                'alice', 'Son 7 gün güncel haberleri araştır')
        self.assertEqual(state, 'failed')
        self.assertIn('makale=1; yayıncı=1', detail)
        self.assertNotIn('Haber hedefi oluşturulmadı', detail)


if __name__ == '__main__':
    unittest.main()
