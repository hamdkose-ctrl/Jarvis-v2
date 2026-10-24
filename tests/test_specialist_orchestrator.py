"""Specialist orchestration contract checks. No live model/account/network calls."""
from types import SimpleNamespace, ModuleType
import sys
import unittest
from unittest.mock import patch

try:
    from google import genai as _genai_probe  # noqa: F401
except ImportError:
    # Cloud/offline sandboxes without pypi access cannot install google-genai.
    # modules.llm imports it at module load time purely to build a client;
    # nothing in this file's tests touches a real model. Install a minimal
    # stand-in so the import chain (goal_tools -> llm) resolves, without
    # changing any production module or faking execute_step's own behaviour.
    _google_pkg = sys.modules.get('google') or ModuleType('google')
    _genai_mod = ModuleType('google.genai')
    _genai_mod.errors = ModuleType('google.genai.errors')
    _genai_mod.types = ModuleType('google.genai.types')

    class _StubClient:
        def __init__(self, *a, **k): pass

    _genai_mod.Client = _StubClient
    _google_pkg.genai = _genai_mod
    sys.modules.setdefault('google', _google_pkg)
    sys.modules['google.genai'] = _genai_mod
    sys.modules['google.genai.errors'] = _genai_mod.errors
    sys.modules['google.genai.types'] = _genai_mod.types

from modules import specialist_orchestrator as orchestrator


class SpecialistOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.runtime=SimpleNamespace(profile=SimpleNamespace(slug='alice'))

    def test_cross_domain_steps_keep_explicit_specialist_ownership(self):
        members=[
            {'id':'finance','name':'Finans','tags':[],'tools':['data','verify']},
            {'id':'social','name':'Sosyal','tags':[],'tools':['account','writer','verify']},
        ]
        tasks=[
            {'id':'finance-read','specialist':'finance','tool':'data','input':{'operation':'exchange','base':'USD','quote':'TRY'}},
            {'id':'social-read','specialist':'social','tool':'account','input':{'service':'youtube','operation':'channel_stats'}},
        ]
        outputs=[{'state':'done','text':'kur','owner':'alice','local_evidence':'data'},
                 {'state':'done','text':'kanal','owner':'alice','verification':{'agent':'account'}}]
        with patch('modules.specialist_orchestrator.team_center.members',return_value=members), \
             patch('modules.specialist_orchestrator.goal_tools.validate',side_effect=lambda k,d:d), \
             patch('modules.specialist_orchestrator.goal_tools.checkpoint',return_value=None), \
             patch('modules.specialist_orchestrator.goal_tools.execute',side_effect=outputs), \
             patch('modules.specialist_orchestrator.goal_tools.verify',return_value=True):
            result=orchestrator.run(self.runtime,'Kur ve sosyal kanal durumunu birlikte kontrol et',tasks)
        self.assertEqual(result['state'],'done')
        self.assertEqual([(t['specialist'],t['tool']) for t in result['tasks']],[('finance','data'),('social','account')])

    def test_specialist_cannot_use_tool_outside_its_contract(self):
        members=[{'id':'finance','name':'Finans','tags':[],'tools':['data','verify']}]
        tasks=[{'id':'send','specialist':'finance','tool':'publish','input':{'service':'gmail','destination':'a@b.com','subject':'x','text':'y'}}]
        with patch('modules.specialist_orchestrator.team_center.members',return_value=members):
            with self.assertRaisesRegex(ValueError,'bu aracı kullanamaz'):
                orchestrator.validate('alice','mail gönder',tasks)

    def test_dependency_must_be_completed_before_handoff(self):
        members=[
            {'id':'research','name':'Araştırma','tags':[],'tools':['research']},
            {'id':'production','name':'Üretim','tags':[],'tools':['writer']},
        ]
        tasks=[
            {'id':'write','specialist':'production','tool':'writer','depends':['missing'],'input':{'instruction':'rapor','filename':'x.md'}},
        ]
        with patch('modules.specialist_orchestrator.team_center.members',return_value=members):
            with self.assertRaisesRegex(ValueError,'bağımlılığı'):
                orchestrator.validate('alice','rapor hazırla',tasks)

    def test_existing_permission_gate_is_not_bypassed(self):
        members=[{'id':'social','name':'Sosyal','tags':[],'tools':['publish']}]
        tasks=[{'id':'send','specialist':'social','tool':'publish','input':{'service':'gmail','destination':'a@b.com','subject':'x','text':'y'}}]
        with patch('modules.specialist_orchestrator.team_center.members',return_value=members), \
             patch('modules.specialist_orchestrator.goal_tools.validate',side_effect=lambda k,d:d), \
             patch('modules.specialist_orchestrator.goal_tools.checkpoint',return_value=None), \
             patch('modules.specialist_orchestrator.goal_tools.execute',side_effect=PermissionError('onay gerekli')), \
             patch('modules.specialist_orchestrator.goal_tools.reconcile',return_value=None):
            with self.assertRaises(PermissionError):orchestrator.run(self.runtime,'taslak hazırla; gönderme',tasks)

    def test_non_durable_run_rejects_conditional_capability_before_worker(self):
        members=[{'id':'social','name':'Sosyal','tags':[],'tools':['publish']}]
        tasks=[{'id':'send','specialist':'social','tool':'publish',
                'input':{'service':'gmail','destination':'a@b.com','subject':'x','text':'y'}}]
        with patch('modules.specialist_orchestrator.team_center.members',return_value=members), \
             patch('modules.specialist_orchestrator.goal_tools.validate',side_effect=lambda k,d:d), \
             patch('modules.specialist_orchestrator.goal_tools.replay_safe',return_value=False), \
             patch('modules.specialist_orchestrator.goal_tools.execute') as execute:
            with self.assertRaisesRegex(PermissionError,'durable yürütme'):
                orchestrator.run(self.runtime,'mail gönder',tasks)
        execute.assert_not_called()


