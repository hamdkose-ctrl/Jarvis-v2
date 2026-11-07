import engine_source
"""Cancellable background request lifetimes and keyboard boundaries, without WhatsApp."""
import concurrent.futures
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import Mock, patch
if 'pyautogui' not in sys.modules:
    keyboard_stub = ModuleType('pyautogui')
    keyboard_stub.__getattr__ = lambda name: Mock()
    sys.modules['pyautogui'] = keyboard_stub
from modules import requests_state as state, messaging
from modules.session_state import SessionState
import test_confirmation_safety as confirmation_tests


class BackgroundRequestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        for p in (patch.object(state, '_records', {}), patch.object(state, '_journal', Path(self.tmp.name) / 'requests.json')):
            p.start();self.addCleanup(p.stop)

    def test_background_remains_cancellable_after_parent_finishes(self):
        state.register('hamdi', 'parent')
        with state.activate('hamdi', 'parent'):
            self.assertTrue(state.register_background('hamdi', 'child'))
        self.assertEqual(state._records[('hamdi', 'parent')]['state'], 'done')
        state.cancel('hamdi')
        with self.assertRaises(state.Cancelled), state.activate('hamdi', 'child'):
            self.fail('Cancelled task started')

    def test_cancelled_parent_cannot_register_new_background_work(self):
        state.register('hamdi', 'parent')
        with state.activate('hamdi', 'parent'):
            state.cancel('hamdi')
            with self.assertRaises(state.Cancelled):
                state.register_background('hamdi', 'child')
        self.assertNotIn(('hamdi', 'child'), state._records)

    def test_background_cannot_borrow_another_user_request(self):
        state.register('hamdi', 'parent')
        with state.activate('hamdi', 'parent'):
            with self.assertRaises(ValueError):
                state.register_background('ebru', 'child')
        self.assertNotIn(('ebru', 'child'), state._records)

    def message(self):
        session = SessionState(pending_msg={'to': 'Ebru', 'text': 'Merhaba', 'stage': 'confirm'})
        result, ns = confirmation_tests.ConfirmationTests().message(session, 'evet gönder')
        ns['requests_state'] = state
        return result, ns

    def test_cancel_before_worker_runs_never_invokes_sender(self):
        # Build real production worker, registering through the real request module.
        from test_confirmation_safety import ROOT
        import ast, re, queue
        tree = engine_source.tree()
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_message_step')
        session = SessionState(pending_msg={'to': 'Ebru', 'text': 'Merhaba', 'stage': 'confirm'})
        owner = SimpleNamespace(slug='hamdi', data={'contacts': {'Ebru': '905551112233'}})
        adapter = Mock()
        adapter.name_matches.return_value = ['Ebru']
        adapter.contact_matches.return_value = [('Ebru', '905551112233')]
        adapter.mask_phone.return_value = '…2233'
        ns = {'_session': lambda: session, 'load_approve': lambda: True, 're': re, 'profile': owner, 'messaging': adapter, 'threading': SimpleNamespace(Thread=Mock()), 'requests_state': state, 'privacy': Mock(), '_emit_for': Mock(), 'pc_profile': lambda: owner, 'events': queue.Queue(), 'secrets': SimpleNamespace(token_hex=lambda size: 'child'), '_record_failure': Mock()}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), 'real-background-message', 'exec'), ns)
        state.register('hamdi', 'parent')
        with state.activate('hamdi', 'parent'):
            ns['_message_step']('evet', 'evet')
        state.cancel('hamdi')
        ns['threading'].Thread.call_args.kwargs['target']()
        adapter.send_whatsapp.assert_not_called()
        ns['_emit_for'].assert_called_once_with(owner, 'assistant', 'WhatsApp gönderim işlemi iptal edildi.')

    def test_background_exception_is_reported_to_captured_owner(self):
        _, ns = self.message()
        # Helper captured a mock request module for this independent error-path test.
        ns['requests_state'] = SimpleNamespace(activate=lambda *args: __import__('contextlib').nullcontext(), check=Mock(), Cancelled=state.Cancelled)
        ns['_record_failure'] = Mock()
        ns['messaging'].send_whatsapp.side_effect = OSError('send failed')
        ns['threading'].Thread.call_args.kwargs['target']()
        self.assertIn('tamamlanamadı', ns['_emit_for'].call_args.args[2])
        self.assertEqual(ns['_emit_for'].call_args.args[0].slug, 'hamdi')
        ns['_record_failure'].assert_called_once()

    def test_cancellation_while_waiting_for_keyboard_lock_does_not_send(self):
        state.register('hamdi', 'child')
        entered = threading.Event()
        def send():
            with state.activate('hamdi', 'child'):
                entered.set()
                return messaging.send_whatsapp('Ebru', 'Merhaba')
        with messaging._SEND_LOCK, patch.object(messaging, '_send_whatsapp') as adapter, concurrent.futures.ThreadPoolExecutor(1) as pool:
            future = pool.submit(send)
            self.assertTrue(entered.wait(1))
            state.cancel('hamdi')
            with self.assertRaises(state.Cancelled):
                future.result(timeout=2)
            adapter.assert_not_called()


