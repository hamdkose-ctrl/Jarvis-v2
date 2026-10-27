import unittest
from unittest.mock import patch

from modules import task_workers


class Phase4ResearchWiringTests(unittest.TestCase):
    def test_research_worker_reads_general_page_through_readonly_provider(self):
        source = {
            'url': 'https://example.test/article',
            'text': 'Araştırma bulgusu enerji tüketimini anlamlı ölçüde azalttığını gösteriyor. Bu sonuç bağımsız deneylerle tekrar doğrulandı ve ölçüm protokolü yayımlandı.',
            'content_type': 'text/html',
        }
        task = {
            'id': 'research-1',
            'agent': 'research',
            'input': {'url': source['url'], 'question': 'Ne bulundu?'},
            'execution': {'request': 'Enerji araştırması'},
        }
        answer = '{"supported": true, "answer": "Enerji tüketimi azaldı.", "quotes": ["Araştırma bulgusu enerji tüketimini anlamlı ölçüde azalttığını gösteriyor. Bu sonuç bağımsız deneylerle tekrar doğrulandı ve ölçüm protokolü yayımlandı."]}'
        with patch('modules.privacy.blocked', return_value=None), \
             patch('modules.research_providers.extract_source', return_value=source) as extract, \
             patch('modules.model_wait.ask', return_value=answer):
            output = task_workers.run('alice', task, {})

        extract.assert_called_once_with(source['url'])
        self.assertEqual(output['source'], source['url'])
        self.assertIn('Enerji tüketimi azaldı.', output['text'])

    def test_research_worker_searches_query_then_reads_ranked_source(self):
        source = {
            'url': 'https://example.test/verified',
            'text': 'Doğrulanmış araştırma sonucu enerji tüketiminde ölçülebilir düşüş olduğunu ve yöntemin tekrarlandığını anlatıyor.',
            'content_type': 'text/html',
        }
        task = {
            'id': 'research-query-1',
            'agent': 'research',
            'input': {'query': 'enerji verimliliği araştırması', 'question': 'Ne bulundu?'},
            'execution': {'request': 'Enerji araştırması'},
        }
        answer = '{"supported": true, "answer": "Enerji tüketimi düştü.", "quotes": ["Doğrulanmış araştırma sonucu enerji tüketiminde ölçülebilir düşüş olduğunu ve yöntemin tekrarlandığını anlatıyor."]}'
        candidates = [{'provider': 'duckduckgo', 'title': 'Doğrulanmış kaynak', 'url': source['url'],
                       'snippet': '', 'source_kind': 'web', 'verified': False}]
        with patch('modules.privacy.blocked', return_value=None), \
             patch('modules.research_providers.search_public', return_value=candidates) as search, \
             patch('modules.research_providers.extract_source', return_value=source) as extract, \
             patch('modules.model_wait.ask', return_value=answer):
            output = task_workers.run('alice', task, {})

        search.assert_called_once_with(task['input']['query'])
        extract.assert_called_once_with(source['url'])
        self.assertEqual(output['source'], source['url'])
        self.assertIn('Enerji tüketimi düştü.', output['text'])


    def test_research_worker_exposes_unresolved_source_conflict_to_user_output(self):
        source = {'url': 'https://example.test/article', 'text': 'Kaynak metni yeterince uzundur ve doğrulanmış araştırma bulgusunu açıklar. ' * 2, 'content_type': 'text/html'}
        claims = [
            {'source': 'a', 'subject': 'faiz oranı', 'claim_type': 'rate', 'value': 40, 'unit': 'percent', 'scope': 'Türkiye', 'observed_at': '2026-10-27'},
            {'source': 'b', 'subject': 'faiz oranı', 'claim_type': 'rate', 'value': 45, 'unit': 'percent', 'scope': 'Türkiye', 'observed_at': '2026-10-27'},
        ]
        task = {'id': 'research-conflict-1', 'agent': 'research', 'input': {'url': source['url'], 'question': 'Ne bulundu?', 'source_claims': claims, 'verification_claims': []}, 'execution': {'request': 'Araştır'}}
        answer = '{"supported": true, "answer": "Faiz oranı kaynaklarda farklı bildiriliyor.", "quotes": ["Kaynak metni yeterince uzundur ve doğrulanmış araştırma bulgusunu açıklar."]}'
        with patch('modules.privacy.blocked', return_value=None), patch('modules.research_providers.extract_source', return_value=source), patch('modules.model_wait.ask', return_value=answer):
            output = task_workers.run('alice', task, {})

        self.assertEqual(output['source_conflict']['status'], 'unresolved_conflict')
        self.assertIn('Belirsizlik: Kaynaklar çelişiyor', output['text'])

    def test_research_worker_exposes_resolved_conflict_without_selecting_first_source(self):
        source = {'url': 'https://example.test/article', 'text': 'Kaynak metni yeterince uzundur ve doğrulanmış araştırma bulgusunu açıklar. ' * 2, 'content_type': 'text/html'}
        claims = [
            {'source': 'a', 'subject': 'faiz oranı', 'claim_type': 'rate', 'value': 40, 'unit': 'percent', 'scope': 'Türkiye', 'observed_at': '2026-10-27'},
            {'source': 'b', 'subject': 'faiz oranı', 'claim_type': 'rate', 'value': 45, 'unit': 'percent', 'scope': 'Türkiye', 'observed_at': '2026-10-27'},
        ]
        official = {'source': 'resmî', 'source_kind': 'official', 'subject': 'faiz oranı', 'claim_type': 'rate', 'value': 45, 'unit': 'percent', 'scope': 'Türkiye', 'observed_at': '2026-10-27'}
        task = {'id': 'research-resolved-1', 'agent': 'research', 'input': {'url': source['url'], 'question': 'Ne bulundu?', 'source_claims': claims, 'verification_claims': [official]}, 'execution': {'request': 'Araştır'}}
        answer = '{"supported": true, "answer": "Faiz oranı doğrulandı.", "quotes": ["Kaynak metni yeterince uzundur ve doğrulanmış araştırma bulgusunu açıklar."]}'
        with patch('modules.privacy.blocked', return_value=None), patch('modules.research_providers.extract_source', return_value=source), patch('modules.model_wait.ask', return_value=answer):
            output = task_workers.run('alice', task, {})

        self.assertEqual(output['source_conflict']['status'], 'resolved_conflict')
        self.assertEqual(output['source_conflict']['resolved_value'], 45)
        self.assertIn('Kaynak doğrulaması', output['text'])


if __name__ == '__main__':
    unittest.main()
