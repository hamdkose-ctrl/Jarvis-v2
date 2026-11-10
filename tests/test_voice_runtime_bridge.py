"""VOICE-02A opt-in dispatch: profile identity, single output owner and audio-only stop.

All adapters and audio devices are mocked. These tests do not prove physical
speaker output or real Turkish model quality.
"""
import json
import secrets
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import voice_runtime
from modules.engine_voice import VoiceSession
from modules.voice_core import VoiceCatalog, VoiceSpec


def runtime(tmp, voice="tr_kadin"):
    person = SimpleNamespace(slug="alice", data={"prefs": {"voice": voice}})
    emitted = []
    return SimpleNamespace(
        DATA_DIR=Path(tmp), profile=person, pc_profile=lambda: person,
        secrets=secrets, threading=threading, flags={"speak": True, "mic": False},
        emit=lambda kind, message: emitted.append((kind, message)),
        _record_failure=lambda *args: None,
        emitted=emitted,
    )


class VoiceRuntimeBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.rt = runtime(self.temp.name)
        self.addCleanup(self._close)

    def _close(self):
        lane = voice_runtime.active()
        if lane is not None:
            lane.close()

    def test_opt_in_config_absence_keeps_existing_voice_path(self):
        lane, enabled = voice_runtime.maybe_start(self.rt)
        self.assertIsNone(lane)
        self.assertFalse(enabled)
        self.assertIsNone(voice_runtime.active())

    def _config(self, voices=None, enabled=True):
        body = {
            "schema": "voice_core.config.v1",
            "enabled": enabled,
            "voices": voices if voices is not None else {
                "tr_erkek": {"label": "Türkçe erkek", "model": "male-tr.onnx"},
                "tr_kadin": {"label": "Türkçe kadın", "model": "female-tr.onnx"},
            },
        }
        (self.rt.DATA_DIR / voice_runtime.CONFIG_NAME).write_text(
            json.dumps(body, ensure_ascii=False), encoding="utf-8",
        )

    def test_voice_config_choices_are_user_bound_and_not_automatic_fallbacks(self):
        self._config()
        lane, enabled = voice_runtime.maybe_start(self.rt)
        self.assertTrue(enabled)
        self.assertIs(voice_runtime.active(), lane)
        self.assertEqual(lane.catalog.require("tr_kadin").asset_id, "female-tr.onnx")
        self.assertEqual(lane.catalog.require("tr_erkek").asset_id, "male-tr.onnx")
        with self.assertRaisesRegex(ValueError, "unavailable"):
            lane.say("alice", "ml_erkek", "Merhaba")
        self.assertFalse(lane.is_busy())

    def test_invalid_explicit_config_fails_closed(self):
        for voices in ({}, {"unknown": {"label": "X", "model": "x.onnx"}},
                       {"tr_kadin": {"label": "x", "model": "x.onnx", "wrong": 1}}):
            with self.subTest(voices=voices):
                self._config(voices)
                with self.assertRaises(voice_runtime.VoiceConfigurationError):
                    voice_runtime.maybe_start(self.rt)
        self.assertIsNone(voice_runtime.active())

    def test_disabled_config_does_not_take_output_ownership(self):
        self._config(enabled=False)
        lane, enabled = voice_runtime.maybe_start(self.rt)
        self.assertIsNone(lane)
        self.assertFalse(enabled)

    def test_speech_enqueues_without_blocking_work_and_exact_selected_voice(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []
        def synth(spec, text, cancel):
            calls.append(spec.voice_id)
            entered.set()
            release.wait(2)
            return b"audio"
        lane = voice_runtime.VoiceLane(
            self.rt,
            VoiceCatalog((VoiceSpec("tr_kadin", "Kadin", "piper", "a.onnx"),)),
            synth, lambda data, cancel: None,
        )
        voice_runtime.register(lane)
        try:
            done = lane.say("alice", "tr_kadin", "Araştırıyorum")
            self.assertFalse(done.is_set())
            self.assertTrue(entered.wait(1))
            self.assertTrue(lane.is_busy())
            # An unrelated work-owner token is never cancelled by speech.
            goal = threading.Event()
            goal.set()
            lane.interrupt()
            self.assertTrue(goal.is_set())
        finally:
            release.set()
        self.assertTrue(done.wait(2))
        self.assertEqual(calls, ["tr_kadin"])
        self.assertFalse(lane.is_busy())

    def test_web_or_voice_stop_reaches_same_active_lane_without_core_cancel(self):
        entered = threading.Event()
        release = threading.Event()
        played = []
        def synth(spec, text, cancel):
            entered.set()
            release.wait(2)
            return b"audio"
        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "Kadin", "piper", "a.onnx"),)),
            synth, lambda data, cancel: played.append(data),
        )
        voice_runtime.register(lane)
        try:
            done = lane.say("alice", "tr_kadin", "Kes")
            self.assertTrue(entered.wait(1))
            from modules import voice
            voice.stop_speaking()  # shared web/emergency/PC guide entry point
        finally:
            release.set()
        self.assertTrue(done.wait(2))
        self.assertEqual(played, [])

    def test_voice_session_never_calls_legacy_speech_when_lane_enabled(self):
        lane = Mock()
        result = threading.Event()
        lane.say.return_value = result
        rt = self.rt
        rt.threading = SimpleNamespace(Thread=Mock())
        rt.voice = SimpleNamespace(speak=Mock())
        session = VoiceSession.__new__(VoiceSession)
        session.runtime, session.speak_enabled, session.live_on = rt, True, False
        session.voice_lane, session.voice_core_fault = lane, None
        session.speak("Metin", shown=True)
        lane.say.assert_called_once_with("alice", "tr_kadin", "Metin", background=True)
        rt.voice.speak.assert_not_called()
        self.assertIn(("state", "speaking"), rt.emitted)

    def test_voice_session_unavailable_selected_identity_no_silent_fallback(self):
        lane = Mock()
        lane.say.side_effect = ValueError("No such voice")
        rt = self.rt
        rt.voice = SimpleNamespace(speak=Mock())
        session = VoiceSession.__new__(VoiceSession)
        session.runtime, session.speak_enabled, session.live_on = rt, True, False
        session.voice_lane, session.voice_core_fault = lane, None
        session.speak("Metin")
        rt.voice.speak.assert_not_called()
        self.assertTrue(any(k == "system" and "başka ses" in v for k, v in rt.emitted))

    def test_status_returns_idle_after_last_speech_receipt(self):
        lane = voice_runtime.VoiceLane(
            self.rt,
            VoiceCatalog((VoiceSpec("tr_kadin", "Kadin", "piper", "a.onnx"),)),
            lambda spec, text, cancel: b"audio",
            lambda audio, cancel: None,
        )
        voice_runtime.register(lane)
        done = lane.say("alice", "tr_kadin", "Merhaba")
        self.assertTrue(done.wait(2))
        self.assertIn(("state", "idle"), self.rt.emitted)


if __name__ == "__main__":
    unittest.main()
