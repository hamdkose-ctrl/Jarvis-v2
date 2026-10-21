"""Keep automatic follow-up focused on failed checks, not optional configuration."""
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import test_pc_test_watcher as watcher_fixture
import test_codex_followup as followup_fixture

spec=importlib.util.spec_from_file_location('pc_loop_test',Path(__file__).resolve().parents[1]/'scripts'/'pc_test_loop.py')
loop=importlib.util.module_from_spec(spec)
with patch.dict(sys.modules,{'pc_test_watcher':watcher_fixture.watcher,'codex_followup':followup_fixture.followup}):
    spec.loader.exec_module(loop)


class PcLoopFailureHintTests(unittest.TestCase):
    def report(self):
        return {'sha':'a'*40,'status':'failed','validation':{'exit_code':0},
                'desktop_acceptance':{'checks':[
                    {'check':'github_source','state':'pending','detail':'PRIVATE_CONFIG'*90},
                    {'check':'local_configuration','state':'informational','detail':'PRIVATE_ACCOUNT'*90},
                    {'check':'calculator','state':'passed'},
                    {'check':'news_chat_resume','state':'failed','detail':'Two publishers; two pending goals'}]}}

    def test_actual_failure_survives_long_optional_details(self):
        text=loop.failure_hint(self.report())
        self.assertIn('news_chat_resume=failed',text)
        self.assertIn('two pending goals',text)
        self.assertNotIn('PRIVATE_',text)

    def test_optional_changes_do_not_restart_same_failure(self):
        report=self.report();signature=loop.failure_signature(report)
        report['sha']='b'*40
        report['desktop_acceptance']['checks'][0]['detail']='Different source status'
        allowed,reason=loop.should_run_codex(report,{'last_failure_signature':signature})
        self.assertFalse(allowed)
        self.assertEqual(reason,'repeated_failure_stopped')

    def test_pending_required_check_is_actionable(self):
        report=self.report()
        report['desktop_acceptance']['checks']=[{'check':'calculator','state':'pending','detail':'Ambiguous window'}]
        self.assertIn('calculator=pending',loop.failure_hint(report))
