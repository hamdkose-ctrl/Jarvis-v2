"""Specialist orchestration contract checks. No live model/account/network calls."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

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


if __name__=='__main__':
    unittest.main()
