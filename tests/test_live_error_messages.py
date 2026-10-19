import asyncio
import collections
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import numpy as np

from modules import failure_policy, live, live_microphone, ollama_hint


class RateLimitError(Exception):
    status_code = 429


class LiveErrorMessageTests(unittest.TestCase):
    def _connecting(self):
        obj = live.Live.__new__(live.Live)
        obj._quiet_frames = 0
        obj._warned_quiet = False
        obj._state = 'connecting'
        obj._skip = 0
        obj._outbox = collections.deque()
        obj._since = 0.0
        obj._session_error_category = None
        obj._session_rate_limited = False
        obj.emit = Mock()
        return obj

    @staticmethod
    def _services():
        return SimpleNamespace(log=Mock())

    def _timeout(self, obj, *, internet_up):
        services = self._services()
        with patch('modules.ollama_hint.internet_up', return_value=internet_up), \
             patch('modules.live_microphone.time.monotonic', return_value=26.0):
            live_microphone.frame(obj, np.ones(4, dtype=np.int16), object(), services)
        return services

    def test_no_internet_uses_existing_no_internet_message(self):
        obj = self._connecting()
        services = self._timeout(obj, internet_up=False)
        obj.emit.assert_any_call('system', ollama_hint.NO_INTERNET)
        self.assertEqual(services.log.warning.call_args.args[-1], failure_policy.NETWORK)

    def test_rate_limit_uses_quota_message_without_raw_error(self):
        obj = self._connecting()
        secret = 'SECRET_API_KEY_123'
        with patch('modules.diagnose.explain', return_value='güvenli tanı'):
            obj._explain(RateLimitError(f'429 quota exceeded {secret}'))
        self.assertEqual(obj._session_error_category, failure_policy.RATE_LIMIT)
        self.assertTrue(obj._session_rate_limited)

        services = self._timeout(obj, internet_up=True)
        message = next(call.args[1] for call in obj.emit.call_args_list if call.args[0] == 'system')
        self.assertEqual(message, 'Gemini kotası dolmuş görünüyor, biraz sonra tekrar dene.')
        self.assertNotIn(secret, message)
        self.assertNotIn(secret, str(services.log.warning.call_args.args))
        self.assertEqual(services.log.warning.call_args.args[-1], failure_policy.RATE_LIMIT)

    def test_other_error_with_internet_keeps_existing_message(self):
        obj = self._connecting()
        obj._session_error_category = failure_policy.TIMEOUT
        services = self._timeout(obj, internet_up=True)
        old = 'Canlı konuşmaya bağlanılamadı. İnternetini kontrol edip tekrar “Hey Jarvis” de.'
        obj.emit.assert_any_call('system', old)
        self.assertEqual(services.log.warning.call_args.args[-1], failure_policy.TIMEOUT)

    def test_asleep_frame_clears_previous_session_error_marker(self):
        obj = live.Live.__new__(live.Live)
        obj._quiet_frames = 0
        obj._warned_quiet = False
        obj._state = 'asleep'
        obj._session_error_category = failure_policy.RATE_LIMIT
        obj._session_rate_limited = True
        obj._pre = collections.deque()
        obj._win_n = 0
        obj._win_max = 0.0
        obj._win_lvl = 0.0
        obj._wake_soft_hits = 0
        obj._wake_warned = True
        obj._score_logged = 0.0
        obj._frames = 0
        wakeword = SimpleNamespace(
            score=lambda _x: 0.0,
            sensitivity_threshold=lambda: 0.5,
            status=lambda: {'state': 'ready'},
        )
        services = self._services()
        live_microphone.frame(obj, np.ones(4, dtype=np.int16), wakeword, services)
        self.assertIsNone(obj._session_error_category)
        self.assertFalse(obj._session_rate_limited)

    def _watch_once(self, rate_limited):
        obj = live.Live.__new__(live.Live)
        obj._closing = False
        obj.stop_event = SimpleNamespace(is_set=lambda: False)
        obj._claim = None
        obj._reload = False
        obj.player = SimpleNamespace(busy=lambda: False)
        obj._tools_running = 0
        obj._generating = False
        obj._pending_text = []
        obj._heard_any = False
        obj._listening_since = 0.0
        obj._speech_activity = SimpleNamespace(last=1.0, expired=lambda *_args: True)
        obj._session_rate_limited = rate_limited
        obj.emit = Mock()
        obj._beep_close = Mock()
        obj._sleep_after = False
        obj._activity = 0.0

        with patch.object(live.asyncio, 'sleep', new=AsyncMock()), \
             patch.object(live.time, 'monotonic', return_value=20.0), \
             patch.object(live, '_cfg', side_effect=lambda _key, default: default), \
             patch.object(live.log, 'warning') as warning:
            asyncio.run(obj._watch(None))
        return obj, warning

    def test_transcript_failure_message_stays_same_and_log_marks_quota(self):
        expected = 'Ses etkinliği algıladım fakat konuşmanı yazıya çeviremedim. Tekrar söyler misin?'
        for rate_limited, marker in [(True, 'var'), (False, 'yok')]:
            with self.subTest(rate_limited=rate_limited):
                obj, warning = self._watch_once(rate_limited)
                obj.emit.assert_called_once_with('system', expected)
                self.assertIn('oturumda kota hatası %s', warning.call_args.args[0])
                self.assertEqual(warning.call_args.args[1], marker)


if __name__ == '__main__':
    unittest.main()
