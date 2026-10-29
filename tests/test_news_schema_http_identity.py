import json
import unittest
from modules import research_evidence

class HttpSchemaIdentity(unittest.TestCase):
    def page(self, ref, canonical='file:///story-12345'):
        schema={'@type':'NewsArticle','headline':'Example news headline',
                'mainEntityOfPage':{'@id':ref},'datePublished':'2026-10-28'}
        body=('<html><head><link rel="canonical" href="'+canonical+'">'
              '<script type="application/ld+json">'+json.dumps(schema)+'</script></head>'
              '<body><article><h1>Example news headline</h1><p>'+('Real source text. '*20)+
              '</p></article></body></html>')
        return {'url':'https://example.com/story-12345?id=1','body':body.encode()}

    def test_http_metadata_with_exact_final_identity(self):
        result=research_evidence.article(self.page('http://example.com/story-12345?id=1'))
        self.assertEqual(result['published'],'2026-10-28')
        self.assertEqual(result['url'],'https://example.com/story-12345?id=1')

    def test_foreign_or_conflicting_identity_rejected(self):
        for ref in ('http://other.com/story-12345?id=1',
                    'http://example.com/other?id=1',
                    'http://example.com/story-12345?id=2',
                    'http://example.com:80/story-12345?id=1',
                    'file:///story-12345?id=1'):
            with self.subTest(ref=ref),self.assertRaises(ValueError):
                research_evidence.article(self.page(ref))

    def test_redirect_to_index_does_not_use_original_identity(self):
        page=self.page('http://example.com/story-12345?id=1')
        page['url']='https://example.com/'
        with self.assertRaises(ValueError):research_evidence.article(page)

    def test_conflicting_valid_canonical_rejected(self):
        with self.assertRaises(ValueError):
            research_evidence.article(self.page('http://example.com/story-12345?id=1',
                                                'https://other.com/story-12345?id=1'))
