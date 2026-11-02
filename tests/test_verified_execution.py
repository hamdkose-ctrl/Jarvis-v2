"""Evidence, ambiguity and conversation ownership without a Windows machine."""
import sys
import types
import time
import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

if 'pyautogui' not in sys.modules:
    stub = types.ModuleType('pyautogui')
    stub.__getattr__ = lambda _: MagicMock()
    sys.modules['pyautogui'] = stub

from modules import system_control as pc, command_execution, requests_state
from modules.session_state import SessionState


def user_context(case):
    """Yerel işlem testleri açık kullanıcı ve geçici kayıtlarla çalışır."""
    from modules import llm, pc_contracts, permission_audit, permission_policy
    td = tempfile.TemporaryDirectory(); case.addCleanup(td.cleanup)
    root = Path(td.name)
    token = llm._key_context.set('alice'); case.addCleanup(llm._key_context.reset, token)
    token = requests_state._current.set(None); case.addCleanup(requests_state._current.reset, token)
    for module, key, value in ((pc_contracts, 'ROOT', root / 'pc'),
                               (permission_policy, 'ROOT', root / 'policy'),
                               (permission_audit, 'DATA_DIR', root)):
        case.enterContext(patch.object(module, key, value))


class ApplicationEvidenceTests(unittest.TestCase):
    def setUp(self):
        user_context(self)

    def test_calculator_aliases_select_uwp_frame(self):
        windows = [(2034606, 'Hesap Makinesi', 'applicationframehost'),
                   (9, 'Calculator - Chrome', 'chrome'), (10, 'Ayarlar', 'applicationframehost')]
        for name in ('Hesap Makinesi', 'hesap makinesini', 'Hesap Makinesi uygulaması',
                     'calc', 'calculator', 'calculatorapp'):
            with self.subTest(name=name):
                self.assertEqual(pc._select_window(name, windows), [windows[0]])
                self.assertEqual(pc.APPS[pc.find_app(name)], 'calc')

    def test_calculator_frame_requires_native_child_identity(self):
        with patch.object(pc, '_app_windows', return_value=[(1, 'Hesap Makinesi', 'applicationframehost')]), \
             patch('modules.desktop_uia._call') as native:
            native.return_value = {'app': 'applicationframehost', 'app_pid': 3}
            self.assertIsNone(pc._visible_application('hesap makinesi'))
            native.return_value = {'app': 'calculatorapp', 'app_pid': 11548}
            self.assertEqual(pc._visible_application('hesap makinesi'), 1)
            native.assert_called_with({'op': 'observe', 'hwnd': 1})
            native.side_effect = ValueError('unavailable')
            self.assertIsNone(pc._visible_application('hesap makinesi'))
            native.side_effect = requests_state.Cancelled('stop')
            with self.assertRaises(requests_state.Cancelled):
                pc._visible_application('hesap makinesi')

    def test_calculator_title_in_browser_is_not_launch_evidence(self):
        with patch.object(pc, '_app_windows', return_value=[(1, 'Hesap Makinesi', 'chrome')]), \
             patch('modules.desktop_uia._call') as native:
            self.assertIsNone(pc._visible_application('calc'))
            native.assert_not_called()

    def test_launch_with_no_window_is_not_verified(self):
        with patch.object(pc.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0)), \
             patch.object(pc, '_app_windows', return_value=[]), patch.object(pc.time, 'sleep'):
            result = pc.open_application('paint')
        self.assertFalse(result.ok)
        self.assertIn('doğrulayamadım', result)

    def test_verified_open_window_is_reused_without_second_launch(self):
        with patch.object(pc, '_visible_application', return_value=77), \
             patch.object(pc.subprocess, 'run') as launch:
            result = pc.open_application('paint')
        self.assertTrue(result.ok)
        self.assertIn('zaten açık', result)
        launch.assert_not_called()

    def test_native_window_confirms_launch(self):
        with patch.object(pc.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0)), \
             patch.object(pc, '_app_windows', return_value=[(1, 'Adsız - Paint', 'mspaint')]):
            self.assertTrue(pc.open_application('paint').ok)

    def test_existing_verified_window_does_not_depend_on_a_new_launch(self):
        with patch.object(pc.subprocess, 'run', return_value=types.SimpleNamespace(returncode=1)) as launch, \
             patch.object(pc, '_app_windows', return_value=[(1, 'Paint', 'mspaint')]) as windows:
            result = pc.open_application('paint')
        self.assertTrue(result.ok)
        windows.assert_called()
        launch.assert_not_called()

    def test_browser_title_is_not_native_application_evidence(self):
        with patch.object(pc, '_app_windows', return_value=[(1, 'Spotify - Google Chrome', 'chrome')]):
            self.assertIsNone(pc._visible_application('Spotify'))

    def test_ambiguous_prefix_returns_choices_without_launching(self):
        installed = {'visual studio code': ('Visual Studio Code', 'appid', 'a'),
                     'visual studio community': ('Visual Studio Community', 'appid', 'b')}
        with patch.object(pc, 'installed_apps', return_value=installed), patch.object(pc.subprocess, 'Popen') as launch:
            result = pc.open_application('visual studio')
        self.assertFalse(result.ok)
        self.assertEqual(set(result.candidates), {'Visual Studio Code', 'Visual Studio Community'})
        launch.assert_not_called()

    def test_cancel_propagates_during_verification(self):
        with patch.object(pc.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0)), \
             patch.object(requests_state, 'check', side_effect=requests_state.Cancelled('stop')):
            with self.assertRaises(requests_state.Cancelled):
                pc.open_application('paint')


