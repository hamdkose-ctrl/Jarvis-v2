"""Rejected planner decisions reach PC acceptance without raw model inputs."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
from test_stale_goal_and_quota import _Base
from test_mail_calendar_fixes import engine_runtime
from modules import goal_executor as goals, acceptance_checks


class DecisionDiagnosticsTests(_Base):
    def test_three_rejections_are_ordered_and_exported_without_input_values(self):
        invalid={'action':'tool','goal':0,'tool':'action',
                 'input':{'action':'tasks_list','params':{}},
                 'depends':['DO_NOT_EXPORT']}
        sequence=[{'action':'plan','goals':['Listeyi incele']},invalid,invalid,invalid]
        with patch.object(goals,'_planner',side_effect=sequence) as planner:
            goals.run(self.runtime,'Listeyi incele')
        job=goals.latest('alice')
        trace=job.get('decision_diagnostics',[])
        self.assertEqual(len(trace),3)
        self.assertEqual([row['attempt'] for row in trace],[1,2,3])
        self.assertTrue(all(row['tool']=='action' and row['action']=='tool' for row in trace))
        self.assertIn('Bağımlılık',trace[-1]['reason'])
        self.assertEqual(trace[-1]['input_fields'],['action','params'])
        detail=acceptance_checks._news_failure_detail(job)
        self.assertIn('decision_diagnostics',detail)
        self.assertIn('Bağımlılık',detail)
        self.assertNotIn('DO_NOT_EXPORT',detail)
        self.assertEqual(planner.call_count,4)
        self.assertEqual(job['state'],'paused')
        self.assertEqual(job['steps'],[])
        runtime=SimpleNamespace(handle=Mock())
        with patch.object(engine_runtime,'EngineContext',return_value=runtime), \
                patch.object(goals,'latest',return_value=job):
            state,exported=acceptance_checks._news_chat_resume('alice')
        self.assertEqual(state,'failed')
        self.assertEqual(exported,detail)
        runtime.handle.assert_called_once_with('hedef son dakika haberleri')

    def test_parse_failure_cannot_reuse_previous_call_and_resume_resets_trace(self):
        invalid={'action':'tool','goal':0,'tool':'action','input':{},'depends':[]}
        sequence=[{'action':'plan','goals':['Listeyi incele']},invalid,
                  ValueError('Hedef yürütücüsü geçerli JSON üretmedi.'),
                  ValueError('Hedef yürütücüsü geçerli JSON üretmedi.')]
        with patch.object(goals,'_planner',side_effect=sequence):
            goals.run(self.runtime,'Listeyi incele')
        job=goals.latest('alice')
        trace=job['decision_diagnostics']
        self.assertEqual(trace[0]['action'],'tool')
        self.assertEqual(trace[1]['action'],'unparsed')
        self.assertEqual(trace[1]['tool'],'')
        with patch.object(goals,'_planner',return_value={'action':'ask','question':'Hangi klasör?' }):
            goals.run(self.runtime,'hedef devam',resume=True)
        self.assertEqual(goals.latest('alice')['decision_diagnostics'],[])

    def test_reason_redaction_precedes_export(self):
        sequence=[{'action':'plan','goals':['Listeyi incele']}] + [
            ValueError('Authorization: Bearer private-secret-value')] * 3
        with patch.object(goals,'_planner',side_effect=sequence):
            goals.run(self.runtime,'Listeyi incele')
        detail=acceptance_checks._news_failure_detail(goals.latest('alice'))
        self.assertNotIn('private-secret-value',detail)
        self.assertIn('gizlendi',detail)
