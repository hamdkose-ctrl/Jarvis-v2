import unittest
from unittest.mock import patch
from modules import research_providers,public_sources

class SearchResponseStates(unittest.TestCase):
    def search(self,html):
        with patch.object(public_sources,'fetch',return_value={'body':html.encode()}):
            return research_providers.search_public('test query')
    def test_challenge_is_not_empty(self):
        with self.assertRaisesRegex(ValueError,'public_search_blocked'):
            self.search('<form id="challenge-form" action="/anomaly.js"></form>')
    def test_unknown_document_is_not_empty(self):
        with self.assertRaisesRegex(ValueError,'public_search_unrecognized'):
            self.search('<html>Service temporarily unavailable</html>')
    def test_explicit_empty_remains_empty(self):
        self.assertEqual(self.search('<div class="no-results">No results found</div>'),[])
    def test_normal_result_uses_existing_reader(self):
        rows=self.search('<a class="result__a" href="https://example.com/article">Example story</a>')
        self.assertEqual(rows[0]['url'],'https://example.com/article')
        self.assertFalse(rows[0]['verified'])
