"""Real engine voice handoff: no microphone or idle without a verified stop.

This is a deterministic safety test. Audio is mocked at the physical adapter
boundary; it does NOT claim the Windows speaker actually stopped.
"""
from types import SimpleNamespace
import contextlib
import threading
from unittest import TestCase
from unittest.mock import Mock, patch

from modules import engine_loop, engine_voice


def _session(*, busy=False, unconfirmed=False):
    lane = SimpleNamespace(
        is_busy=Mock(return_value=busy),
        stop_unconfirmed=Mock(return_value=unconfirmed),
    )
    return SimpleNamespace(voice_lane=lane)


class EngineSpeakerSafetyTests(TestCase):
    def setUp(self):
        self.runtime = SimpleNamespace(emit=Mock())

    def test_unconfirmed_stop_on_empty_queue_is_still_potentially_audible(self):
        voice = _session(busy=False, unconfirmed=True)
        self.assertTrue(engine_loop._speech_blocks_mic(voice))
        with patch("modules.voice_runtime.handoff_to_listen", return_value=False) as cut:
            self.assertFalse(engine_loop._prepare_manual_listen(self.runtime, voice))
        cut.assert_called_once_with()
        self.runtime.emit.assert_called_once()
        self.assertEqual(self.runtime.emit.call_args.args[0], "system")
        self.assertIn("mikrofon açılmadı", self.runtime.emit.call_args.args[1])

    def test_acknowledged_stop_can_authorize_manual_capture(self):
        voice = _session(busy=False, unconfirmed=True)
        with patch("modules.voice_runtime.handoff_to_listen", return_value=True) as cut:
            self.assertTrue(engine_loop._prepare_manual_listen(self.runtime, voice))
        cut.assert_called_once_with()
        self.runtime.emit.assert_not_called()

    def test_busy_speaker_requires_verified_stop_even_without_unconfirmed_flag(self):
        voice = _session(busy=True, unconfirmed=False)
        with patch("modules.voice_runtime.handoff_to_listen", return_value=False):
            self.assertFalse(engine_loop._prepare_manual_listen(self.runtime, voice))
        self.assertTrue(engine_loop._speech_blocks_mic(voice))

    def test_idle_speaker_uses_no_cut_or_extra_device(self):
        voice = _session(busy=False, unconfirmed=False)
        with patch("modules.voice_runtime.handoff_to_listen", side_effect=AssertionError("unneeded")):
            self.assertTrue(engine_loop._prepare_manual_listen(self.runtime, voice))
        self.assertFalse(engine_loop._speech_blocks_mic(voice))
        self.runtime.emit.assert_not_called()

    def test_installed_voice_session_gate_takes_precedence_over_test_stub_lane(self):
        voice = _session(busy=False, unconfirmed=False)
        voice.speech_blocks_mic = Mock(return_value=True)
        with patch("modules.voice_runtime.handoff_to_listen", return_value=False):
            self.assertFalse(engine_loop._prepare_manual_listen(self.runtime, voice))
        voice.speech_blocks_mic.assert_called()

    def test_no_speaker_lane_does_not_block_text_only_operation(self):
        voice = SimpleNamespace(voice_lane=None)
        self.assertFalse(engine_loop._speech_blocks_mic(voice))
        with patch("modules.voice_runtime.handoff_to_listen", side_effect=AssertionError("unexpected")):
            self.assertTrue(engine_loop._prepare_manual_listen(self.runtime, voice))


class _RaceAtSecondMicLock:
    """A real audio_lock boundary with speaker state changing between captures."""

    def __init__(self, lane, stop=None):
        self.lane = lane
        self.stop = stop
        self.count = 0
        self.lock = threading.RLock()

    def __enter__(self):
        self.lock.acquire()
        self.count += 1
        if self.count == 2:
            self.lane.is_busy.return_value = True
            if self.stop is not None:
                self.stop.set()
        return self

    def __exit__(self, *exc):
        self.lock.release()


class WakeFollowupRaceTests(TestCase):
    @staticmethod
    def session(runtime, lane):
        session = engine_voice.VoiceSession.__new__(engine_voice.VoiceSession)
        session.runtime = runtime
        session.voice_lane = lane
        session.listening_enabled = True
        session.manual_local_stt = False
        session.state = {"awake_until": 0.0}
        return session

    def test_offline_wake_second_capture_is_fenced_inside_physical_lock(self):
        from modules import wakeword
        lane = _session().voice_lane
        runtime = SimpleNamespace(
            stop_event=threading.Event(), pause_listening=threading.Event(),
            flags={"mic": True}, WAKE_WORD="Hey Jarvis", mic_cancel=threading.Event(),
            time=SimpleNamespace(time=lambda: 100.0),
            audio_lock=_RaceAtSecondMicLock(lane),
            voice=SimpleNamespace(recognize=Mock(return_value=""), capture=Mock()),
            _strip_wake=lambda text: "", _AnyAbort=lambda *events: None,
            emit=Mock(), log=Mock(),
        )
        session = self.session(runtime, lane)
        with patch.object(wakeword, "wanted", return_value=True), \\
             patch.object(wakeword, "ready", return_value=True), \\
             patch.object(wakeword, "wait", return_value=b"wake"), \\
             patch("modules.engine_voice._physical_mic_claim",
                   return_value=contextlib.nullcontext()):
            self.assertTrue(session.offline_wake_step())
        self.assertEqual(runtime.audio_lock.count, 2)
        runtime.voice.capture.assert_not_called()

    def test_online_wake_second_capture_drops_if_speaker_just_started(self):
        lane = _session().voice_lane
        stop = threading.Event()
        runtime = SimpleNamespace(
            stop_event=stop, pause_listening=threading.Event(),
            flags={"mic": True}, WAKE_WORD="Hey Jarvis", mic_cancel=threading.Event(),
            time=SimpleNamespace(time=lambda: 100.0),
            audio_lock=_RaceAtSecondMicLock(lane, stop),
            voice=SimpleNamespace(
                recognize=Mock(return_value="hey jarvis"),
                capture=Mock(return_value=b"first"),
                last_noise=1),
            _AnyAbort=lambda *events: None,
            find_wake=lambda text: 0,
            _strip_wake=lambda text: "",
            _tr_lower=str.lower,
            emit=Mock(), log=Mock(), _record_failure=Mock(),
        )
        session = self.session(runtime, lane)
        session.offline_wake_step = Mock(return_value=False)
        session.submit_voice = Mock()
        session.listen_for_wake_word()
        self.assertEqual(runtime.audio_lock.count, 2)
        self.assertEqual(runtime.voice.capture.call_count, 1)
        session.submit_voice.assert_not_called()
