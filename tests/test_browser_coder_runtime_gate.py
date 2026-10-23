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

    def test_browser_prepare_keeps_native_approval_contract(self):
        from modules import specialist_orchestrator
        step={'id':'s1','tool':'browser','input':{'url':'https://example.com','instruction':'formu doldur'},'depends':[]}
        native={'state':'approval','text':'Tarayıcı işlemi onay bekliyor.','id':'browser-approval-1'}
        with patch('modules.goal_tools.execute',return_value=native) as execute:
            output=specialist_orchestrator.execute_step(self.runtime(),self.job(),step,self.identity('browser'))
        execute.assert_called_once()
        self.assertEqual(output,native)

    def test_browser_read_only_done_is_fenced_and_committed(self):
        from modules import specialist_orchestrator
        step={'id':'s1','tool':'browser','input':{'url':'https://example.com','instruction':'Yalnız oku'},'depends':[]}
        native={'state':'done','text':'salt okunur sonuç'}
        enriched={**self.identity('browser'),'command_id':'s1:1'}
        expected={'owner':'alice','job_id':'job-1','step_id':'s1','command_id':'s1:1'}
        fenced={**native,'_worker_result':{'schema':'worker_result.v1'}}
        with patch('modules.goal_tools.execute',return_value=native) as execute, \
             patch('modules.runtime_worker_result.prepare',return_value=(enriched,expected)) as prepare, \
             patch('modules.worker_result_hook.wrap_output',return_value=fenced) as wrap, \
             patch('modules.runtime_worker_result.accept_and_commit',return_value=native) as accept:
            output=specialist_orchestrator.execute_step(self.runtime(),self.job(),step,self.identity('browser'))
        execute.assert_called_once()
        prepare.assert_called_once()
        wrap.assert_called_once_with(native,enriched)
        accept.assert_called_once_with(fenced,expected)
        self.assertEqual(output,native)


if __name__=='__main__':
    unittest.main()
