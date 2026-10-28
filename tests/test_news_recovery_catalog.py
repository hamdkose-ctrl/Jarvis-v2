"""Recovery must persist pipeline receipts, never restart legacy catalog traversal."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from modules import news_recovery


class NewsRecoveryCatalogTests(unittest.TestCase):
    def test_broad_recovery_scans_registered_catalog_after_two_publishers(self):
        job = {
            'id': 'a' * 16, 'owner': 'alice', 'state': 'running',
            'request': 'Türkiye yapay zekâ gelişmelerini araştır',
            'goals': [{'state': 'pending'}], 'steps': [], 'outputs': {},
        }
        rows = [
            {'news_article': {'url': 'https://aa.com.tr/haber', 'title': 'AI',
                              'published': '2026-10-28', 'text': 'Yapay zekâ kanıtı'}},
            {'news_article': {'url': 'https://ntv.com.tr/haber', 'title': 'AI',
                              'published': '2026-10-28', 'text': 'Yapay zekâ kanıtı'}},
        ]
        runtime = SimpleNamespace(profile=SimpleNamespace(slug='alice'))

        def record(_runtime, current, step):
            step['state'] = 'done'
            article = next(row['news_article'] for row in rows if row['news_article']['url'] == step['input']['url'])
            current['outputs'][step['id']] = {
                'state': 'done', 'news_article': article,
                'source_quotes': ['Yapay zekâ kanıtı'], 'source': article['url'],
            }

        with patch('modules.news_pipeline.deliver_job', return_value={'verified': rows}) as pipeline, \
             patch('modules.goal_executor._record', side_effect=record), \
             patch('modules.goal_executor._ensure'), patch('modules.goal_executor._save'), \
             patch('modules.goal_tools.verify'), \
             patch('modules.publisher_news.recovery_indexes', side_effect=AssertionError('legacy catalog ran')):
            news_recovery._chat_deliver(runtime, job, max_new_steps=4)

        pipeline.assert_called_once()
        self.assertEqual([step['tool'] for step in job['steps']], ['research', 'research'])
        self.assertEqual(job['goals'][0]['state'], 'done')
        self.assertEqual(len(job['goals'][0]['evidence']), 2)


if __name__ == '__main__':
    unittest.main()
