"""Real engine voice handoff: no microphone or idle without a verified stop.

This is a deterministic safety test. Audio is mocked at the physical adapter
boundary; it does NOT claim the Windows speaker actually stopped.
"""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from modules import engine_loop


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
