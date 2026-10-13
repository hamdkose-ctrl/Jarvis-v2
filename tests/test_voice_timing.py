import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import numpy as np
from modules import live, live_audio
from modules.voice_timing import VoiceTiming


class VoiceTimingTests(unittest.TestCase):
    def test_each_stage_is_recorded_once_and_beep_cannot_be_first_reply(self):
        timer = VoiceTiming()
        with patch('modules.voice_timing.time.monotonic', side_effect=[10, 11, 12, 13]):
            timer.begin(); timer.note('output_write'); timer.note('connected')
            timer.note('connected'); timer.note('reply_audio'); timer.note('output_write')
        self.assertEqual(timer.events, {'wake':10, 'connected':11, 'reply_audio':12, 'output_write':13})
        timer.begin(); self.assertEqual(list(timer.events), ['wake'])

    def test_beep_write_does_not_fire_reply_playback_callback(self):
        obj = live_audio._Player.__new__(live_audio._Player)
        obj.runtime = SimpleNamespace(speak_allowed=lambda:True)
        obj._stream = SimpleNamespace(write=Mock()); obj._vol_ok = True; obj.on_play = Mock()
        obj._write(b'\0'*100, speech=False)
        obj.on_play.assert_not_called()
        obj._write(b'\0'*100)
        obj.on_play.assert_called_once()

    def test_wake_keeps_boundary_and_next_two_frames_without_skipping(self):
        with patch.object(live, '_Player', return_value=Mock()), patch.object(live.threading, 'Thread'):
            obj = live.Live(Mock(), Mock(), lambda:'prompt')
        self.addCleanup(obj.loop.close)
        obj._beep = Mock(); obj._pre.extend([b'old-wake', b'boundary'])
        def schedule(coro, loop):
            coro.close()
            return Mock()
        with patch.object(live.asyncio, 'run_coroutine_threadsafe', side_effect=schedule), patch.object(live, '_cfg', side_effect=lambda k,d:d):
            obj.wake(by_word=True)
            first = np.full(1280, 400, dtype=np.int16)
            second = np.full(1280, 800, dtype=np.int16)
            obj._on_frame(first, Mock()); obj._on_frame(second, Mock())
        self.assertEqual(list(obj._outbox), [b'boundary', first.tobytes(), second.tobytes()])
