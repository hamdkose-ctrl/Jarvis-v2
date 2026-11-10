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

    def test_invalid_asset_path_rejected_before_synthesis(self):
        self._config({"tr_kadin": {"label": "x", "model": "../outside.onnx"}})
        with self.assertRaises(voice_runtime.VoiceConfigurationError):
            voice_runtime.maybe_start(self.rt)
        self.assertIsNone(voice_runtime.active())

    def test_only_one_output_owner_may_be_registered(self):
        first = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "K", "piper", "a.onnx"),)),
            lambda s, t, c: b"audio", lambda a, c: None,
        )
        voice_runtime.register(first)
        second = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "K", "piper", "a.onnx"),)),
            lambda s, t, c: b"audio", lambda a, c: None,
        )
        try:
            with self.assertRaises(voice_runtime.VoiceConfigurationError):
                voice_runtime.register(second)
            self.assertIs(voice_runtime.active(), first)
        finally:
            second.close()

    def test_unavailable_voice_selection_does_not_change_profile_preference(self):
        from modules.engine_context import _set_voice
        person = self.rt.profile
        saved = []
        person.name = "Deneme"
        person.set_pref = lambda key, value: saved.append((key, value))
        self.rt.voice = SimpleNamespace(VOICES={"tr_erkek": ("Kerem · Türkçe", "edge"),
                                               "tr_kadin": ("Defne · Türkçe", "edge")})
        lane = Mock()
        lane.check_voice.side_effect = ValueError("model missing")
        with patch("modules.voice_runtime.active", return_value=lane):
            message = _set_voice(self.rt, "tr_erkek")
        self.assertEqual(saved, [])
        self.assertIn("değişmedi", message)
        lane.check_voice.assert_called_once_with("tr_erkek")

    def test_valid_local_voice_selection_stops_queued_old_identity(self):
        from modules.engine_context import _set_voice
        person = self.rt.profile
        person.name = "Deneme"
        person.set_pref = lambda key, value: person.data["prefs"].__setitem__(key, value)
        self.rt.voice = SimpleNamespace(VOICES={
            "tr_erkek": ("Kerem · Türkçe", "edge"),
            "tr_kadin": ("Defne · Türkçe", "edge"),
        })
        lane = Mock()
        lane.check_voice.return_value = VoiceSpec("tr_erkek", "Yerel erkek", "piper", "male.onnx")
        with patch("modules.voice_runtime.active", return_value=lane):
            result = _set_voice(self.rt, "tr_erkek")
        self.assertEqual(person.data["prefs"]["voice"], "tr_erkek")
        self.assertIn("Yerel erkek", result)
        lane.interrupt.assert_called_once()

    def test_invalid_explicit_config_blocks_old_privacy_notice(self):
        self.assertFalse(voice_runtime.announce_active("notice"))
        voice_runtime.block_legacy_on_fault()
        self.assertTrue(voice_runtime.announce_active("notice"))
        # A subsequent absent configuration is an explicit return to legacy.
        voice_runtime.maybe_start(self.rt)
        self.assertFalse(voice_runtime.announce_active("notice"))

    def test_muted_voice_never_enqueues_privacy_notice(self):
        self.rt.flags["speak"] = False
        lane = Mock()
        lane.runtime = self.rt
        with patch("modules.voice_runtime.active", return_value=lane):
            self.assertTrue(voice_runtime.announce_active("do not play"))
        lane.say.assert_not_called()

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
        deadline = time.monotonic() + 2
        while ("state", "idle") not in self.rt.emitted and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIn(("state", "idle"), self.rt.emitted)


if __name__ == "__main__":
    unittest.main()
