"""Bound real routing waits without network, model, device or tool execution."""
import json
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from modules import engine_tools, llm, model_wait, requests_state, router


class RouterWaitTests(unittest.TestCase):
    def setUp(self):
        token = llm._key_context.set(self.id())
        self.addCleanup(llm._key_context.reset, token)
        self.session = SimpleNamespace(last_command='önceki', pending_request={'question': 'Hangi dosya?'})
        self.ask = Mock(return_value=json.dumps({'intent': 'app_action', 'args': {'action': 'files_list', 'params': {}}}))
        self.runtime = SimpleNamespace(profile=SimpleNamespace(slug=self.id()),
            _session=lambda: self.session, _recent_turns=lambda *a, **k: [],
            json=json, intent_router=router, ask=self.ask)

    def release_worker(self, release):
        release.set()
        deadline = time.monotonic() + 2
        while self.id() in model_wait._PENDING and time.monotonic() < deadline:
            time.sleep(.001)
        self.assertNotIn(self.id(), model_wait._PENDING)

    def test_timeout_does_not_accept_late_route_or_consume_pending(self):
        release = threading.Event()
        self.ask.side_effect = lambda *a, **k: (release.wait(1), json.dumps({'intent': 'task', 'args': {}}))[1]
        before = dict(vars(self.session))
        with patch.object(model_wait, 'DEFAULT_SECONDS', .03):
            try:
                with self.assertRaisesRegex(RuntimeError, 'Geç yanıt') as timed_out:
                    engine_tools.route(self.runtime, 'hangi dosya yazıldı')
                from modules import failure_policy
                self.assertEqual(failure_policy.classify(timed_out.exception), failure_policy.TIMEOUT)
                with self.assertRaisesRegex(RuntimeError, 'henüz kapanmadı'):
                    engine_tools.route(self.runtime, 'başka bir dosyayı bul')
                self.assertEqual(self.ask.call_count, 1)
            finally:
                self.release_worker(release)
        self.assertEqual(vars(self.session), before)

    def test_cancel_returns_before_provider_finishes_and_keeps_pending(self):
        release, started = threading.Event(), threading.Event()
        def provider(*args, **kwargs):
            started.set()
            release.wait(1)
            return json.dumps({'intent': 'task', 'args': {}})
        self.ask.side_effect = provider
        def check():
            if started.is_set():
                raise requests_state.Cancelled('Test iptali')
        before = dict(vars(self.session))
        with model_wait.guard(check):
            try:
                with self.assertRaises(requests_state.Cancelled):
                    engine_tools.route(self.runtime, 'hangi dosya yazıldı')
                self.assertFalse(release.is_set())
            finally:
                self.release_worker(release)
        self.assertEqual(vars(self.session), before)

    def test_success_preserves_injected_ask_and_route_and_context(self):
        self.assertEqual(engine_tools.route(self.runtime, 'hangi dosya yazıldı')['intent'], 'app_action')
        self.ask.assert_called_once()
        self.assertIn('Hangi dosya?', self.ask.call_args.args[1])
        self.assertIsNone(self.session.pending_request)
        self.assertEqual(self.session.last_command, 'hangi dosya yazıldı')

    def test_fast_greeting_needs_no_model_or_user_wait_slot(self):
        with patch.object(model_wait, 'ask', side_effect=AssertionError('Hızlı kural model beklememeli')):
            self.assertEqual(engine_tools.route(self.runtime, 'merhaba')['intent'], 'chat')
        self.ask.assert_not_called()


if __name__ == '__main__':
    unittest.main()