class DecisionContextTests(unittest.TestCase):
    """_decision_context() must derive gate inputs from real job/step state,
    never emit the permissive defaults the gate would otherwise treat as a
    pre-cleared execute/ready decision."""

    def _job(self,**over):
        base={'owner':'alice','request':'rapor hazırla','state':'running'}
        base.update(over);return base

    def _step(self,**over):
        base={'state':'running'}
        base.update(over);return base

    def test_missing_owner_forbids_domain_authority_and_blocks_invariant(self):
        ctx=orchestrator._decision_context(self._job(owner=None),self._step())
        self.assertEqual(ctx['domain_invariant'],'block')
        self.assertEqual(ctx['domain_authority'],'forbidden')

    def test_missing_request_forbids_user_and_domain_authority(self):
        ctx=orchestrator._decision_context(self._job(request=''),self._step())
        self.assertEqual(ctx['domain_invariant'],'block')
        self.assertEqual(ctx['domain_authority'],'forbidden')
        self.assertEqual(ctx['user_authority'],'forbidden')

    def test_terminal_job_state_forbids_job_authority_and_blocks_invariant(self):
        for terminal in ('done','cancelled','failed'):
            ctx=orchestrator._decision_context(self._job(state=terminal),self._step())
            self.assertEqual(ctx['job_authority'],'forbidden',terminal)
            self.assertEqual(ctx['domain_invariant'],'block',terminal)
            # Owner/request are still valid, so this must not be confused with
            # an identity failure.
            self.assertEqual(ctx['domain_authority'],'execute',terminal)
            self.assertEqual(ctx['user_authority'],'execute',terminal)

    def test_terminal_step_state_forbids_job_authority_and_blocks_invariant(self):
        for terminal in ('done','cancelled','failed'):
            ctx=orchestrator._decision_context(self._job(),self._step(state=terminal))
            self.assertEqual(ctx['job_authority'],'forbidden',terminal)
            self.assertEqual(ctx['domain_invariant'],'block',terminal)

    def test_running_job_and_step_derive_full_execute_ready_context(self):
        ctx=orchestrator._decision_context(self._job(),self._step())
        self.assertEqual(ctx,{
            'domain_invariant':'pass','domain_authority':'execute',
            'user_authority':'execute','job_authority':'execute','effect_state':'ready',
        })
        # None is treated the same as the initial 'running' state for both job
        # and step (pre-dispatch default), still with no permissive defaults.
        ctx_none=orchestrator._decision_context(self._job(state=None),self._step(state=None))
        self.assertEqual(ctx_none,ctx)


