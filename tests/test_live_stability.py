import asyncio
import collections
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave
import numpy as np
from modules import live
from modules.speech_activity import SpeechActivity
from modules.audio_diagnostics import AudioDiagnostics


class SpeechTests(unittest.TestCase):
    def test_sustained_speech_extends_wait_but_noise_cannot_keep_it_open_forever(self):
        detector = SpeechActivity()
        for i in range(50):
            detector.observe(np.full(1280, 8, dtype=np.int16), i * .08)
        for i in range(4):
            detector.observe(np.full(1280, 300, dtype=np.int16), 11 + i * .08)
        self.assertFalse(detector.expired(13, 0, 12))
        self.assertTrue(detector.expired(24, 0, 12))
        detector.last = 59.9
        self.assertTrue(detector.expired(60, 0, 12))

    def test_constant_noise_and_single_click_are_not_activity(self):
        detector = SpeechActivity()
        for i in range(100):
            detector.observe(np.full(1280, 400, dtype=np.int16), i * .08)
        detector.observe(np.full(1280, 12000, dtype=np.int16), 10)
        detector.observe(np.full(1280, 400, dtype=np.int16), 10.08)
        self.assertIsNone(detector.last)

    def test_reset_preserves_room_baseline_but_forgets_previous_speech(self):
        detector = SpeechActivity(); detector.levels.append(10); detector.last = 42
        detector.reset()
        self.assertIsNone(detector.last)
        self.assertEqual(list(detector.levels), [10])


