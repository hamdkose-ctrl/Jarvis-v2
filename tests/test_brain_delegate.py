"""Jarvis brain delegation regressions. No live model/provider calls."""
from types import SimpleNamespace
import json
import unittest
from unittest.mock import patch

from modules import brain_delegate


class BrainDelegateTests(unittest.TestCase):
    def test_brain_assigns_specialists_and_executes_validated_plan(self):
        members=[
            {'id':'research','name':'Araştırma','tags':['haber'],'tools':['research','data','verify']},
            {'id':'production','name':'Üretim','tags':['rapor'],'tools':['writer','verify']},
        ]
        raw={'tasks':[
            {'id':'find','specialist':'research','tool':'data','input':{'operation':'sources'},'depends':[]},
            {'id':'report','specialist':'production','tool':'writer','input':{'instruction':'Kaynaklara göre rapor','filename':'rapor.md'},'depends':['find']},
            {'id':'check','specialist':'production','tool':'verify','input':{},'depends':['report']},
        ]}
        runtime=SimpleNamespace(profile=SimpleNamespace(slug='alice'))
        with patch('modules.brain_delegate.team_center.members',return_value=members), \
             patch('modules.brain_delegate.llm.ask',return_value=json.dumps(raw)) as ask, \
             patch('modules.brain_delegate.specialist_orchestrator.validate',side_effect=lambda o,r,t:t) as validate, \
             patch('modules.brain_delegate.specialist_orchestrator.run',return_value={'state':'done'}) as execute:
            result=brain_delegate.run(runtime,'Türkiye yapay zekâ haberlerini araştır ve raporla')
        self.assertEqual(result['state'],'done');ask.assert_called_once();validate.assert_called_once();execute.assert_called_once()
        self.assertEqual(execute.call_args.args[2][0]['specialist'],'research')

    def test_invalid_specialist_plan_is_rejected_before_execution(self):
        members=[{'id':'finance','name':'Finans','tags':['finans'],'tools':['data','verify']}]
        raw={'tasks':[{'id':'bad','specialist':'finance','tool':'publish','input':{},'depends':[]}]}
        with patch('modules.brain_delegate.team_center.members',return_value=members), \
             patch('modules.brain_delegate.llm.ask',return_value=json.dumps(raw)), \
             patch('modules.brain_delegate.specialist_orchestrator.validate',side_effect=ValueError('Seçilen uzman bu aracı kullanamaz.')), \
             patch('modules.brain_delegate.specialist_orchestrator.run') as execute:
            with self.assertRaises(ValueError):brain_delegate.plan('alice','finans raporu hazırla')
        execute.assert_not_called()

    def test_planner_prompt_explicitly_denies_permission_granting_and_open_only_success(self):
        members=[{'id':'operations','name':'Operasyon','tags':[],'tools':['application','desktop','verify']}]
        captured={}
        def ask(prompt,system='',**kwargs):
            captured['prompt']=prompt;captured['system']=system
            return '{"tasks":[{"id":"x","specialist":"operations","tool":"application","input":{"operation":"list"},"depends":[]}]}'
        with patch('modules.brain_delegate.team_center.members',return_value=members), \
             patch('modules.brain_delegate.llm.ask',side_effect=ask), \
             patch('modules.brain_delegate.specialist_orchestrator.validate',side_effect=lambda o,r,t:t):
            brain_delegate.plan('alice','Excel içinde satış toplamını bul')
        self.assertIn('Sayfa açmak',captured['system'])
        self.assertIn('izinleri model tarafından verilmez',captured['system'])


if __name__=='__main__':
    unittest.main()
