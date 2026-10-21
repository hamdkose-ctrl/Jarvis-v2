"""Model specialist labels cannot strand otherwise valid durable tool steps."""
import copy
import unittest
from unittest.mock import patch
from test_stale_goal_and_quota import _Base
import test_news_chat_writer as news_fixture
from modules import goal_executor as goals, team_center, specialist_orchestrator


class GoalSpecialistRoutingTests(_Base):
    def test_wrong_unknown_and_disabled_model_labels_use_registered_data_specialist(self):
        entries=copy.deepcopy(team_center.DEFAULTS)
        next(m for m in entries if m['id']=='finance')['enabled']=False
        for proposed in ('production','unknown','finance'):
            with self.subTest(proposed=proposed):
                sequence=[{'action':'plan','goals':['Kaynakları listele']},
                          {'action':'tool','goal':0,'tool':'data','specialist':proposed,
                           'input':{'operation':'sources'}},
                          {'action':'complete','goal':0,'evidence':['s1']}]
                with patch.object(team_center,'members',return_value=entries), \
                        patch.object(goals,'_planner',side_effect=sequence) as planner:
                    reply=goals.run(self.runtime,'Kaynakları listele')
                job=goals.latest('alice')
                self.assertEqual(job['state'],'done',reply)
                self.assertEqual(job['steps'][0]['specialist']['id'],'research')
                self.assertEqual(job['outputs']['s1']['state'],'done')
                self.assertEqual(job['decision_diagnostics'],[])
                self.assertEqual(planner.call_count,3)

    def test_explicit_specialist_contract_stays_strict(self):
        with patch.object(team_center,'members',return_value=copy.deepcopy(team_center.DEFAULTS)):
            with self.assertRaisesRegex(ValueError,'Seçilen uzman'):
                team_center.assign('alice','data',preferred='production')
            with self.assertRaisesRegex(ValueError,'Seçilen uzman'):
                specialist_orchestrator.validate('alice','Kaynakları listele',[
                    {'id':'a','specialist':'production','tool':'data','input':{'operation':'sources'}}])


class NewsSpecialistRoutingTests(unittest.TestCase):
    def test_news_delivery_and_closed_resume_survive_wrong_model_specialist(self):
        scenario=news_fixture.NewsChatWriterTests();self.addCleanup(scenario.doCleanups)
        original=goals._planner
        def planner(*args,**kwargs):
            call=original(*args,**kwargs)
            if call.get('action')=='tool':call['specialist']='operations'
            return call
        with patch.object(goals,'_planner',side_effect=planner), \
                patch.object(team_center,'members',return_value=copy.deepcopy(team_center.DEFAULTS)):
            case,job,reply,fetch=scenario.run_case()
            self.assertEqual(job['state'],'done',reply)
            self.assertTrue(all(step['specialist']['id']=='research' for step in job['steps']))
            self.assertFalse(any(step['tool']=='writer' for step in job['steps']))
            self.assertEqual(fetch.call_count,2)
            self.assertEqual(case.ask.call_count,4)
            before=copy.deepcopy(job)
            case.ask.reset_mock();case.ask.side_effect=AssertionError('Closed goal must not replan')
            answer=goals.handle(case.runtime,'devam')
            self.assertIn('Açık hedef yok',answer)
            self.assertEqual(goals.latest('alice'),before)
            case.ask.assert_not_called()
