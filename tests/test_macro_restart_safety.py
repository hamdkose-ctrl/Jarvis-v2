import engine_source
"""Macro control and restart failures; no real desktop or process mutations."""
import ast
import os
from pathlib import Path
import re
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from modules import main_planner, requests_state
from modules.command_manager import PENDING_INPUT_FIELDS
from modules.session_state import SessionState

ROOT = Path(__file__).resolve().parents[1]


class Ambiguous(str):
    """open_app'in seçim bekleyen deterministic açma yanıtı: metin + candidates."""
    candidates = ('Chrome', 'Edge')


class MacroControlTests(unittest.TestCase):
    """Kaydedilmiş kısayol adımı ikinci kez yorumlanmaz: adlandırılmış açma eylemi kendi deterministic sahibine gider."""

    def runtime(self):
        session = SessionState()
        runtime = SimpleNamespace(profile=SimpleNamespace(slug='hamdi', data={'macros': {'başla': {'title': 'başla', 'actions': ['ilk', 'ikinci']}}}), _session=lambda: session, re=re, _macro_key=lambda text: text, _VERB_END=re.compile('(?!)'), requests_state=SimpleNamespace(check=Mock()), flags={}, stop_event=threading.Event(), handle=Mock(side_effect=AssertionError('kısayol adımı yeniden yorumlanamaz')), time=SimpleNamespace(sleep=Mock()),
            system_control=SimpleNamespace(find_app=lambda base: base, open_application=Mock(side_effect=lambda name: name + ' açıldı')))
        return runtime, session

    def test_every_pending_input_stops_macro_and_displays_its_question(self):
        for field in PENDING_INPUT_FIELDS:
            with self.subTest(field=field):
                runtime, session = self.runtime()
                def launch(name):
                    setattr(session, field, True if field == 'pending_weather_location' else 'waiting')
                    return Ambiguous('Bu işlemi onaylıyor musun?')
                runtime.system_control.open_application.side_effect = launch
                result = main_planner._macro_run(runtime, 'başla')
                self.assertEqual(runtime.system_control.open_application.call_count, 1)
                self.assertIn('Bu işlemi onaylıyor musun?', result)
                self.assertIn('kalan adımlarını çalıştırmadım', result)
                self.assertFalse(session._in_macro)

    def test_user_change_stops_macro_and_cleans_original_flag(self):
        runtime, original = self.runtime()
        target = SessionState()
        def switch(name):
            runtime.profile = SimpleNamespace(slug='ebru')
            runtime._session = lambda: target
            return 'Ebru’ya geçtim.'
        runtime.system_control.open_application.side_effect = switch
        self.assertIn('Kullanıcı değişti', main_planner._macro_run(runtime, 'başla'))
        runtime.handle.assert_not_called()
        self.assertEqual(runtime.system_control.open_application.call_count, 1)
        self.assertFalse(original._in_macro)
        self.assertFalse(target._in_macro)

    def test_cancellation_after_first_action_prevents_next_action(self):
        runtime, session = self.runtime()
        runtime.requests_state.check.side_effect = [None, requests_state.Cancelled('iptal')]
        with self.assertRaises(requests_state.Cancelled):
            main_planner._macro_run(runtime, 'başla')
        self.assertEqual(runtime.system_control.open_application.call_count, 1)
        self.assertFalse(session._in_macro)

    def test_closing_during_first_action_prevents_next_action(self):
        runtime, session = self.runtime()
        def close(name):
            runtime.flags['closing'] = True
            return 'Jarvis kapanıyor.'
        runtime.system_control.open_application.side_effect = close
        self.assertIn('kalan adımlarını çalıştırmadım', main_planner._macro_run(runtime, 'başla'))
        self.assertEqual(runtime.system_control.open_application.call_count, 1)
        self.assertFalse(session._in_macro)

    def test_exact_macro_name_wins_over_suffix_fallback(self):
        runtime, session = self.runtime()
        runtime.profile.data['macros'] = {
            'notu': {'title': 'notu', 'actions': ['doğru']},
            'not': {'title': 'not', 'actions': ['yanlış']},
        }
        main_planner._macro_run(runtime, 'notu')
        runtime.system_control.open_application.assert_called_once_with('doğru')

    def test_completed_macro_reports_run_actions_and_waits_only_between_them(self):
        runtime, session = self.runtime()
        result = main_planner._macro_run(runtime, 'başla')
        self.assertEqual([c.args[0] for c in runtime.system_control.open_application.call_args_list], ['ilk', 'ikinci'])
        self.assertIn('ilk, ikinci', result)
        runtime.time.sleep.assert_called_once_with(0.4)
        runtime.handle.assert_not_called()
        self.assertFalse(session._in_macro)

    def test_an_action_that_is_not_an_app_launch_is_refused_not_interpreted(self):
        runtime, session = self.runtime()
        runtime.profile.data['macros'] = {'başla': {'title': 'başla', 'actions': ['sesi kıs']}}
        runtime.system_control.find_app = Mock(return_value=None)
        result = main_planner._macro_run(runtime, 'başla')
        self.assertIn('sesi kıs', result)
        runtime.system_control.open_application.assert_not_called()
        runtime.handle.assert_not_called()
        self.assertFalse(session._in_macro)