class KeyboardBoundaryTests(unittest.TestCase):
    def adapter(self):
        return SimpleNamespace(press=Mock(), hotkey=Mock(), FailSafeException=type('FailSafe', (Exception,), {}))

    def test_missing_window_never_types_or_presses_enter(self):
        keyboard = self.adapter()
        with patch.dict(sys.modules, pyautogui=keyboard), patch.object(messaging.os, 'name', 'nt'), patch.object(messaging.os, 'startfile', create=True), patch.object(messaging, '_find_window', return_value=False), patch.object(messaging, '_wait_window', return_value=False):
            self.assertIn('penceresini bulamadım', messaging.send_whatsapp('Ebru', 'Merhaba', '905551234567'))
        keyboard.press.assert_not_called();keyboard.hotkey.assert_not_called()

    def test_a_recipient_without_a_number_never_touches_the_desktop(self):
        # Eski GUI yolu (arama kutusu + ilk sonuç + Enter) kapalıdır: numara yoksa hiçbir şey açılmaz.
        keyboard = self.adapter()
        with patch.dict(sys.modules, pyautogui=keyboard), patch.object(messaging.os, 'name', 'nt'), patch.object(messaging.os, 'startfile', create=True) as startfile, patch.object(messaging, '_find_window') as window:
            result = messaging.send_whatsapp('Ebru', 'Merhaba', None)
        self.assertIn('kayıtlı bir numara yok', result)
        startfile.assert_not_called();window.assert_not_called()
        keyboard.press.assert_not_called();keyboard.hotkey.assert_not_called()

    def test_cancel_during_phone_wait_never_presses_send(self):
        keyboard = self.adapter()
        with patch.dict(sys.modules, pyautogui=keyboard), patch.object(messaging.os, 'name', 'nt'), patch.object(messaging.os, 'startfile', create=True), patch.object(messaging, '_find_window', return_value=True), patch.object(messaging, '_pause', side_effect=state.Cancelled('cancel')):
            with self.assertRaises(state.Cancelled):
                messaging.send_whatsapp('Ebru', 'Merhaba', '905551234567')
        keyboard.press.assert_not_called()

    def test_pause_checks_cancellation_without_waiting_full_delay(self):
        with patch.object(state, 'check', side_effect=state.Cancelled('cancel')), patch.object(messaging.time, 'sleep') as sleep:
            with self.assertRaises(state.Cancelled):
                messaging._pause(10)
        sleep.assert_not_called()

    def test_two_senders_cannot_use_keyboard_concurrently(self):
        started, release, attempted = threading.Event(), threading.Event(), threading.Event()
        active, maximum = 0, 0
        lock = threading.Lock()
        class ObservedLock:
            def __init__(self):
                self.inner = threading.Lock()
                self.calls = 0
            def acquire(self, timeout):
                with lock:
                    self.calls += 1
                    if self.calls >= 2:
                        attempted.set()
                return self.inner.acquire(timeout=timeout)
            def release(self):
                self.inner.release()
        def send(*args):
            nonlocal active, maximum
            with lock: active += 1;maximum = max(maximum, active)
            started.set();release.wait(2)
            with lock: active -= 1
            return 'ok'
        with patch.object(messaging, '_SEND_LOCK', ObservedLock()), patch.object(messaging, '_send_whatsapp', side_effect=send) as adapter, concurrent.futures.ThreadPoolExecutor(2) as pool:
            first = pool.submit(messaging.send_whatsapp, 'a', 'one')
            self.assertTrue(started.wait(1))
            second = pool.submit(messaging.send_whatsapp, 'b', 'two')
            self.assertTrue(attempted.wait(1))
            self.assertEqual(adapter.call_count, 1)
            release.set()
            self.assertEqual(first.result(timeout=2), 'ok');self.assertEqual(second.result(timeout=2), 'ok')
        self.assertEqual(maximum, 1)
