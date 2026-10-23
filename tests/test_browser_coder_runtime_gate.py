import unittest
from types import SimpleNamespace
from unittest.mock import patch


class BrowserCoderRuntimeGateTests(unittest.TestCase):
    def runtime(self):
        return SimpleNamespace(profile=SimpleNamespace(slug='alice'))

    def job(self):
        return {'owner':'alice','id':'job-1','request':'kod taslağı hazırla','outputs':{}}

    def identity(self, kind):
        return {'version':1,'owner':'alice','job_id':'job-1','task_id':'s1','capability':kind,
                'risk':'development_workspace' if kind=='coder' else 'external_effect_possible',
                'replay_safe':False,'attempt':1,'outcome':'pending','request':'kod taslağı hazırla'}

    def test_coder_prepare_does_not_execute_worker(self):
        from modules import specialist_orchestrator
        step={'id':'s1','tool':'coder','input':{'request':'bir modül taslağı hazırla'},'depends':[]}
        with patch('modules.goal_tools.execute') as execute:
            output=specialist_orchestrator.execute_step(self.runtime(),self.job(),step,self.identity('coder'))
        execute.assert_not_called()
        self.assertEqual(output['state'],'approval')
        self.assertEqual(output['capability_id'],'task.coder')
        self.assertEqual(output['job_id'],'job-1')
        self.assertEqual(output['step_id'],'s1')
        self.assertIn('input_digest',output)

    def test_coder_approval_must_match_prepare_artifact(self):
        from modules import specialist_orchestrator
        step={'id':'s1','tool':'coder','input':{'request':'bir modül taslağı hazırla'},'depends':[]}
        bad={'state':'approval','capability_id':'task.coder','job_id':'job-1','step_id':'other','input_digest':'x'}
        with self.assertRaises(PermissionError):
            specialist_orchestrator.execute_step(self.runtime(),self.job(),step,self.identity('coder'),approval=bad)


if __name__=='__main__':
    unittest.main()
