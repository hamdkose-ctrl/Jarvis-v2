import unittest
from unittest.mock import Mock,patch

from modules import acceptance_checks


class NewsAcceptanceHelperTests(unittest.TestCase):
    def test_goal_signature_ignores_volatile_top_level_time(self):
        base={'id':'g1','owner':'alice','request':'haber','state':'done','goals':[],'steps':[],'outputs':{},'updated':1}
        later={**base,'updated':999}
        self.assertEqual(acceptance_checks._goal_signature(base),acceptance_checks._goal_signature(later))
        changed={**base,'outputs':{'s1':{'state':'done'}}}
        self.assertNotEqual(acceptance_checks._goal_signature(base),acceptance_checks._goal_signature(changed))

    def test_news_job_facts_requires_valid_receipts_and_counts_publishers(self):
        job={
            'request':'son dakika haberleri',
            'outputs':{
                'a':{'state':'done','news_article':True},
                'b':{'state':'done','news_article':True},
                'c':{'state':'failed','news_article':True},
            },
        }
        receipts=[
            {'url':'https://example-a.test/haber/1','published':'2026-10-21'},
            {'url':'https://example-b.test/haber/2','published':'2026-10-21'},
        ]
        with patch('modules.research_evidence.news_receipt',side_effect=receipts) as receipt, \
                patch('modules.research_evidence.news_date') as news_date, \
                patch('modules.publisher_news.publisher_key',side_effect=['a','b']):
            articles,publishers=acceptance_checks._news_job_facts(job)
        self.assertEqual(articles,2)
        self.assertEqual(publishers,{'a','b'})
        self.assertEqual(receipt.call_count,2)
        self.assertEqual(news_date.call_count,2)

    def test_news_chat_resume_is_pending_when_live_sources_do_not_close_the_goal(self):
        job={'state':'paused','blocker':'Tarihli haber kanıtı bulunamadı.'}
        runtime=Mock();runtime._prefetch_pool=None
        with patch('modules.engine_runtime.EngineContext',return_value=runtime), \
                patch('modules.goal_executor.latest',return_value=job):
            state,detail=acceptance_checks._news_chat_resume('alice')
        self.assertEqual(state,'pending')
        self.assertIn('devam denetimi yapılmadı',detail)
        runtime.handle.assert_called_once_with('hedef son dakika haberleri')


if __name__=='__main__':
    unittest.main()
