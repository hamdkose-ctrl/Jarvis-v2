import json
import unittest
from modules import research_evidence

class DuplicateHeadlines(unittest.TestCase):
    def page(self, second='Story headline', ref='https://example.com/story-12345'):
        schema={'@type':'NewsArticle','headline':'Story headline','mainEntityOfPage':ref,'datePublished':'2026-10-28'}
        return {'url':'https://example.com/story-12345','body':('<html><head><script type="application/ld+json">'+json.dumps(schema)+'</script></head><body><h1>Story headline</h1><h1>'+second+'</h1><article><p>'+('Real article sentence. '*20)+'</p></article></body></html>').encode()}
    def test_identical_schema_bound_copies(self):
        self.assertEqual(research_evidence.article(self.page())['published'],'2026-10-28')
    def test_different_headlines_rejected(self):
        with self.assertRaises(ValueError):research_evidence.article(self.page(second='Different story'))
    def test_foreign_schema_rejected(self):
        with self.assertRaises(ValueError):research_evidence.article(self.page(ref='https://other.com/story-12345'))
