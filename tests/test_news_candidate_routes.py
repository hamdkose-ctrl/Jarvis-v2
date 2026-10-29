import unittest
from modules import public_sources

class CandidateRoutes(unittest.TestCase):
    def test_padding_preserves_security(self):
        url='https://example.com/story-12345.html'
        self.assertEqual(public_sources.address(url+' '*20),url)
        for c in ('\r','\n','\t'):
            with self.assertRaises(ValueError):public_sources.address(url+c)
        self.assertTrue(public_sources.address(url+'%20').endswith('%20'))

    def test_routes_before_cutoff_and_topic_preserved(self):
        links=['<h2><a href="/video-galeri/item/%s">AI video item</a></h2>'%n for n in range(60)]
        links+=['<h2><a href="/other-story-12345">Unrelated story</a></h2>',
                '<h2><a href="/ai-story-12346">AI research story</a></h2>']
        rows=public_sources.entries({'url':'https://example.com/','body':''.join(links).encode()},query_terms=('research',))
        self.assertEqual(rows[0]['url'],'https://example.com/ai-story-12346')
        self.assertEqual(rows[1]['url'],'https://example.com/other-story-12345')
        self.assertTrue(any('/video-galeri/' in r['url'] for r in rows))
