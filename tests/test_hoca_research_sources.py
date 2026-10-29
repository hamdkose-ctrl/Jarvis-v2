"""Use the shared bounded research reader; do not stop at one bad candidate."""
import unittest
from unittest.mock import patch
from modules import hoca, requests_state

class HocaResearchSources(unittest.TestCase):
    def setUp(self):
        self.candidates=[{'url':'https://one.example/a','title':'One'}, {'url':'https://two.example/b','title':'Two'}]
        self.good={'url':self.candidates[1]['url'],'text':'Kaynakta bulunan gerçek eğitim içeriği. '*5}
    def test_inaccessible_first_source_is_skipped(self):
        with patch('modules.research_providers.search_public',return_value=self.candidates) as search, \
             patch('modules.research_providers.extract_source',side_effect=[OSError('offline'),self.good]) as extract:
            result=hoca._research_source('hücre')
        self.assertEqual(result['url'],self.good['url']);self.assertEqual(result['label'],'Two')
        search.assert_called_once_with('hücre');self.assertEqual(extract.call_count,2)
    def test_short_first_source_is_skipped(self):
        with patch('modules.research_providers.search_public',return_value=self.candidates), \
             patch('modules.research_providers.extract_source',side_effect=[{'text':'short'},self.good]):
            self.assertEqual(hoca._research_source('hücre')['text'],self.good['text'].strip())
    def test_permission_and_cancel_stop_without_second_read(self):
        for error in (PermissionError('denied'),requests_state.Cancelled('stop')):
            with self.subTest(error=type(error).__name__), \
                 patch('modules.research_providers.search_public',return_value=self.candidates), \
                 patch('modules.research_providers.extract_source',side_effect=error) as extract:
                with self.assertRaises(type(error)):hoca._research_source('hücre')
                self.assertEqual(extract.call_count,1)
    def test_candidate_reads_are_bounded_and_no_model_called(self):
        candidates=[{'url':f'https://one.example/{i}'} for i in range(20)]
        with patch('modules.research_providers.search_public',return_value=candidates) as search, \
             patch('modules.research_providers.extract_source',side_effect=OSError('offline')) as extract, \
             patch.object(hoca.llm,'ask') as model:
            with self.assertRaises(hoca.HocaError):hoca._research_source('hücre')
        self.assertEqual(extract.call_count,10);self.assertEqual(search.call_count,1);model.assert_not_called()