class ConversationExecutionTests(unittest.TestCase):
    def runtime(self, session):
        return types.SimpleNamespace(_session=lambda: session,
            system_control=types.SimpleNamespace(open_application=Mock(return_value=pc.ApplicationResult('açık', ok=True))))

    def test_selected_app_uses_owned_list_and_new_request_clears_it(self):
        alice, bob = SessionState(), SessionState()
        alice.pending_app = {'choices': ('Paint', 'Paint 3D'), 'at': time.monotonic()}
        self.assertIsNone(command_execution.continue_app(self.runtime(bob), '2'))
        runtime = self.runtime(alice)
        self.assertTrue(command_execution.continue_app(runtime, '2').ok)
        runtime.system_control.open_application.assert_called_once_with('Paint 3D')
        alice.pending_app = {'choices': ('Paint',), 'at': time.monotonic()}
        self.assertIsNone(command_execution.continue_app(runtime, 'hava nasıl'))
        self.assertIsNone(alice.pending_app)

    def test_old_choice_expires_without_launch(self):
        session = SessionState(pending_app={'choices': ('Paint',), 'at': time.monotonic()-121})
        runtime = self.runtime(session)
        self.assertIsNone(command_execution.continue_app(runtime, '1'))
        runtime.system_control.open_application.assert_not_called()

    def test_prior_target_and_pending_question_reach_the_active_context(self):
        # Eski engine_tools.route bu iki sinyali modele verir ve modeli beklerken oturum
        # durumunu tüketirdi. Canonical gözlem onları provenance ile taşır; bekleyen isteği
        # tüketmez, çünkü kararı model değil exact state gate verir.
        from modules import brain_context
        session = SessionState(last_command='raporu düzelt',
                               pending_request={'command': 'bunu iyi yap', 'question': 'Hangi rapor?'})
        store = types.SimpleNamespace(_states={'alice': session}, _lock=None)
        context = brain_context.build_active_context(
            owner='alice', request_id='r', session_store=store,
            history_reader=lambda owner, limit: [{'id': 't1', 'owner': owner, 'role': 'assistant',
                                                  'text': 'Pompa raporu hazır'}],
            history_filter=lambda owner, rows: list(rows),
            goal_reader=lambda owner: None, goal_is_open=lambda goal: False)
        pending = {ref.id: ref.provenance for ref in context.pending_references}
        self.assertEqual(pending['pending_request']['value'],
                         {'command': 'bunu iyi yap', 'question': 'Hangi rapor?'})
        recent = {ref.id: ref.provenance for ref in context.recent_references
                  if ref.source == 'session_state'}
        self.assertEqual(recent['last_command']['text'], 'raporu düzelt')
        self.assertIn('Pompa raporu hazır', [ref.provenance['text'] for ref in context.recent_references
                                             if ref.source == 'history'])
        self.assertIsNotNone(session.pending_request)


if __name__ == '__main__':
    unittest.main()
