import unittest
from pathlib import Path
from unittest.mock import patch
from modules import research_providers as rp,public_sources,requests_state
class NewsRssFallback(unittest.TestCase):
    def test_real_feed_extracts_public_addresses_not_evidence(self):
        # Minimal captured-shape fixture; raw live pages are not repository data.
        body=b'<rss><channel><item><title>Story</title><link>http://www.bing.com/news/apiclick.aspx?url=https%3A%2F%2Fexample.com%2Fstory</link></item></channel></rss>'
        with patch.object(rp,'search_public',side_effect=ValueError('blocked')),patch.object(public_sources,'fetch',return_value={'body':body}) as fetch:
            rows=rp.search_news_public('news')
        self.assertEqual(rows[0]['url'],'https://example.com/story');self.assertFalse(rows[0]['verified']);fetch.assert_called_once()
    def test_primary_success_never_calls_fallback(self):
        with patch.object(rp,'search_public',return_value=[{'url':'https://example.com/story'}]),patch.object(public_sources,'fetch') as fetch:
            self.assertEqual(len(rp.search_news_public('news')),1)
        fetch.assert_not_called()
    def test_permissions_and_cancel_propagate(self):
        for error in [PermissionError('blocked'),requests_state.Cancelled('stop')]:
            with patch.object(rp,'search_public',side_effect=error),patch.object(public_sources,'fetch') as fetch:
                with self.assertRaises(type(error)):rp.search_news_public('news')
            fetch.assert_not_called()
    def test_entities_rejected(self):
        with patch.object(rp,'search_public',side_effect=ValueError('blocked')),patch.object(public_sources,'fetch',return_value={'body':b'<!DOCTYPE rss><rss/>'}):
            with self.assertRaises(ValueError):rp.search_news_public('news')

    def test_empty_primary_attempts_bing_once_and_reports_empty(self):
        with patch.object(rp,'search_public',return_value=[]),patch.object(public_sources,'fetch',return_value={'body':b'<rss><channel/></rss>'}) as fetch:
            with self.assertRaisesRegex(ValueError,'public_news_rss_empty.*item=0'):
                rp.search_news_public('news')
        fetch.assert_called_once()
