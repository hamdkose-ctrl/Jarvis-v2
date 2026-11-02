"""Operation validation, confirmations and native target verification without hardware access."""
import inspect
import sys
import types
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch, MagicMock
from modules import app_actions as actions
from modules.session_state import SessionState

class ActionTests(unittest.TestCase):
    def setUp(self):
        self.p=types.SimpleNamespace(slug='alice',data={'tasks':[{'id':3,'text':'Pompa'}],'items':[]})
        self.b=Mock();self.state=SessionState();self.events=[]
        self.emit=lambda *args:self.events.append(args)
    @contextmanager
    def owned(self,p):yield self.b
    def test_schema_rejects_unknown_methods_secrets_types_and_extra_fields(self):
        for action,params in [('send',{'text':'x'}),('settings_save',{'data':{'api_key':'secret'}}),
                              ('task_delete',{'tid':True}),('task_add',{'text':'x','shell':'whoami'}),
                              ('set_flag',{'name':'mic','value':'false'}),('nx_set',{'key':'nx_theme','value':'banana'})]:
            with self.assertRaises(ValueError):actions.run(self.b,self.p,action,params,confirmed=True)
        self.assertEqual(self.b.mock_calls,[])
    def test_confirmation_value_must_be_a_real_boolean(self):
        with self.assertRaises(ValueError):actions.run(self.b,self.p,'task_delete',{'tid':3},confirmed='false')
        self.b.task_delete.assert_not_called()
    def test_pc_fast_paths_do_not_require_an_llm(self):
        # Canonical kapı: Understanding niyeti üretir, Core argümanı doğrular; model çağrısı yok.
        from modules import brain_core_map, brain_understanding, llm
        from modules.brain_contracts import ActiveContext

        def decide(text):
            semantic=brain_understanding.understand(owner='alice',request_id='r',text=text,
                active_context=ActiveContext(owner='alice',request_id='r'),candidates=(),references=())
            return brain_core_map.core_plan(semantic.capability_hint,semantic.arguments)

        with patch.object(llm,'ask',Mock(side_effect=AssertionError('Model çağrısı gereksiz'))):
            self.assertEqual(decide('Açık pencereleri listele'),('app_action',{'action':'pc_windows','params':{}}))
            # Hedef küçük harfe indirgenir; yürütücü (system_control._select_window) zaten kendi
            # normalleştiricisiyle eşleştirdiği için pencere başlığındaki büyük harf yeteneği düşürmez.
            self.assertEqual(decide('Plan – Chrome penceresini öne getir'),('app_action',{'action':'pc_window',
                'params':{'target':'plan – chrome','action':'focus'}}))
    def test_confirmation_does_not_execute_until_exact_reply(self):
        with patch.object(actions,'_owned',self.owned):
            reply=actions.voice({'action':'task_delete','params':{'tid':3}},self.state,self.p,self.emit,'Pompa görevini sil')
            self.assertIn('Onaylıyor',reply);self.b.task_delete.assert_not_called()
            self.b.task_delete.return_value=True
            actions.continue_voice('evet',self.state,self.p,self.emit)
            self.b.task_delete.assert_called_once_with(tid=3)
            self.assertIsNone(self.state.pending_action)
            self.assertEqual(self.events,[('action','task_delete')])
    def test_cancel_expire_owner_and_different_request_do_not_execute(self):
        for reply,owner,expires in [('iptal','alice',10**12),('evet','bob',10**12),('evet','alice',0),('evet deme','alice',10**12)]:
            self.state.pending_action={'action':'task_delete','params':{'tid':3},'owner':owner,'expires':expires}
            with patch.object(actions,'_owned',self.owned):actions.continue_voice(reply,self.state,self.p,self.emit)
            self.assertIsNone(self.state.pending_action)
        self.b.task_delete.assert_not_called()
    def test_deleted_or_other_users_reference_is_rejected_at_confirmation(self):
        with self.assertRaises(ValueError):actions.run(self.b,self.p,'task_delete',{'tid':42},confirmed=True)
        self.b.task_delete.assert_not_called()
    def test_mic_off_and_learning_off_are_real_state_success(self):
        self.b.set_flag.return_value={'mic':False,'speak':True}
        result=actions.run(self.b,self.p,'set_flag',{'name':'mic','value':False})
        self.assertTrue(result['ok']);self.b.set_flag.assert_called_once_with(name='mic',value=False)
        self.b.learn_toggle.return_value=False
        self.assertTrue(actions.run(self.b,self.p,'learn_toggle',{'on':False})['ok'])
    def test_failure_is_reported_and_not_emitted_as_success(self):
        self.b.widget_set.return_value=False
        with patch.object(actions,'_owned',self.owned):
            reply=actions.voice({'action':'widget_set','params':{'on':True}},self.state,self.p,self.emit)
        self.assertIn('tamamlanamadı',reply);self.assertEqual(self.events,[])
    def test_missing_information_keeps_original_request_for_next_turn(self):
        with patch.object(actions,'_owned',self.owned):
            actions.voice({'question':'Hangi görev?'},self.state,self.p,self.emit,'Görevi sil')
        self.assertEqual(self.state.pending_action['command'],'Görevi sil')
        actions.continue_voice('iptal',self.state,self.p,self.emit)
        self.assertIsNone(self.state.pending_action)

class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if 'pyautogui' not in sys.modules:
            m=types.ModuleType('pyautogui');m.__getattr__=lambda _:MagicMock();sys.modules['pyautogui']=m
        from modules import system_control
        cls.pc=system_control
    def setUp(self):
        self.api=Mock();self.api.IsWindow.return_value=True;self.api.IsIconic.return_value=False
        self.api.IsZoomed.return_value=False;self.api.GetForegroundWindow.return_value=999
        self.windows=[(101,'Plan – Chrome','chrome'),(102,'Mail – Chrome','chrome')]
    def test_ambiguity_never_changes_a_window(self):
        with patch.object(self.pc,'_window_api',return_value=self.api),patch.object(self.pc,'_app_windows',return_value=self.windows):
            result=self.pc.window_action('chrome','focus')
        self.assertTrue(result['needs_clarification']);self.api.SetForegroundWindow.assert_not_called()
    def test_exact_title_focus_success_and_denial(self):
        with patch.object(self.pc,'_window_api',return_value=self.api),patch.object(self.pc,'_app_windows',return_value=self.windows),patch.object(self.pc.time,'sleep'):
            self.assertFalse(self.pc.window_action('Plan – Chrome','focus')['ok'])
            self.api.GetForegroundWindow.return_value=101
            self.assertTrue(self.pc.window_action('Plan – Chrome','focus')['ok'])
        self.api.SetForegroundWindow.assert_called_with(101)
    def test_lost_focus_prevents_keyboard_input(self):
        with patch.object(self.pc,'window_action',return_value={'ok':True,'title':'Plan','hwnd':101}),patch.object(self.pc,'_window_api',return_value=self.api),patch.object(self.pc.pyautogui,'hotkey') as key:
            self.assertFalse(self.pc.window_shortcut('Plan','save')['ok']);key.assert_not_called()
    def test_native_state_not_showwindow_return_verifies_minimize(self):
        with patch.object(self.pc,'_window_api',return_value=self.api),patch.object(self.pc,'_app_windows',return_value=self.windows),patch.object(self.pc.time,'sleep'):
            self.api.ShowWindow.return_value=True
            self.assertFalse(self.pc.window_action('Plan – Chrome','minimize')['ok'])
            self.api.IsIconic.return_value=True
            self.assertTrue(self.pc.window_action('Plan – Chrome','minimize')['ok'])

if __name__=='__main__':unittest.main()
