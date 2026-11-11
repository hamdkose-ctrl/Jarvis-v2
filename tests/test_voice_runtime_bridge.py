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
    events = []

    def emit(kind, message, extra=""):
        emitted.append((kind, message))
        events.append((kind, message, extra))

    return SimpleNamespace(
        DATA_DIR=Path(tmp), profile=person, pc_profile=lambda: person,
        secrets=secrets, threading=threading, flags={"speak": True, "mic": False},
        emit=emit,
        _record_failure=lambda *args: None,
        voice=SimpleNamespace(VOICES={
            "tr_erkek": ("Kerem · Türkçe", "tr-TR-AhmetNeural"),
            "tr_kadin": ("Defne · Türkçe", "tr-TR-EmelNeural"),
        }),
        emitted=emitted, events=events,
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

    def test_absent_piper_config_selects_exact_edge_owner_not_legacy(self):
        lane, enabled = voice_runtime.maybe_start(self.rt)
        self.assertIsNotNone(lane)
        self.assertFalse(enabled)
        self.assertIs(voice_runtime.active(), lane)
        self.assertEqual(lane.catalog.require("tr_kadin").backend, "edge")
        self.assertEqual(lane.catalog.require("tr_kadin").asset_id, "tr-TR-EmelNeural")

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
            lambda s, t, c: b"audio", lambda a, c, s: s(),
        )
        voice_runtime.register(first)
        second = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "K", "piper", "a.onnx"),)),
            lambda s, t, c: b"audio", lambda a, c, s: s(),
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
        from modules.engine_context import _set_voice
        from web_voice import WebVoice
        self.assertFalse(voice_runtime.announce_active("notice"))
        voice_runtime.block_legacy_on_fault()
        self.assertTrue(voice_runtime.announce_active("notice"))
        person = self.rt.profile
        person.name = "Deneme"
        person.set_pref = Mock()
        self.rt.voice = SimpleNamespace(VOICES={"tr_kadin": ("Defne · Türkçe", "edge")})
        bridge = WebVoice()
        bridge._runtime = SimpleNamespace(_p=lambda: person)
        self.assertEqual(bridge.voice_options()["voices"], [])
        self.assertIn("error", bridge.voice_options())
        self.assertFalse(bridge.voice_set("tr_kadin"))
        self.assertFalse(bridge.rate_set(20))
        self.assertIn("değişmedi", _set_voice(self.rt, "tr_kadin"))
        person.set_pref.assert_not_called()
        # An absent Piper config now selects the exact Edge owner (no legacy loop).
        lane, enabled = voice_runtime.maybe_start(self.rt)
        self.assertFalse(enabled)
        self.assertIs(voice_runtime.active(), lane)
        self.assertEqual(lane.catalog.require("tr_kadin").backend, "edge")

    def test_muted_voice_never_enqueues_privacy_notice(self):
        self.rt.flags["speak"] = False
        lane = Mock()
        lane.runtime = self.rt
        with patch("modules.voice_runtime.active", return_value=lane):
            self.assertTrue(voice_runtime.announce_active("do not play"))
        lane.say.assert_not_called()

    def test_disabled_piper_config_still_owns_output_with_exact_edge(self):
        self._config(enabled=False)
        lane, enabled = voice_runtime.maybe_start(self.rt)
        self.assertIsNotNone(lane)
        self.assertFalse(enabled)
        self.assertIs(voice_runtime.active(), lane)
        self.assertEqual(lane.catalog.require("tr_erkek").backend, "edge")

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
            synth, lambda data, cancel, on_start: on_start(),
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
            synth, lambda data, cancel, on_start: (played.append(data), on_start()),
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
        lane.say.assert_called_once_with("alice", "tr_kadin", "Metin", background=True, rate=0,
                                         kind="notice", turn_id="")
        rt.voice.speak.assert_not_called()
        # Enqueue is not audible speech: the lane claims "speaking" only at the
        # real playback_started boundary (see VoiceLane stage tests), never here.
        self.assertNotIn(("state", "speaking"), rt.emitted)

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

    def test_web_local_choices_preview_and_rate_are_exact_and_owner_bound(self):
        from web_voice import WebVoice
        spec = VoiceSpec("tr_kadin", "Yerel kadın", "piper", "female.onnx")
        catalog = VoiceCatalog((spec,))
        lane = Mock()
        lane.catalog = catalog
        lane.check_voice.side_effect = catalog.require
        person = self.rt.profile
        person.set_pref = lambda key, value: person.data["prefs"].__setitem__(key, value)
        voice_events = []
        bridge = WebVoice()
        bridge._runtime = SimpleNamespace(
            _p=lambda: person,
            config=SimpleNamespace(load_settings=lambda: {"local_stt_enabled": False}),
            _live=lambda: self.fail("local voice should never inspect Gemini Live"),
            engine=SimpleNamespace(events=SimpleNamespace(put=voice_events.append)),
        )
        with patch("modules.voice_runtime.active", return_value=lane):
            options = bridge.voice_options()
            self.assertTrue(options["local"])
            self.assertTrue(options["rate_supported"])
            self.assertEqual(options["voices"], [{
                "key": "tr_kadin", "name": "Yerel kadın", "info": "Yerel Piper",
            }])
            self.assertTrue(bridge.voice_set("tr_kadin"))
            self.assertTrue(bridge.rate_set(35))
            self.assertFalse(bridge.rate_set(True))
            self.assertFalse(bridge.rate_set("hızlı"))
            self.assertFalse(bridge.voice_set("not-installed"))
        self.assertEqual(person.data["prefs"].get("voice"), "tr_kadin")
        self.assertEqual(person.data["prefs"].get("rate"), 35)
        self.assertEqual(voice_events, [
            ("say", "Merhaba, seçtiğin ses böyle.", "alice"),
            ("say", "Böyle konuşuyorum."),
        ])
        lane.interrupt.assert_not_called()

    def test_voice_session_snapshots_rate_and_slow_mode_without_mutating_prefs(self):
        lane = Mock()
        lane.say.return_value = threading.Event()
        rt = self.rt
        rt.threading = SimpleNamespace(Thread=Mock())
        rt.voice = SimpleNamespace(speak=Mock())
        rt.profile.data["prefs"]["rate"] = 20
        session = VoiceSession.__new__(VoiceSession)
        session.runtime, session.speak_enabled, session.live_on = rt, True, False
        session.voice_lane, session.voice_core_fault = lane, None
        session.speak("Normal hız")
        session.speak("Yavaş anlat", slow=True)
        first, second = lane.say.call_args_list[0].kwargs, lane.say.call_args_list[1].kwargs
        self.assertEqual((first["background"], first["rate"]), (False, 20))
        self.assertEqual((second["background"], second["rate"]), (False, -15))
        self.assertEqual(rt.profile.data["prefs"]["rate"], 20)
        rt.voice.speak.assert_not_called()

    def test_missing_piper_voice_rejects_rate_setting_without_false_success(self):
        from modules.engine_context import set_profile_rate
        person = self.rt.profile
        writes = []
        person.set_pref = lambda key, value: writes.append((key, value))
        lane = Mock()
        lane.check_voice.side_effect = ValueError("installed voice missing")
        self.assertFalse(set_profile_rate(person, 12, lane=lane))
        self.assertFalse(set_profile_rate(person, True, lane=lane))
        self.assertEqual(writes, [])

    def test_web_rejects_missing_local_model_without_changing_profile(self):
        from web_voice import WebVoice
        lane = Mock()
        lane.catalog = VoiceCatalog((VoiceSpec("tr_kadin", "Kadın", "piper", "missing.onnx"),))
        lane.check_voice.side_effect = ValueError("missing")
        person = self.rt.profile
        person.set_pref = Mock()
        web = WebVoice()
        web._runtime = SimpleNamespace(_p=lambda: person)
        with patch("modules.voice_runtime.active", return_value=lane):
            self.assertEqual(web.voice_options()["voices"], [])
            self.assertFalse(web.voice_options()["rate_supported"])
            self.assertFalse(web.voice_set("tr_kadin"))
            self.assertFalse(web.rate_set(12))
        person.set_pref.assert_not_called()
        lane.interrupt.assert_not_called()

    def test_pending_audio_receipt_is_acknowledged_immediately_on_sus(self):
        entered, released = threading.Event(), threading.Event()
        def synth(spec, text, cancel):
            entered.set()
            self.assertTrue(released.wait(3))
            return b"audio"
        lane = voice_runtime.VoiceLane(
            self.rt,
            VoiceCatalog((VoiceSpec("tr_kadin", "Kadın", "piper", "a.onnx"),)),
            synth, lambda audio, cancel, on_start: on_start(),
        )
        voice_runtime.register(lane)
        try:
            active = lane.say("alice", "tr_kadin", "Birinci yanıt.")
            self.assertTrue(entered.wait(1))
            waiting = lane.say("alice", "tr_kadin", "Bekleyen ikinci yanıt.")
            self.assertFalse(waiting.is_set())
            lane.interrupt()
            self.assertTrue(waiting.wait(1))
            self.assertTrue(lane.is_busy())
        finally:
            released.set()
        self.assertTrue(active.wait(2))
        self.assertFalse(lane.is_busy())

    def test_status_returns_idle_after_last_speech_receipt(self):
        lane = voice_runtime.VoiceLane(
            self.rt,
            VoiceCatalog((VoiceSpec("tr_kadin", "Kadin", "piper", "a.onnx"),)),
            lambda spec, text, cancel: b"audio",
            lambda audio, cancel, on_start: on_start(),
        )
        voice_runtime.register(lane)
        done = lane.say("alice", "tr_kadin", "Merhaba")
        self.assertTrue(done.wait(2))
        deadline = time.monotonic() + 2
        while ("state", "idle") not in self.rt.emitted and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIn(("state", "idle"), self.rt.emitted)


    def test_edge_voice_refused_in_local_only_mode_without_egress(self):
        import config  # load config before privacy (config <-> privacy import cycle)
        from modules import privacy
        synthesized = []
        with patch.object(privacy, "mode", return_value="yerel"), \
                patch("modules.voice_runtime.EdgeSynthesizer") as synth_cls:
            synth_cls.return_value = lambda spec, text, cancel: (synthesized.append(text), b"audio")[1]
            lane, enabled = voice_runtime.maybe_start(self.rt)
            self.assertFalse(enabled)
            done = lane.say("alice", "tr_kadin", "Merhaba")
            self.assertTrue(done.is_set())  # rejected at enqueue, acknowledged immediately
            self.assertFalse(lane.is_busy())
        self.assertEqual(synthesized, [])  # no online synthesis, no cloud egress
        self.assertTrue(any(k == "system" and "buluta gönderilmez" in v
                            for k, v in self.rt.emitted))
        self.assertEqual(self.rt.profile.data["prefs"]["voice"], "tr_kadin")  # preference kept

    def test_offline_piper_voice_speaks_in_local_only_mode(self):
        import config  # load config before privacy (config <-> privacy import cycle)
        from modules import privacy
        played = []
        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "K", "piper", "a.onnx"),)),
            lambda spec, text, cancel: b"audio",
            lambda audio, cancel, on_start: (played.append(audio), on_start()),
        )
        voice_runtime.register(lane)
        with patch.object(privacy, "mode", return_value="yerel"):
            done = lane.say("alice", "tr_kadin", "Merhaba")
            self.assertTrue(done.wait(2))
        self.assertEqual(played, [b"audio"])
        self.assertFalse(any("buluta gönderilmez" in v for k, v in self.rt.emitted if k == "system"))

    def test_speaking_and_identity_come_from_real_playback_not_enqueue(self):
        entered, release = threading.Event(), threading.Event()

        def synth(spec, text, cancel):
            entered.set()
            return b"audio"

        def play(audio, cancel, on_start):
            self.assertTrue(release.wait(2))
            on_start()

        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "K", "piper", "a.onnx"),)),
            synth, play,
        )
        voice_runtime.register(lane)
        done = lane.say("alice", "tr_kadin", "Merhaba", turn_id="t1", goal_id="g1")
        self.assertTrue(entered.wait(1))
        # WAV bytes exist and enqueue succeeded, but the player has not started.
        self.assertNotIn(("state", "speaking"), self.rt.emitted)
        self.assertFalse(any(k == "speech" and t == "playback_started"
                             for k, t, _ in self.rt.events))
        release.set()
        self.assertTrue(done.wait(2))
        self.assertIn(("state", "speaking"), self.rt.emitted)
        started = [json.loads(x) for k, t, x in self.rt.events
                   if k == "speech" and t == "playback_started"]
        self.assertEqual(len(started), 1)
        self.assertEqual((started[0]["turn_id"], started[0]["goal_id"]), ("t1", "g1"))
        self.assertTrue(started[0]["speech_id"])
        self.assertEqual(started[0]["voice_id"], "tr_kadin")

    def test_stage_events_never_idle_and_late_receipt_keeps_newer_speech_busy(self):
        entered, release = threading.Event(), threading.Event()

        def synth(spec, text, cancel):
            entered.set()
            self.assertTrue(release.wait(2))
            return b"audio"

        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "K", "piper", "a.onnx"),)),
            synth, lambda audio, cancel, on_start: on_start(),
        )
        voice_runtime.register(lane)
        active = lane.say("alice", "tr_kadin", "Birinci")
        self.assertTrue(entered.wait(1))
        waiting = lane.say("alice", "tr_kadin", "İkinci")
        self.assertFalse(waiting.is_set())
        # No stage event (accepted/synthesizing/audio_ready) claims idle.
        self.assertFalse(any(k == "state" and t == "idle" for k, t, _ in self.rt.events))
        # Interrupt acknowledges the pending second receipt while the first is still
        # playing: busy stays set, so the newer speech is not idled by a late receipt.
        lane.interrupt()
        self.assertTrue(waiting.wait(1))
        self.assertTrue(lane.is_busy())
        self.assertFalse(any(k == "state" and t == "idle" for k, t, _ in self.rt.events))
        release.set()
        self.assertTrue(active.wait(2))
        self.assertFalse(lane.is_busy())

    def test_stage_event_for_another_owner_is_not_presented(self):
        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "K", "piper", "a.onnx"),)),
            lambda spec, text, cancel: b"audio",
            lambda audio, cancel, on_start: on_start(),
        )
        voice_runtime.register(lane)
        done = lane.say("bob", "tr_kadin", "Başka kullanıcı")
        self.assertTrue(done.wait(2))
        self.assertFalse(any(k == "speech" for k, _, _ in self.rt.events))
        self.assertNotIn(("state", "speaking"), self.rt.emitted)

    def test_speech_for_another_owner_never_reaches_the_player(self):
        # §5: an utterance for a user who is not the active desktop profile must
        # never hit the physical speaker (not merely be hidden in the UI). The
        # pre-playback identity check is the audible boundary.
        played = []
        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "K", "piper", "a.onnx"),)),
            lambda spec, text, cancel: b"audio",
            lambda audio, cancel, on_start: (played.append(audio) or on_start()),
        )
        voice_runtime.register(lane)
        done = lane.say("bob", "tr_kadin", "Başka kullanıcı")
        self.assertTrue(done.wait(2))
        self.assertEqual(played, [])  # no audible cross-user leak
        self.assertNotIn(("state", "speaking"), self.rt.emitted)

    def test_user_switch_stops_queued_old_owner_audio_before_playback(self):
        # §5: the active user switching mid-queue must not let the previous user's
        # still-queued reply play into the new user's session, while audio that
        # already started keeps its receipt.
        started = []
        def play(audio, cancel, on_start):
            started.append(audio)
            on_start()
            if len(started) == 1:  # after the first alice utterance starts, desktop user switches
                self.rt.pc_profile = lambda: SimpleNamespace(
                    slug="bob", data={"prefs": {"voice": "tr_kadin"}})

        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "K", "piper", "a.onnx"),)),
            lambda spec, text, cancel: b"audio", play,
        )
        voice_runtime.register(lane)
        first = lane.say("alice", "tr_kadin", "Birinci")
        second = lane.say("alice", "tr_kadin", "İkinci")
        self.assertTrue(first.wait(2))
        self.assertTrue(second.wait(2))
        self.assertEqual(len(started), 1)  # only Birinci played; İkinci dropped before playback
        self.assertEqual(len([x for k, t, x in self.rt.events
                              if k == "speech" and t == "playback_started"]), 1)
        self.assertFalse(any(k == "system" for k, _m in self.rt.emitted))  # no leaked notice

    def test_handoff_with_no_speech_allows_microphone_immediately(self):
        self.assertTrue(voice_runtime.handoff_to_listen(timeout=0.05))

    def test_real_playback_registers_echo_guard_for_mic(self):
        # The living echo guard (stt_guard) must learn what Jarvis actually plays,
        # now that the legacy voice.speak note_said call is retired.
        from modules import stt_guard
        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "K", "piper", "a.onnx"),)),
            lambda spec, text, cancel: b"audio",
            lambda audio, cancel, on_start: on_start(),
        )
        voice_runtime.register(lane)
        with patch.object(stt_guard, "note_said") as note:
            done = lane.say("alice", "tr_kadin", "Paylaşımı kapattım")
            self.assertTrue(done.wait(2))
        note.assert_called_once_with("Paylaşımı kapattım")

    def test_unplayed_cancelled_speech_does_not_register_echo(self):
        # Audio interrupted before the real playback boundary never reached the
        # speaker, so it must not suppress a matching user command.
        from modules import stt_guard
        entered = threading.Event()

        def synth(spec, text, cancel):
            entered.set()
            return b"audio"

        def play(audio, cancel, on_start):
            cancel.wait(2)   # interrupted before on_start: no real playback

        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "K", "piper", "a.onnx"),)),
            synth, play,
        )
        voice_runtime.register(lane)
        with patch.object(stt_guard, "note_said") as note:
            done = lane.say("alice", "tr_kadin", "Henüz çalınmadı")
            self.assertTrue(entered.wait(1))
            lane.interrupt()
            self.assertTrue(done.wait(2))
        note.assert_not_called()

    def test_push_to_talk_handoff_cuts_speech_and_verifies_output_stopped(self):
        started, stopped = threading.Event(), threading.Event()

        def play(audio, cancel, on_start):
            started.set()
            on_start()
            cancel.wait(2)  # real player stops when the interrupt sets cancel
            stopped.set()

        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "K", "piper", "a.onnx"),)),
            lambda spec, text, cancel: b"audio", play,
        )
        voice_runtime.register(lane)
        done = lane.say("alice", "tr_kadin", "Uzun konuşma")
        self.assertTrue(started.wait(1))
        self.assertTrue(lane.is_busy())
        self.assertTrue(voice_runtime.handoff_to_listen(timeout=1.0))
        self.assertTrue(stopped.is_set())  # output acknowledged stop before mic opens
        self.assertFalse(lane.is_busy())
        self.assertTrue(done.wait(1))

    def test_handoff_keeps_protection_when_player_does_not_stop(self):
        started, release = threading.Event(), threading.Event()

        def play(audio, cancel, on_start):
            started.set()
            on_start()
            release.wait(2)  # ignores cancel: audio still playing

        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "K", "piper", "a.onnx"),)),
            lambda spec, text, cancel: b"audio", play,
        )
        voice_runtime.register(lane)
        done = lane.say("alice", "tr_kadin", "Durmayan konuşma")
        self.assertTrue(started.wait(1))
        self.assertFalse(voice_runtime.handoff_to_listen(timeout=0.1))
        self.assertTrue(lane.is_busy())  # protection kept: mic must not open yet
        release.set()
        self.assertTrue(done.wait(2))


if __name__ == "__main__":
    unittest.main()
