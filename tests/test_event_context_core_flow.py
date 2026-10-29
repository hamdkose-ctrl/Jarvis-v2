"""Real Core lifecycle with fake planner/tool transport; no live account/network/model."""
import unittest
from unittest.mock import patch
import test_goal_executor as core_fixtures
from modules import goal_executor as goals, task_agents, news_temporal

class EventContextCoreFlow(unittest.TestCase):
    def setUp(self):core_fixtures.GoalTests.setUp(self)
    def test_worker_cannot_choose_scope_core_asks_and_keeps_goal_pending(self):
        core_fixtures.GoalTests.responses(self,
            {'action':'plan','goals':['Kararın geçerliliğini doğrula']},
            {'action':'tool','goal':0,'tool':'research','input':{'url':'https://example.com/notice','question':'Yarın geçerli mi'},'depends':[]},
            {'action':'ask','question':news_temporal.EventContextRequired.question})
        with patch.object(task_agents,'worker',side_effect=news_temporal.EventContextRequired(news_temporal.EventContextRequired.question)):
            result=goals.run(self.runtime,'Yarın tatil haberi doğru mu?')
        job=goals.latest('alice')
        self.assertEqual(job['state'],'question',result)
        self.assertEqual(job['question'],news_temporal.EventContextRequired.question)
        self.assertEqual(job['goals'][0]['state'],'pending')
        self.assertFalse(any(row.get('state')=='done' for row in job['outputs'].values()))
