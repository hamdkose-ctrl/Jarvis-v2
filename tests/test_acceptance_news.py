import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import acceptance_checks


class NewsAcceptanceHelperTests(unittest.TestCase):
    def test_cli_accepts_news_flag_and_passes_it_to_runner(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output=Path(temp_dir)/'acceptance.json'
            with patch.object(acceptance_checks,'run',return_value={'checks':[]}) as run, \
                    patch.object(sys,'argv',['acceptance_checks','--news','--skip-suite','--output',str(output)]):
                self.assertEqual(acceptance_checks.main(),0)
        self.assertTrue(run.call_args.kwargs['news'])
        self.assertFalse(run.call_args.kwargs['suite'])

    def test_failure_summary_keeps_recovery_facts_in_truncated_pr_preview(self):
        job={'state':'paused','request':'son dakika haberleri',
             'goals':[{'state':'done'},{'state':'pending','text':'PRIVATE_REQUEST'}],
             'steps':[{'id':'s1','tool':'data','state':'done','recovery':True},
                      {'id':'s2','tool':'research','state':'failed','recovery':True}],
             'outputs':{'s2':{'state':'failed','text':'PRIVATE_CONTENT'}},
             'blocker':'3 geçersiz karar '+('x'*300),
             'decision_diagnostics':[{'reason':'Bu hedefin başarılı adımı değil.'}]*3}
        detail=acceptance_checks._news_failure_detail(job)
        self.assertIn('hedefler=done,pending',detail[:600])
        self.assertIn('makale=0',detail[:600])
        self.assertIn('kurtarma=data.done:1,research.failed:1',detail[:600])
        self.assertNotIn('PRIVATE_',detail)

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

    def test_all_three_live_scenarios_are_required(self):
        with patch.object(acceptance_checks,'_news_scenario',side_effect=[
                ('passed','2/2'),('failed','konu kanıtı yok'),('passed','dosya doğrulandı')]) as run:
            state,detail=acceptance_checks._news_chat_resume('alice')
        self.assertEqual(state,'failed')
        self.assertEqual(run.call_count,3)
        self.assertIn('Türkiye AI sohbet: failed',detail)
        self.assertTrue(run.call_args_list[-1].kwargs['file_report'])
        self.assertEqual(
            [call.args[1] for call in run.call_args_list],
            ['Son 7 gün güncel haberleri araştır',
             'Son 7 gündeki Türkiye yapay zekâ gelişmelerini araştır',
             'Son 7 gündeki Türkiye yapay zekâ gelişmelerini araştır ve raporu dosyaya kaydet'],
        )
        self.assertFalse(run.call_args_list[0].kwargs['file_report'])

    def test_all_scenarios_must_pass_and_exceptions_do_not_skip_file_case(self):
        with patch.object(acceptance_checks,'_news_scenario',return_value=('passed','2/2')):
            self.assertEqual(acceptance_checks._news_chat_resume('alice')[0],'passed')
        with patch.object(acceptance_checks,'_news_scenario',side_effect=[
                ('passed','2/2'),ValueError('invalid receipt'),('passed','file')]) as run:
            self.assertEqual(acceptance_checks._news_chat_resume('alice')[0],'failed')
        self.assertEqual(run.call_count,3)


if __name__=='__main__':
    unittest.main()
