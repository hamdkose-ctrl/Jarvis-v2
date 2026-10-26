import unittest
from unittest.mock import patch

from modules import task_workers


class Phase4ResearchWiringTests(unittest.TestCase):
    def test_research_worker_reads_general_page_through_readonly_provider(self):
        source = {
            'url': 'https://example.test/article',
            'text': 'Araştırma bulgusu enerji tüketimini anlamlı ölçüde azalttığını gösteriyor.',
            'content_type': 'text/html',
        }
        task = {
            'id': 'research-1',
            'agent': 'research',
            'input': {'url': source['url'], 'question': 'Ne bulundu?'},
            'execution': {'request': 'Enerji araştırması'},
        }
        answer = '{"supported": true, "answer": "Enerji tüketimi azaldı.", "quotes": ["Araştırma bulgusu enerji tüketimini anlamlı ölçüde azalttığını gösteriyor."]}'
        with patch('modules.privacy.blocked', return_value=None), \
             patch('modules.research_providers.extract_source', return_value=source) as extract, \
             patch('modules.model_wait.ask', return_value=answer):
            output = task_workers.run('alice', task, {})

        extract.assert_called_once_with(source['url'])
        self.assertEqual(output['source'], source['url'])
        self.assertIn('Enerji tüketimi azaldı.', output['text'])


if __name__ == '__main__':
    unittest.main()