class ExecuteStepGateTests(unittest.TestCase):
    """execute_step() must route real DecisionContext into
    runtime_execution_gate.plan_task and honour its verdict before any
    worker runs."""

    def setUp(self):
        self.runtime=SimpleNamespace(profile=SimpleNamespace(slug='alice'))
        self.identity={'owner':'alice','job_id':'job-1','request':'rapor'}

    def _job(self,**over):
        base={'owner':'alice','request':'rapor hazırla','state':'running','outputs':{}}
        base.update(over);return base

    def _step(self,**over):
        base={'tool':'verify','input':{'target':'x'},'depends':[],'state':'running'}
        base.update(over);return base

    def test_plan_task_receives_the_real_derived_decision_context(self):
        job=self._job();step=self._step()
        expected_ctx=orchestrator._decision_context(job,step)
        with patch('modules.runtime_execution_gate.plan_task',
                   return_value={'phase':'execute','worker_allowed':True,'reason_code':'OK'}) as plan_task, \
             patch('modules.specialist_orchestrator.goal_tools.execute',return_value={'state':'done'}) as execute:
            orchestrator.execute_step(self.runtime,job,step,self.identity)
        _,kwargs=plan_task.call_args
        self.assertEqual(kwargs['domain_invariant'],expected_ctx['domain_invariant'])
        self.assertEqual(kwargs['domain_authority'],expected_ctx['domain_authority'])
        self.assertEqual(kwargs['user_authority'],expected_ctx['user_authority'])
        self.assertEqual(kwargs['job_authority'],expected_ctx['job_authority'])
        self.assertEqual(kwargs['effect_state'],expected_ctx['effect_state'])
        self.assertEqual(kwargs['approval_verified'],False)
        execute.assert_called_once()

    def test_invalid_owner_or_request_yields_forbidden_context_and_blocks_before_worker(self):
        job=self._job(owner=None);step=self._step()
        with patch('modules.specialist_orchestrator.goal_tools.execute') as execute:
            with self.assertRaises(PermissionError):
                orchestrator.execute_step(self.runtime,job,step,self.identity)
        execute.assert_not_called()

    def test_terminal_job_blocks_before_worker_is_called(self):
        job=self._job(state='done');step=self._step()
        with patch('modules.specialist_orchestrator.goal_tools.execute') as execute:
            with self.assertRaises(PermissionError):
                orchestrator.execute_step(self.runtime,job,step,self.identity)
        execute.assert_not_called()

    def test_terminal_step_blocks_before_worker_is_called(self):
        job=self._job();step=self._step(state='cancelled')
        with patch('modules.specialist_orchestrator.goal_tools.execute') as execute:
            with self.assertRaises(PermissionError):
                orchestrator.execute_step(self.runtime,job,step,self.identity)
        execute.assert_not_called()

    def test_gate_blocked_verdict_prevents_goal_tools_execute(self):
        job=self._job();step=self._step()
        with patch('modules.runtime_execution_gate.plan_task',
                   return_value={'phase':'blocked','worker_allowed':False,'reason_code':'TEST_BLOCK'}), \
             patch('modules.specialist_orchestrator.goal_tools.execute') as execute:
            with self.assertRaisesRegex(PermissionError,'TEST_BLOCK'):
                orchestrator.execute_step(self.runtime,job,step,self.identity)
        execute.assert_not_called()

    def test_normal_execute_path_unaffected_by_gated_tool_outside_gate_set(self):
        job=self._job();step=self._step(tool='data',input={'operation':'exchange'})
        with patch('modules.specialist_orchestrator.goal_tools.execute',
                   return_value={'state':'done'}) as execute:
            output=orchestrator.execute_step(self.runtime,job,step,self.identity)
        execute.assert_called_once()
        self.assertEqual(output,{'state':'done'})

    def test_coder_prepare_approval_flow_unaffected(self):
        job=self._job();step=self._step(tool='coder',input={'instruction':'x'})
        with patch('modules.runtime_execution_gate.plan_task',
                   return_value={'phase':'prepare','worker_allowed':False,'reason_code':'ASK'}), \
             patch('modules.developer.status',return_value={'enabled':True,'unlocked':True}), \
             patch('modules.runtime_prepare_approval.prepare',return_value={'state':'approval'}) as prepare, \
             patch('modules.runtime_execution_gate.accept_prepare_result',
                   side_effect=lambda plan,output:output) as accept, \
             patch('modules.specialist_orchestrator.goal_tools.execute') as execute:
            output=orchestrator.execute_step(self.runtime,job,step,self.identity)
        prepare.assert_called_once()
        accept.assert_called_once()
        execute.assert_not_called()
        self.assertEqual(output,{'state':'approval'})

    def test_browser_approval_still_verified_before_gate_execute_phase(self):
        job=self._job();step=self._step(tool='browser',input={'url':'https://x'})
        with patch('modules.runtime_execution_gate.plan_task',
                   return_value={'phase':'execute','worker_allowed':True,'reason_code':'OK'}) as plan_task, \
             patch('modules.specialist_orchestrator.goal_tools.execute',return_value={'state':'done'}) as execute:
            orchestrator.execute_step(self.runtime,job,step,self.identity,approval='tok')
        _,kwargs=plan_task.call_args
        self.assertEqual(kwargs['approval_verified'],True)
        execute.assert_called_once()


if __name__=='__main__':
    unittest.main()
