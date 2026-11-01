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


class _Reply:
    """run_step'in adım geri bildirimi; _macro_run yalnız result_status'a bakar."""

    def __init__(self, result_status='handled'):
        self.result_status = result_status


class MacroControlTests(unittest.TestCase):
    """Kısayolun her adımı KENDİ canonical kararıyla çalışır; ham adım ne `runtime.handle` ne eski zincir."""

    def runtime(self):
        session = SessionState()
        runtime = SimpleNamespace(profile=SimpleNamespace(slug='hamdi', data={'macros': {'başla': {'title': 'başla', 'actions': ['ilk', 'ikinci']}}}), _session=lambda: session, re=re, _macro_key=lambda text: text, _VERB_END=re.compile('(?!)'), requests_state=SimpleNamespace(check=Mock()), flags={}, stop_event=threading.Event(), handle=Mock(side_effect=AssertionError('kısayol adımı ikinci kez yorumlanamaz')), time=SimpleNamespace(sleep=Mock()),
            system_control=SimpleNamespace(find_app=Mock(side_effect=AssertionError('kısayol adımı kendi kararını kendisi açmaz')), open_application=Mock(side_effect=AssertionError('kısayol adımı doğrudan uygulama açamaz'))))
        return runtime, session

    def drive(self, runtime, command, step):
        """run_step'i tek noktadan taklit eder; kısayol yalnız envelope üzerinden ilerler."""
        calls = []
        def envelope(_runtime, text):
            calls.append((_runtime, text))
            return (step(text), _Reply())
        with patch('modules.brain_entry.run_step', side_effect=envelope):
            return calls, main_planner._macro_run(runtime, command)

    def test_every_pending_input_stops_macro_and_displays_its_question(self):
        for field in PENDING_INPUT_FIELDS:
            with self.subTest(field=field):
                runtime, session = self.runtime()
                def step(text):
                    setattr(session, field, True if field == 'pending_weather_location' else 'waiting')
                    return 'Bu işlemi onaylıyor musun?'
                calls, result = self.drive(runtime, 'başla', step)
                self.assertEqual([row[1] for row in calls], ['ilk'])
                self.assertIn('Bu işlemi onaylıyor musun?', result)
                self.assertIn('kalan adımlarını çalıştırmadım', result)
                self.assertFalse(session._in_macro)

    def test_user_change_stops_macro_and_cleans_original_flag(self):
        runtime, original = self.runtime()
        target = SessionState()
        def step(text):
            runtime.profile = SimpleNamespace(slug='ebru')
            runtime._session = lambda: target
            return 'Ebru’ya geçtim.'
        calls, result = self.drive(runtime, 'başla', step)
        self.assertIn('Kullanıcı değişti', result)
        self.assertEqual([row[1] for row in calls], ['ilk'])
        runtime.handle.assert_not_called()
        self.assertFalse(original._in_macro)
        self.assertFalse(target._in_macro)

    def test_cancellation_after_first_action_prevents_next_action(self):
        runtime, session = self.runtime()
        runtime.requests_state.check.side_effect = [None, requests_state.Cancelled('iptal')]
        with patch('modules.brain_entry.run_step', return_value=('Tamam.', _Reply())) as step:
            with self.assertRaises(requests_state.Cancelled):
                main_planner._macro_run(runtime, 'başla')
        step.assert_called_once_with(runtime, 'ilk')
        self.assertFalse(session._in_macro)

    def test_closing_during_first_action_prevents_next_action(self):
        runtime, session = self.runtime()
        def step(text):
            runtime.flags['closing'] = True
            return 'Jarvis kapanıyor.'
        calls, result = self.drive(runtime, 'başla', step)
        self.assertIn('kalan adımlarını çalıştırmadım', result)
        self.assertEqual([row[1] for row in calls], ['ilk'])
        self.assertFalse(session._in_macro)

    def test_exact_macro_name_wins_over_suffix_fallback(self):
        runtime, session = self.runtime()
        runtime.profile.data['macros'] = {
            'notu': {'title': 'notu', 'actions': ['doğru']},
            'not': {'title': 'not', 'actions': ['yanlış']},
        }
        calls, _result = self.drive(runtime, 'notu', lambda text: text + ' bitti')
        self.assertEqual([row[1] for row in calls], ['doğru'])

    def test_completed_macro_reports_run_actions_and_waits_only_between_them(self):
        runtime, session = self.runtime()
        calls, result = self.drive(runtime, 'başla', lambda text: text + ' bitti')
        self.assertEqual([row[1] for row in calls], ['ilk', 'ikinci'])
        self.assertTrue(all(row[0] is runtime for row in calls))
        self.assertIn('ilk, ikinci', result)
        self.assertNotIn('bitti', result)  # Aggregate reply is the summary, not one action's speech.
        runtime.time.sleep.assert_called_once_with(0.4)
        runtime.handle.assert_not_called()
        runtime.system_control.open_application.assert_not_called()
        self.assertFalse(session._in_macro)

    def test_an_action_that_is_not_an_app_launch_still_gets_the_canonical_envelope(self):
        runtime, session = self.runtime()
        runtime.profile.data['macros'] = {'başla': {'title': 'başla', 'actions': ['sesi kıs']}}
        calls, result = self.drive(runtime, 'başla', lambda text: text + ' bitti')
        self.assertEqual([row[1] for row in calls], ['sesi kıs'])
        self.assertIn('sesi kıs', result)
        runtime.handle.assert_not_called()
        runtime.system_control.find_app.assert_not_called()
        self.assertFalse(session._in_macro)

    def test_a_step_that_is_not_handled_stops_the_chain(self):
        runtime, session = self.runtime()
        calls = []
        def envelope(_runtime, text):
            calls.append(text)
            return ('Hangi uygulamayı?', _Reply('needs_input'))
        with patch('modules.brain_entry.run_step', side_effect=envelope):
            result = main_planner._macro_run(runtime, 'başla')
        self.assertEqual(calls, ['ilk'])
        self.assertIn('yanıt veya onay bekliyor', result)
        self.assertNotIn('ikinci', result)
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
              'runtime': object(),  # engine_source yalnız nitelikli kullanımları soyutlar; envelope runtime'ı argüman olarak alır.
              'handle': Mock(side_effect=AssertionError('adım ikinci kez yorumlanamaz')), 'privacy': SimpleNamespace(audit=Mock())}
        run = self.function('_run_steps', ns)
        calls = []
        def envelope(text):
            calls.append(text)
            if text == 'jarvis kapat':
                flags['closing'] = True
                return ('Jarvis kapanıyor.', _Reply())
            return ('ikinci adım bitti', _Reply())
        with patch('modules.brain_entry.run_step', side_effect=lambda _runtime, text: envelope(text)):
            result = run(['jarvis kapat', 'ikinci işlem'])
        ns['handle'].assert_not_called()
        self.assertEqual(calls, ['jarvis kapat'])
        self.assertIn('kalan adımları', result)
        self.assertNotIn('ikinci adım bitti', result)
        self.assertFalse(ns['stop_event'].is_set())
        self.assertFalse(session._in_multi)