class RestartFailureTests(unittest.TestCase):
    def restart(self, namespace):
        from modules.deferred import start
        namespace['_defer'] = lambda seconds, callback: start(seconds, callback, timer_factory=namespace['threading'].Timer)
        tree = ast.parse((ROOT / 'web.py').read_text(encoding='utf-8'))
        bridge = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Bridge')
        method = next(n for n in bridge.body if isinstance(n, ast.FunctionDef) and n.name == 'restart')
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), 'real-bridge-restart', 'exec'), namespace)
        return lambda: namespace['restart'](object())

    def namespace(self):
        return {'engine': SimpleNamespace(log=Mock()), 'os': os, 'sys': SimpleNamespace(executable='current-python'), 'Path': Path, '__file__': str(ROOT / 'web.py'), 'subprocess': SimpleNamespace(Popen=Mock()), 'hub': Mock(), 'threading': SimpleNamespace(Timer=Mock()), '_shutdown': Mock(), '_close_windows': Mock(), 'time': Mock()}

    def test_spawn_failure_leaves_current_window_and_process_running(self):
        ns = self.namespace();ns['subprocess'].Popen.side_effect = OSError('spawn failed')
        self.assertFalse(self.restart(ns)())
        ns['hub'].publish.assert_not_called()
        ns['_close_windows'].assert_not_called()
        ns['_shutdown'].assert_not_called()
        ns['threading'].Timer.assert_not_called()

    def test_success_clears_old_boot_markers_then_schedules_shutdown(self):
        ns = self.namespace()
        with patch.dict(os.environ, {'JARVIS_BOOT_MARKERS': 'old-markers', 'JARVIS_BOOT_ID': 'old-id'}):
            self.assertTrue(self.restart(ns)())
        args, kwargs = ns['subprocess'].Popen.call_args
        self.assertEqual(args[0], ['current-python', str(ROOT / 'launcher.py')])
        self.assertNotIn('JARVIS_BOOT_ID', kwargs['env'])
        self.assertNotIn('JARVIS_BOOT_MARKERS', kwargs['env'])
        self.assertEqual(kwargs['cwd'], str(ROOT))
        ns['hub'].publish.assert_called_once_with('quit')
        ns['threading'].Timer.call_args.args[1]()
        ns['_shutdown'].assert_called_once_with(close_windows=False, reason='yeniden başlatma')


class CloseChainTests(unittest.TestCase):
    def function(self, name, ns):
        tree = engine_source.tree()
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), 'real-chain-control', 'exec'), ns)
        return ns[name]

    def test_close_marks_intent_before_delayed_exit(self):
        ns = {'flags': {}, 'emit': Mock(), 'threading': SimpleNamespace(Timer=Mock()), 'stop_event': threading.Event()}
        self.function('_close_jarvis', ns)()
        self.assertTrue(ns['flags']['closing'])
        self.assertFalse(ns['stop_event'].is_set())

    def test_multistep_chain_never_runs_a_delayed_close_step(self):
        session = SessionState();flags = {}
        ns = {'flags': flags, 'stop_event': threading.Event(), '_session': lambda: session, 'profile': SimpleNamespace(slug='hamdi'),
              'handle': Mock(side_effect=AssertionError('adım ikinci kez yorumlanamaz')), 'privacy': SimpleNamespace(audit=Mock())}
        result = self.function('_run_steps', ns)(['jarvis kapat', 'ikinci işlem'])
        ns['handle'].assert_not_called()
        self.assertIn('ikinci işlem', result)
        self.assertNotIn('closing', flags)
        self.assertFalse(ns['stop_event'].is_set())
        self.assertFalse(session._in_multi)
