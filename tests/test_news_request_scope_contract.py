from datetime import date
from unittest.mock import patch
import unittest

from modules import news_pipeline


class NewsRequestScopeContractTests(unittest.TestCase):
    def setUp(self):
        news_pipeline.cache_clear()
        self.addCleanup(news_pipeline.cache_clear)

    def test_headline_reader_forwards_user_query(self):
        seen = []

        def fake_headlines(owner, url, **kwargs):
            seen.append((owner, url, kwargs))
            return {'items': []}

        with patch('modules.domain_tools.headlines', side_effect=fake_headlines):
            reader = news_pipeline.headline_reader('alice', 'Türkiye yapay zekâ gelişmeleri')
            self.assertEqual(reader('https://example.org/news'), [])

        self.assertEqual(seen, [
            ('alice', 'https://example.org/news', {'query': 'Türkiye yapay zekâ gelişmeleri'})
        ])

    def test_run_uses_requested_news_window_when_days_is_omitted(self):
        result = news_pipeline.run(
            'son 30 gündeki yapay zekâ haberleri',
            sources=[],
            reader=lambda _url: [],
            now=date(2026, 10, 28),
        )
        self.assertEqual(result['window_days'], 30)

    def test_future_dated_evidence_is_not_in_window(self):
        row = {'published_at': '2099-01-01'}
        self.assertFalse(news_pipeline.in_window(row, 7, date(2026, 10, 28)))


if __name__ == '__main__':
    unittest.main()
