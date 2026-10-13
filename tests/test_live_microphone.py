"""Microphone pipeline contracts with synthetic samples, no real device."""
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import numpy as np
import test_engine_modular as fixtures
from modules import live,live_microphone

class LiveMicrophoneTests(unittest.TestCase):
    def instance(self):
        with patch.object(live,'_Player',return_value=Mock()), patch.object(live.threading,'Thread'):
            obj=live.Live(Mock(),Mock(),Mock())
        self.addCleanup(obj.loop.close)
        obj.player.busy.return_value=False
        obj.player.last_end=0.;obj.player.latency=0.
        return obj

    def test_fixed_gain_is_capped_and_output_stays_int16(self):
        obj=self.instance();samples=np.full(1280,3000,dtype=np.int16)
        with patch.object(live,'_cfg',return_value=100):result=obj._agc(samples)
        self.assertEqual(obj._gain,20.)
        self.assertEqual(result.dtype,np.int16)
        self.assertEqual(len(result),1280)
        self.assertTrue(np.all(result>=0));self.assertLessEqual(int(result.max()),32767)

    def test_wake_threshold_keeps_original_word_wakeup(self):
        obj=self.instance();obj.wake=Mock()
        ww=SimpleNamespace(score=lambda x:.9,sensitivity_threshold=lambda:.7,reset=Mock())
        samples=np.full(1280,100,dtype=np.int16)
        obj._on_frame(samples,ww)
        obj.wake.assert_called_once_with(by_word=True);ww.reset.assert_called_once()
        self.assertEqual(obj._pre[-1],samples.tobytes())

    def test_speaker_echo_is_not_forwarded(self):
        obj=self.instance();obj._state='awake';obj.player.busy.return_value=True
        ww=SimpleNamespace(score=lambda x:.1)
        obj._on_frame(np.full(1280,100,dtype=np.int16),ww)
        self.assertEqual(len(obj._outbox),0);self.assertTrue(obj._was_muted)

    def test_two_strong_wake_frames_interrupt_playback(self):
        obj=self.instance();obj._state='awake';obj.player.busy.return_value=True;obj.interrupt=Mock()
        ww=SimpleNamespace(score=lambda x:1.,reset=Mock())
        samples=np.full(1280,100,dtype=np.int16)
        obj._on_frame(samples,ww);obj.interrupt.assert_not_called()
        obj._on_frame(samples,ww);obj.interrupt.assert_called_once();ww.reset.assert_called_once()

    def test_echo_tail_sends_gap_without_microphone_audio(self):
        obj=self.instance();obj._state='awake';obj._was_muted=True
        obj.player.last_end=100.;obj.player.latency=.2
        with patch.object(live_microphone.time,'monotonic',return_value=100.):
            obj._on_frame(np.full(1280,100,dtype=np.int16),SimpleNamespace())
        self.assertEqual(list(obj._outbox),[None]);self.assertGreater(obj._mute_until,100.)
        self.assertEqual(len(obj._sent),0)

    def test_disabled_microphone_does_not_open_portaudio_stream(self):
        obj=self.instance();obj.mic_on=lambda:False
        obj.stop_event=SimpleNamespace(is_set=Mock(side_effect=[False,True]),wait=Mock())
        stream=Mock()
        with patch.dict(sys.modules,{'sounddevice':SimpleNamespace(InputStream=stream)}):obj._mic_loop()
        stream.assert_not_called();obj.stop_event.wait.assert_called_once_with(.10)
