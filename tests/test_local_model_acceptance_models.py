"""Live acceptance must follow installed models without manufacturing a stale scenario."""
import runpy
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from modules import llm

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/local_model_acceptance.py'

class LocalModelAcceptanceModels(unittest.TestCase):
    def setUp(self):
        self.probe=runpy.run_path(str(SCRIPT),run_name='local_model_dynamic_probe')
        self.status={'local_backend':'ollama','local_model_preference':'missing-model',
            'local_installed_models':['qwen2.5:3b'],'local_effective_model':'qwen2.5:3b',
            'local_model_stale':True,'local_model_select_enabled':True}
    def test_three_billion_model_is_valid_without_seven_billion_model(self):
        self.assertEqual(self.probe['contract_errors'](self.status),[])
    def test_valid_installed_preference_is_not_forced_into_stale_scenario(self):
        self.status.update(local_model_preference='qwen2.5:3b',local_model_stale=False)
        self.assertEqual(self.probe['contract_errors'](self.status),[])
    def test_default_latest_alias_is_valid_preference(self):
        self.status.update(local_model_preference='llama3.2',local_installed_models=['llama3.2:latest'],
                           local_effective_model='llama3.2:latest',local_model_stale=False)
        self.assertEqual(self.probe['contract_errors'](self.status),[])
    def test_missing_or_uninstalled_effective_model_rejected(self):
        for models,effective in [([],''),(['qwen2.5:3b'],'qwen2.5-coder:7b')]:
            with self.subTest(models=models):
                status=dict(self.status,local_installed_models=models,local_effective_model=effective)
                self.assertTrue(self.probe['contract_errors'](status))
    def test_incorrect_stale_flag_rejected(self):
        self.status['local_model_stale']=False
        self.assertTrue(self.probe['contract_errors'](self.status))
    def test_no_saved_preference_is_reported_without_inventing_stale(self):
        self.status.update(local_model_preference='',local_model_stale=False)
        self.assertEqual(self.probe['contract_errors'](self.status),[])
    def test_other_installed_model_cannot_override_valid_preference(self):
        self.status.update(local_model_preference='qwen2.5:3b',local_model_stale=False,
                           local_installed_models=['qwen2.5:3b','gemma3:4b'],local_effective_model='gemma3:4b')
        self.assertTrue(self.probe['contract_errors'](self.status))
    def run_acceptance(self,answer='merhaba',route_model='qwen2.5:3b'):
        run=self.probe['run']
        with patch.dict(run.__globals__,{'_browser_check':Mock(return_value=(True,'UI verified'))}), \
             patch('web_models.WebModels.llm_status',return_value=self.status), \
             patch('modules.personalization.get_active',return_value='acceptance-fixture'), \
             patch.object(llm,'_timed',side_effect=lambda provider,call:call()), \
             patch.object(llm,'_ollama',return_value=answer), \
             patch.object(llm,'take_route',side_effect=[[],[(f'Cevap: Ollama (yerel) · {route_model}',True)]]):
            return run()
    def test_live_result_requires_route_for_actual_three_billion_model(self):
        result=self.run_acceptance()
        self.assertEqual(result['state'],'passed',result)
        self.assertIn('effective=qwen2.5:3b',result['detail'])
        self.assertIn('stale_preference',result['detail'])
    def test_wrong_model_route_and_empty_answer_still_fail(self):
        self.assertEqual(self.run_acceptance(route_model='different-model')['state'],'failed')
        self.assertEqual(self.run_acceptance(answer='')['state'],'failed')
