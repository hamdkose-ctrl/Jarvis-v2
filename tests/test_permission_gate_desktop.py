"""Permission gate integration; UI/network and user storage are isolated."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tests.test_desktop_agent import FakeUI, screen, action
from modules import desktop_agent as agent, permission_gate, permission_classify, permission_grants, permission_audit


class PermissionDesktopTests(unittest.TestCase):
    def setUp(self):
        td=tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup)
        self.enterContext(patch.object(agent,'STORE',Path(td.name)/'jobs'))
        self.enterContext(patch.object(permission_grants,'ROOT',Path(td.name)/'grants'))
        self.enterContext(patch.object(permission_audit,'DATA_DIR',Path(td.name)))
        self.enterContext(patch.object(agent.privacy,'blocked',return_value=None))
        self.enterContext(patch.object(agent.time,'sleep'))
        self.audit=self.enterContext(patch.object(permission_audit,'record'))
        self.failure=self.enterContext(patch.object(agent,'_record_failure'))
        self.decide=self.enterContext(patch.object(permission_gate,'decide',return_value={'decision':'allow','reason':'İzinli.'}))
        self.classify=self.enterContext(patch.object(permission_classify,'classify',return_value='local_reversible'))
        self.ui=FakeUI()
        self.job={'owner':'alice','target':'Hesap Makinesi','goal':'12 ile 7 topla','status':'running',
                  'history':[],'hwnd':None,'approval':None,'pending_effect':None}
        self.plans=self.enterContext(patch.object(agent,'_plan',side_effect=[action(),{'op':'finish','expect':action()['expect'],'message':'19'}]))

    def run_job(self,**kw):
        return agent.run(self.job,ui=self.ui,current=lambda:'alice',**kw)

    def test_deny_never_sends_and_audits_actual_control_and_process(self):
        self.decide.return_value={'decision':'deny','reason':'Bu işlem kapalı.'}
        self.run_job()
        self.assertEqual(self.ui.calls,[])
        self.assertEqual(self.job['status'],'blocked')
        self.assertIn('Bu işlem kapalı',self.job['message'])
        self.classify.assert_called_with('desktop','Topla','calculatorapp')
        self.audit.assert_called_with('alice','deny','local_reversible','calculatorapp','desktop','Bu işlem kapalı.')

    def test_ask_uses_existing_bound_approval_and_resume_rechecks_gate(self):
        self.decide.return_value={'decision':'ask','reason':'Onay gerekli.'}
        self.run_job()
        self.assertEqual(self.ui.calls,[])
        self.assertEqual(self.job['status'],'approval')
        pending=copy.deepcopy(self.job['approval'])
        self.assertEqual(pending['action'],action())
        self.assertIn('digest',pending)
        self.run_job(approval=pending['id'])
        self.assertEqual(len(self.ui.calls),1)
        self.assertEqual(self.job['status'],'done')
        self.assertGreaterEqual(self.decide.call_count,2)

    def test_deny_after_approval_does_not_replay(self):
        self.decide.return_value={'decision':'ask','reason':'Onay gerekli.'}
        self.run_job(); token=self.job['approval']['id']
        self.decide.return_value={'decision':'deny','reason':'İzin geri alındı.'}
        self.run_job(approval=token)
        self.assertEqual(self.ui.calls,[])
        self.assertEqual(self.job['status'],'blocked')

    def test_allow_preserves_readback_and_completion(self):
        self.run_job()
        self.assertEqual(self.job['status'],'done')
        self.assertEqual(len(self.ui.calls),1)
        self.assertTrue(self.job['history'][0]['verified'])
        self.audit.assert_called()

    def test_gate_and_audit_exceptions_fail_closed(self):
        for component in (self.decide,self.audit):
            with self.subTest(component=component):
                self.job.update(history=[],approval=None,pending_effect=None,hwnd=None,pid=None,app_pid=None,status='running')
                self.plans.side_effect=[action()]
                component.side_effect=RuntimeError('PRIVATE')
                self.run_job()
                self.assertEqual(self.ui.calls,[])
                self.assertEqual(self.job['status'],'blocked')
                self.failure.assert_called()
                self.assertNotIn('PRIVATE',self.job['message'])
                component.side_effect=None

    def test_legacy_approval_is_not_weakened_by_allow(self):
        self.ui.screen['controls'][1]['name']='Sil'
        self.run_job()
        self.assertEqual(self.job['status'],'approval')
        self.assertEqual(self.ui.calls,[])

    def test_clear_action_also_passes_gate_before_sending(self):
        self.decide.return_value={'decision':'deny','reason':'Kapalı.'}
        with patch.object(agent,'_clear_step',return_value=action()):
            self.run_job()
        self.assertEqual(self.ui.calls,[])
        self.audit.assert_called()

    def test_malformed_decision_is_closed(self):
        self.decide.return_value={'decision':'unexpected','reason':'x'}
        self.run_job()
        self.assertEqual(self.ui.calls,[])
        self.assertEqual(self.job['status'],'blocked')
