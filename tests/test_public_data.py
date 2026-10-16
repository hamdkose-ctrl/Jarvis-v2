"""Removed search cannot call an external service, including through old goals."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from modules import public_data,llm,goal_tools

class PublicDataTests(unittest.TestCase):
    def setUp(self):
        token=llm._key_context.set('alice');self.addCleanup(llm._key_context.reset,token)

    def test_legacy_search_fails_without_network(self):
        fetch=Mock()
        with self.assertRaisesRegex(ValueError,'kaldırıldı'):
            public_data.news_search('alice','science',fetcher=fetch)
        fetch.assert_not_called()

    def test_legacy_search_owner_boundary(self):
        fetch=Mock()
        with self.assertRaises(PermissionError):public_data.news_search('bob','science',fetcher=fetch)
        fetch.assert_not_called()

    def test_catalog_and_goal_adapter_are_model_free(self):
        runtime=SimpleNamespace(profile=SimpleNamespace(slug='alice'))
        identity={'owner':'alice','job_id':'job','task_id':'s1','request':'Haber kaynaklarını listele'}
        with patch.object(llm,'ask',side_effect=AssertionError('No model')):
            out=goal_tools.execute(runtime,'data',{'operation':'sources'},{},identity)
        self.assertTrue(goal_tools.verify(out,'alice'))
        self.assertEqual({s['operation'] for s in out['structured']['sources']},{'exchange','headlines'})
        row=public_data.catalog('alice');row['sources'][0]['name']='changed'
        self.assertNotEqual(public_data.catalog('alice')['sources'][0]['name'],'changed')

    def test_planner_cannot_expand_weekly_window(self):
        runtime=SimpleNamespace(profile=SimpleNamespace(slug='alice'))
        identity={'owner':'alice','job_id':'job','task_id':'s1','request':'Haftalık haberleri araştır'}
        with patch.object(public_data,'news_search') as network:
            with self.assertRaises(goal_tools.NotStarted):
                goal_tools.execute(runtime,'data',{'operation':'news_search','query':'science','days':90},{},identity)
        network.assert_not_called()
