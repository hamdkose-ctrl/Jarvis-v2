import unittest
from modules import news_pipeline as np
class ExternalCandidates(unittest.TestCase):
    def test_directories_skipped_before_budget(self):
        rows=[{'url':'https://example.com/haberleri/son-haberler'},
              {'url':'https://example.com/kategori/guncel/'},
              {'url':'https://example.com/news/story-12345'}]
        self.assertEqual(np.external_candidates(rows)[0]['url'],rows[2]['url'])
    def test_one_per_publisher_and_bounded(self):
        rows=[{'url':f'https://example{i}.com/story'} for i in range(10)]
        rows.insert(1,{'url':'https://www.example0.com/other'})
        selected=np.external_candidates(rows)
        self.assertEqual(len(selected),8)
        self.assertNotIn(rows[1],selected)
    def test_msn_not_blanket_blocked(self):
        rows=[{'url':'https://www.msn.com/tr-tr/haber/dunya/story/ar-123'}]
        self.assertEqual(np.external_candidates(rows),rows)
