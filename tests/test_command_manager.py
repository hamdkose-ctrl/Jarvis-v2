import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from modules.command_manager import CommandContext, dispatch, engine_control
from modules.session_state import SessionState
from modules import app_actions, smart_router, system_doctor, task_agents, pc_guide, developer, chat_translation


class CommandManagerTests(unittest.TestCase):
    def test_explicit_desktop_cancel_bypasses_pending_action_and_model(self):
        from modules import desktop_agent
        context = self.context('alice'); context.session.pending_desktop = True
        context.session.pending_action = object()
        with patch.object(desktop_agent, 'handle', return_value='iptal edildi') as cancel, \
             patch.object(desktop_agent, 'awaiting', return_value=False), \
             patch.object(app_actions, 'continue_voice') as pending, patch.object(smart_router, 'handle') as router:
            self.assertEqual(dispatch(context, 'pc görev iptal', 'pc görev iptal'), 'iptal edildi')
        cancel.assert_called_once_with('alice', 'pc görev iptal', context.emit, current=context.pc_owner, source=context.source)
        self.assertIsNone(context.session.pending_desktop)
        pending.assert_not_called(); router.assert_not_called()
    def test_continue_routes_to_owned_desktop_job_and_pauses_multi_step(self):
        from modules import desktop_agent
        context=self.context('alice'); context.session.pending_desktop=True
        with patch.object(smart_router,'handle',return_value=None), patch.object(system_doctor,'handle',return_value=None), patch.object(task_agents,'handle',return_value=None), patch.object(pc_guide,'handle',return_value=None), patch.object(developer,'handle',return_value=None), patch.object(desktop_agent,'handle',return_value='doğrulama bekliyor') as run, patch.object(desktop_agent,'awaiting',return_value=True):
            self.assertEqual(dispatch(context,'devam et','devam et'), 'doğrulama bekliyor')
        self.assertEqual(run.call_args.args[:2], ('alice','PC görevi devam'))
        from modules.command_manager import awaiting_input
        self.assertTrue(awaiting_input(context.session))
    def context(self, owner='alice'):
        return CommandContext(SimpleNamespace(slug=owner),SessionState(),Mock(),Mock(),Mock(return_value=[]),Mock(),Mock(return_value=None))

    def test_pending_user_approval_precedes_model_and_developer(self):
        context=self.context();context.session.pending_action=object()
        with patch.object(app_actions,'continue_voice',return_value='onay'),patch.object(smart_router,'handle') as router:
            self.assertEqual(dispatch(context,'evet','evet'),'onay');router.assert_not_called()

    def test_development_followups_precede_translation_and_keep_session_owner(self):
        context=self.context('bob')
        with patch.object(smart_router,'handle',return_value=None),patch.object(system_doctor,'handle',return_value=None),patch.object(task_agents,'handle',return_value=None),patch.object(pc_guide,'handle',return_value=None),patch.object(developer,'handle',return_value='taslak') as edit,patch.object(chat_translation,'resolve') as translate:
            self.assertEqual(dispatch(context,'bunu değiştir','bunu değiştir'),'taslak')
            self.assertEqual(edit.call_args.args[0],'bob');translate.assert_not_called()
            self.assertEqual(context.session.speech_override,'Geliştirme sonucu sohbet ekranında hazır.')

    def test_pc_guidance_keeps_priority_and_full_profile(self):
        context = self.context('bob')
        with patch.object(smart_router, 'handle', return_value=None), patch.object(system_doctor, 'handle', return_value=None), patch.object(task_agents, 'handle', return_value=None), patch.object(pc_guide, 'handle', return_value='adım') as guide, patch.object(developer, 'handle') as edit:
            self.assertEqual(dispatch(context, 'yardım et', 'yardım et'), 'adım')
            guide.assert_called_once_with(context.profile, 'yardım et')
            edit.assert_not_called()


class EngineControlTests(unittest.TestCase):
    def test_close_jarvis_bypasses_guides_but_not_pc_shutdown(self):
        close, sleep = Mock(return_value='kapatılıyor'), Mock()
        for command in ("jarvis'i kapat", 'jarvis’i kapat', 'kendini kapat'):
            self.assertEqual(engine_control(command, source='ses', sleeping=False, close=close, set_sleep=sleep), 'kapatılıyor')
        self.assertIsNone(engine_control('bilgisayarı kapat', source='ses', sleeping=False, close=close, set_sleep=sleep))
        self.assertEqual(close.call_count, 3)
        sleep.assert_not_called()

    def test_phone_cannot_close_pc_engine(self):
        close = Mock()
        reply = engine_control('jarvis kapat', source='telefon', sleeping=False, close=close, set_sleep=Mock())
        self.assertIn('bilgisayarından', reply)
        close.assert_not_called()

    def test_sleep_and_wake_use_existing_engine_flags(self):
        sleep = Mock(return_value='uyandı')
        self.assertEqual(engine_control('uyan', source='ses', sleeping=True, close=Mock(), set_sleep=sleep), 'uyandı')
        sleep.assert_called_once_with(False, announce=False)
        self.assertIsNone(engine_control('uyan', source='ses', sleeping=False, close=Mock(), set_sleep=sleep))

    def test_pending_approval_does_not_import_unneeded_development_modules(self):
        import builtins
        context = CommandManagerTests().context()
        context.session.pending_action = object()
        original = builtins.__import__
        def import_checked(name, globals=None, locals=None, fromlist=(), level=0):
            if name == 'modules' and any(x in fromlist for x in ('developer', 'pc_guide', 'task_agents')):
                raise AssertionError('Approval should not import unrelated handlers')
            return original(name, globals, locals, fromlist, level)
        with patch.object(app_actions, 'continue_voice', return_value='onay'), patch('builtins.__import__', side_effect=import_checked):
            self.assertEqual(dispatch(context, 'evet', 'evet'), 'onay')