class VoiceTests(unittest.TestCase):
    def test_selecting_current_voice_does_not_reload_or_write_settings(self):
        obj = live.Live.__new__(live.Live); obj._reload = False
        with patch.object(live, 'voice_name', return_value='Kore'), patch('config.save_settings') as save:
            self.assertIn('Zaten', obj._change_voice('kore'))
        save.assert_not_called(); self.assertFalse(obj._reload)

    def test_new_voice_is_persisted_and_schedules_one_reload(self):
        obj = live.Live.__new__(live.Live); obj._reload = False
        with patch.object(live, 'voice_name', return_value='Charon'), patch('config.save_settings') as save:
            obj._change_voice('Kore')
        save.assert_called_once_with(live_voice='Kore'); self.assertTrue(obj._reload)

    def test_voice_reload_drops_resume_handle(self):
        obj = live.Live.__new__(live.Live)
        obj.stop_event = SimpleNamespace(is_set=lambda: False)
        obj.player = SimpleNamespace(busy=lambda: False)
        obj._closing = False; obj._claim = None; obj._tools_running = 0
        obj._generating = False; obj._pending_text = []; obj._heard_any = True
        obj._speech_activity = SpeechActivity(); obj._reload = True; obj._reload_at = 0
        obj._resume = 'old-voice-session'; obj._reconnect = False
        obj._flush_transcripts = Mock(return_value='')
        async def no_wait(_): pass
        with patch.object(live.asyncio, 'sleep', no_wait), patch.object(live, '_cfg', side_effect=lambda k,d: d):
            asyncio.run(obj._watch(None))
        self.assertIsNone(obj._resume); self.assertTrue(obj._reconnect)

    def test_old_session_cannot_play_voice_change_confirmation(self):
        obj = live.Live.__new__(live.Live)
        obj._voice_transition = True; obj._discard = False; obj._generating = False
        obj._timing = Mock()
        obj.player = SimpleNamespace(feed=Mock()); obj._out_buf = []; obj._in_buf = []
        obj._tools_running = 0; obj._ex_tools = 0; obj._corrected = False
        obj.emit = Mock(); obj._flush_transcripts = Mock(return_value='')
        response = SimpleNamespace(data=b'old-voice', tool_call=None,
            server_content=SimpleNamespace(output_transcription=SimpleNamespace(text='Sesimi değiştirdim'), turn_complete=True))
        class Session:
            calls = 0
            async def receive(self):
                self.calls += 1
                if self.calls > 1: raise RuntimeError('end test')
                yield response
        with self.assertRaisesRegex(RuntimeError, 'end test'):
            asyncio.run(obj._receive(Session()))
        obj.player.feed.assert_not_called()
        self.assertEqual(obj._out_buf, [])

    def test_confirmation_is_queued_only_after_new_connection_enters(self):
        player = SimpleNamespace(clear=Mock())
        with patch.object(live, '_Player', return_value=player), patch.object(live.threading, 'Thread'):
            obj = live.Live(Mock(), Mock(), lambda: 'prompt')
        self.addCleanup(obj.loop.close)
        obj._voice_confirmation = 'Kore'; obj._voice_transition = True
        obj._discard = obj._generating = True
        obj._config = Mock(return_value={'voice': 'Kore'})
        obj._save_sent = Mock()
        events = []
        class Connection:
            async def __aenter__(self):
                self_outer.assertEqual(obj._pending_text, [])
                self_outer.assertTrue(obj._voice_transition)
                events.append('connected')
                return SimpleNamespace()
            async def __aexit__(self, *args): pass
        self_outer = self
        async def run_session(session):
            self.assertEqual(events, ['connected'])
            self.assertFalse(obj._voice_transition)
            self.assertFalse(obj._discard)
            self.assertFalse(obj._generating)
            self.assertEqual(len(obj._pending_text), 1)
            self.assertIn('Sesimi Kore olarak güncelledim', obj._pending_text[0])
            obj._closing = True
        obj._run_session = run_session
        cli = SimpleNamespace(aio=SimpleNamespace(live=SimpleNamespace(connect=lambda **kw: Connection())))
        with patch('modules.llm._cli', return_value=cli), patch.object(live, 'enabled', return_value=True), patch.object(live, '_cfg', side_effect=lambda k,d: d):
            asyncio.run(obj._converse())

    def test_timer_measures_listening_not_connection_latency(self):
        obj = live.Live.__new__(live.Live)
        obj.stop_event = SimpleNamespace(is_set=lambda: False)
        obj.player = SimpleNamespace(busy=lambda: False)
        obj._closing = False; obj._claim = None; obj._tools_running = 0
        obj._generating = False; obj._pending_text = []; obj._heard_any = False
        obj._speech_activity = SpeechActivity(); obj._reload = False
        obj._woke_at = 0; obj._listening_since = 20; obj._activity = 20
        obj._sleep_after = False; obj._beep_close = Mock(); obj.emit = Mock()
        clock = [9]
        async def no_wait(_):
            self.assertFalse(obj._closing)
            clock[0] += 12
        with patch.object(live.asyncio, 'sleep', no_wait), patch.object(live, 'time', SimpleNamespace(monotonic=lambda: clock[0])), patch.object(live, '_cfg', side_effect=lambda k,d: d):
            asyncio.run(obj._watch(None))
        self.assertTrue(obj._closing); obj._beep_close.assert_called_once()


class DiagnosticsTests(unittest.TestCase):
    def test_recordings_preserve_missing_send_as_silence_on_same_timeline(self):
        recorder = AudioDiagnostics()
        pcm = np.full(1600, 500, dtype='<i2').tobytes()
        recorder.input(29, pcm, 16000); recorder.input(30, pcm, 16000)
        recorder.output(30, pcm)
        with tempfile.TemporaryDirectory() as folder:
            recorder.save(Path(folder), 30)
            with wave.open(str(Path(folder)/'tani_mikrofon.wav')) as w:
                self.assertEqual(w.getnframes(), 480000)
                raw = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2')
            with wave.open(str(Path(folder)/'tani_gonderilen.wav')) as w:
                sent = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2')
        self.assertGreater(raw[round(28.95*16000)], 0)
        self.assertEqual(sent[round(28.95*16000)], 0)
        self.assertTrue(np.array_equal(raw[-1600:], sent[-1600:]))

    def test_native_rate_is_preserved_and_buffers_are_bounded(self):
        recorder = AudioDiagnostics()
        for i in range(1000): recorder.input(i/10, b'\0\0'*4410, 44100)
        self.assertEqual(len(recorder.raw), 400)
        with tempfile.TemporaryDirectory() as folder:
            recorder.save(Path(folder), 100)
            with wave.open(str(Path(folder)/'tani_mikrofon.wav')) as w:
                self.assertEqual(w.getframerate(), 44100)

