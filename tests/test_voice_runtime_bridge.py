"""VOICE-02A opt-in dispatch: profile identity, single output owner and audio-only stop.

All adapters and audio devices are mocked. These tests do not prove physical
speaker output or real Turkish model quality.
"""
import json
import os
import secrets
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import requests_state, voice_edge, voice_runtime
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


class CutWinmm:
    """Fake winmm whose mode is a statement about the speaker, not a script.

    ``status mode`` always answers the current mode, so the player sees a stable
    device: ``playing`` means sound is live, ``stopped`` means the speaker is
    silent. ``stop_code`` decides whether winmm accepts the cut command and
    ``after_stop`` is the mode the device reports afterwards, which is exactly
    the difference between a proven interrupt and one that was never confirmed.
    """

    def __init__(self, mode="playing", stop_code=0, after_stop=None, ends_after=None):
        self.mode = mode
        self.stop_code = stop_code
        self.after_stop = after_stop
        self.ends_after = ends_after      # status reads after which a playback ends
        self.commands = []
        self.path = None
        self._reads = 0

    def __call__(self, command, buffer, length, hwnd):
        self.commands.append(command)
        if command.startswith("open "):
            self.path = command.split('"')[1]
            return 0
        if command.startswith("stop "):
            if self.after_stop is not None:
                self.mode = self.after_stop
            return self.stop_code
        if command.startswith("status "):
            self._reads += 1
            if (self.ends_after is not None and self._reads > self.ends_after
                    and self.mode == "playing"):
                self.mode = "stopped"     # the stream reached its real end
            if buffer is not None:
                buffer.value = self.mode
            return 0
        return 0


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

    def _requests_isolated(self):
        """Speech mutes must never touch the real ~/.jarvis request journal."""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.enterContext(patch.object(requests_state, "_journal", Path(temp.name) / "requests.json"))
        saved = dict(requests_state._records)
        requests_state._records.clear()

        def restore():
            requests_state._records.clear()
            requests_state._records.update(saved)
        self.addCleanup(restore)

    def test_sus_mutes_the_stopped_turns_speech_not_the_running_request(self):
        # §6 speech scope: the answer the model finishes after "sus" must never
        # restart audio, while the request keeps running with its written result
        # and the next turn is still answered out loud.
        self._requests_isolated()
        heard = []
        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "Kadın", "piper", "a.onnx"),)),
            lambda spec, text, cancel: heard.append(text) or b"audio",
            lambda audio, cancel, on_start: on_start(),
        )
        voice_runtime.register(lane)
        from modules import voice
        self.assertTrue(requests_state.register("alice", "turn-1"))
        self.assertTrue(lane.say("alice", "tr_kadin", "İlk cevap", turn_id="turn-1").wait(2))
        voice.stop_speaking()          # the shared web/voice/phone stop entry
        self.assertTrue(requests_state.speech_muted("alice", "turn-1"))
        late = lane.say("alice", "tr_kadin", "Modelden sonra geldi", turn_id="turn-1")
        self.assertTrue(late.is_set(), "a refused utterance is acknowledged, never left waiting")
        self.assertTrue(requests_state.register("alice", "turn-2"))
        self.assertTrue(lane.say("alice", "tr_kadin", "Yeni sorunun cevabı", turn_id="turn-2").wait(2))
        self.assertEqual(heard, ["İlk cevap", "Yeni sorunun cevabı"])
        self.assertFalse(requests_state.is_cancelled("alice", "turn-1"),
                         '"sus" is a mute, not a task cancel')
        self.assertFalse(any(kind == "system" for kind, _ in self.rt.emitted),
                         "quiet was requested; a muted turn must not complain about itself")

    def test_sus_stops_the_remaining_chunks_of_an_utterance_already_playing(self):
        # An answer cut mid-sentence must not synthesize or play its next chunk;
        # the cooperative cancel is what bounds it, verified through the real
        # shared stop entry rather than a mock of the worker.
        self._requests_isolated()
        heard = []
        started = threading.Event()
        release = threading.Event()

        def synth(spec, text, cancel):
            heard.append(text)
            started.set()
            self.assertTrue(release.wait(2))
            return b"audio"

        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "Kadın", "piper", "a.onnx"),)),
            synth, lambda audio, cancel, on_start: on_start(),
        )
        voice_runtime.register(lane)
        from modules import voice
        self.assertTrue(requests_state.register("alice", "turn-1"))
        first = lane.say("alice", "tr_kadin", "Birinci cümle. " + ("dolgu " * 200), turn_id="turn-1")
        self.assertTrue(started.wait(1))
        voice.stop_speaking()
        release.set()
        self.assertTrue(first.wait(2))
        self.assertEqual(len(heard), 1, "the stopped turn never synthesizes its remaining chunk")

    def test_sus_keeps_the_other_jobs_later_spoken_result_while_muting_its_own(self):
        # Two independent jobs run for the same user. Jarvis is speaking job A's
        # answer when "sus" is said. The mute belongs to that speech and to its
        # late audio only: job B, which the voice owner was never given, keeps the
        # spoken result it will send later. Verified through the shared stop entry
        # and the real lane/queue, not through a mock of the stop itself.
        self._requests_isolated()
        heard = []
        started = threading.Event()
        release = threading.Event()

        def synth(spec, text, cancel):
            heard.append(text)
            started.set()
            self.assertTrue(release.wait(2))
            return b"audio"

        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "Kadın", "piper", "a.onnx"),)),
            synth, lambda audio, cancel, on_start: on_start(),
        )
        voice_runtime.register(lane)
        from modules import voice
        self.assertTrue(requests_state.register("alice", "turn-A"))
        self.assertTrue(requests_state.register("alice", "job-B"))
        first = lane.say("alice", "tr_kadin", "A işinin cevabı", turn_id="turn-A")
        self.assertTrue(started.wait(1))
        voice.stop_speaking()
        release.set()
        self.assertTrue(first.wait(2))
        self.assertTrue(requests_state.speech_muted("alice", "turn-A"))
        self.assertFalse(requests_state.speech_muted("alice", "job-B"),
                         'the other job\'s future spoken result is not muted by "sus"')
        self.assertFalse(requests_state.is_cancelled("alice", "job-B"),
                         '"sus" cancels no Core work')
        late = lane.say("alice", "tr_kadin", "A'nın modelden sonra biten cevabı", turn_id="turn-A")
        self.assertTrue(late.is_set(), "a refused utterance is acknowledged, never left waiting")
        notice = lane.say("alice", "tr_kadin", "B işinin sonraki bildirimi",
                          turn_id="job-B", background=True)
        self.assertTrue(notice.wait(2))
        self.assertEqual(heard, ["A işinin cevabı", "B işinin sonraki bildirimi"],
                         "the stopped turn stays silent and the other job is still heard")

    def test_sus_mutes_the_turn_whose_request_finished_while_its_audio_was_playing(self):
        # The normal answer flow marks the request done while its audio is still on
        # the speaker, so the mute cannot depend on the request lifecycle: "sus"
        # arriving mid-utterance mutes that turn by identity even when the record
        # already says done. A later utterance of the same turn then stays silent,
        # while another finished job keeps its own spoken result.
        self._requests_isolated()
        heard = []
        started = threading.Event()
        release = threading.Event()

        def synth(spec, text, cancel):
            heard.append(text)
            started.set()
            self.assertTrue(release.wait(2))
            return b"audio"

        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "Kadın", "piper", "a.onnx"),)),
            synth, lambda audio, cancel, on_start: on_start(),
        )
        voice_runtime.register(lane)
        from modules import voice
        for rid in ("turn-A", "job-B"):
            self.assertTrue(requests_state.register("alice", rid))
            with requests_state.activate("alice", rid):
                pass                       # the handler returned; the record is 'done'
        first = lane.say("alice", "tr_kadin", "Bitmiş cevabın sesi", turn_id="turn-A")
        self.assertTrue(started.wait(1))
        voice.stop_speaking()              # "sus" while the finished answer is audible
        release.set()
        self.assertTrue(first.wait(2))
        self.assertTrue(requests_state.speech_muted("alice", "turn-A"),
                        '"sus" mutes the turn it stopped even after its request completed')
        late = lane.say("alice", "tr_kadin", "Aynı turun geciken sesi", turn_id="turn-A")
        self.assertTrue(late.is_set(), "the refused utterance is acknowledged, never left waiting")
        notice = lane.say("alice", "tr_kadin", "B işinin bildirimi", turn_id="job-B",
                          background=True)
        self.assertTrue(notice.wait(2))
        self.assertEqual(heard, ["Bitmiş cevabın sesi", "B işinin bildirimi"],
                         "the stopped turn is silent, the other finished job is still heard")
        self.assertFalse(requests_state.is_cancelled("alice", "turn-A"),
                         '"sus" still cancels no Core work, finished or not')

    def test_sus_never_mutes_a_request_the_lane_was_never_given(self):
        # Nothing had reached the speaker yet, so there is no speech to mute: the
        # mute scope cannot be extended to a request the voice owner never saw.
        self._requests_isolated()
        heard = []
        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "Kadın", "piper", "a.onnx"),)),
            lambda spec, text, cancel: heard.append(text) or b"audio",
            lambda audio, cancel, on_start: on_start(),
        )
        voice_runtime.register(lane)
        from modules import voice
        self.assertTrue(requests_state.register("alice", "job-B"))
        voice.stop_speaking()
        self.assertFalse(requests_state.speech_muted("alice", "job-B"))
        self.assertTrue(lane.say("alice", "tr_kadin", "B işinin bildirimi",
                                 turn_id="job-B", background=True).wait(2))
        self.assertEqual(heard, ["B işinin bildirimi"])

    def test_voice_session_never_calls_legacy_speech_when_lane_enabled(self):
        lane = Mock()
        result = threading.Event()
        lane.say.return_value = result
        rt = self.rt
        rt.threading = SimpleNamespace(Thread=Mock())
        rt.voice = SimpleNamespace(speak=Mock())
        session = VoiceSession.__new__(VoiceSession)
        session.runtime, session.speak_enabled = rt, True
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
        session.runtime, session.speak_enabled = rt, True
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
        session.runtime, session.speak_enabled = rt, True
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

    def test_owner_switch_cancels_started_playback_at_the_real_player(self):
        # §4-A: the previous user's speech that had ALREADY begun must be stopped
        # at the real player when the desktop user switches, and their queued
        # audio must drop too. This exercises the coordinator, the lane owner
        # bookkeeping and on_owner_switch together — not a mock's own behavior.
        began = threading.Event()
        started = []
        def play(audio, cancel, on_start):
            started.append(audio)
            on_start()
            began.set()             # the real player has actually started
            cancel.wait(2)          # a real MCI stream blocks until stop is honored

        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "K", "piper", "a.onnx"),)),
            lambda spec, text, cancel: b"audio", play,
        )
        voice_runtime.register(lane)
        first = lane.say("alice", "tr_kadin", "Birinci")      # starts playing and blocks
        self.assertTrue(began.wait(2))                        # switch only after real start
        second = lane.say("alice", "tr_kadin", "İkinci")      # queued behind the blocked first
        self.assertTrue(lane.outstanding_owner("alice"))
        self.rt.pc_profile = lambda: SimpleNamespace(slug="bob", data={"prefs": {}})
        self.assertTrue(voice_runtime.on_owner_switch("alice", timeout=2))  # verified stop
        self.assertTrue(first.wait(2))
        self.assertTrue(second.wait(2))
        self.assertEqual(started, [b"audio"])                 # the old audio never resumed
        self.assertFalse(lane.outstanding_owner("alice"))     # every prior utterance acknowledged
        self.assertFalse(any(k == "system" for k, _m in self.rt.emitted))  # no leak notice to bob

    def test_handoff_with_no_speech_allows_microphone_immediately(self):
        self.assertTrue(voice_runtime.handoff_to_listen(timeout=0.05))

    def test_full_notice_queue_still_answers_the_current_user(self):
        # §4-C: background notifications used to occupy every bounded slot, so the
        # user's actual question was refused with VOICE_QUEUE_FULL and the
        # preemption never happened. The queue bound is kept: the stalest waiting
        # notice gives up only its AUDIO (its written result stays Core's), the
        # question is answered, and no phony user-facing notice is emitted.
        release = threading.Event()
        began = threading.Event()

        def play(audio, cancel, on_start):
            on_start()
            began.set()                 # the real player owns the output now
            self.assertTrue(release.wait(2))

        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "K", "piper", "a.onnx"),)),
            lambda spec, text, cancel: b"audio", play,
        )
        voice_runtime.register(lane)
        talking = lane.say("alice", "tr_kadin", "Konuşma")
        self.assertTrue(began.wait(2))
        notices = [lane.say("alice", "tr_kadin", f"Bildirim {i}", background=True,
                            kind="progress", goal_id="g1") for i in range(8)]
        question = lane.say("alice", "tr_kadin", "Şu anki soru")
        self.assertTrue(notices[0].wait(2))   # the dropped notice is acknowledged, not lost
        self.assertFalse(any(k == "system" for k, _m in self.rt.emitted))
        release.set()
        self.assertTrue(talking.wait(2))
        self.assertTrue(question.wait(2))
        self.assertTrue(all(done.wait(2) for done in notices[1:]))
        self.assertFalse(lane.is_busy())      # nothing sticks the mic handoff

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

    def test_reminder_producer_names_the_result_it_announces(self):
        # §7: the notice that asks for speech says which record it announces, so
        # currency, duplicate delivery and invalidation all have a real identity.
        from modules import engine_background
        events = []
        profile = SimpleNamespace(slug="alice", data={"prefs": {}},
                                  due_events=lambda now: [{"id": 7, "title": "İlaç",
                                                           "fired": "2026-11-12T09:00"}])
        stub = SimpleNamespace(
            list_users=lambda: ["alice"], _get_profile=lambda name: profile,
            datetime=SimpleNamespace(now=lambda: None), _emit_for=lambda *a, **k: None,
            pc_profile=lambda: profile, threading=SimpleNamespace(Thread=Mock()),
            notify=Mock(), events=SimpleNamespace(put=events.append),
        )
        engine_background._reminder_tick(stub)
        self.assertEqual(events, [("say", "Hatırlatma: İlaç", "alice", {
            "kind": "reminder", "event_id": "reminder:7",
            "turn_id": "reminder:7@2026-11-12T09:00",
            "ttl_seconds": engine_background.REMINDER_SPEECH_TTL_SECONDS})])

    def test_a_queued_reminder_is_dropped_when_the_user_deletes_the_record(self):
        # §7 invalidation now has a production caller: the planner that changes
        # the calendar record drops only that record's waiting audio, and the
        # utterance already playing keeps going.
        entered, release = threading.Event(), threading.Event()
        heard = []

        def synth(spec, text, cancel):
            heard.append(text)
            if text == "uzun yanıt":
                entered.set()
                self.assertTrue(release.wait(2))
            return b"audio"

        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "Kadın", "piper", "a.onnx"),)),
            synth, lambda audio, cancel, on_start: on_start(),
        )
        voice_runtime.register(lane)
        from modules import engine_background, main_planner
        record = {"id": 7, "title": "İlaç", "fired": "2026-11-12T09:00"}
        first = lane.say("alice", "tr_kadin", "uzun yanıt")
        self.assertTrue(entered.wait(1))
        queued = lane.say("alice", "tr_kadin", "Hatırlatma: İlaç", background=True,
                          kind="reminder",
                          event_id=engine_background.reminder_speech_id(record),
                          turn_id=engine_background.reminder_occurrence_id(record))
        main_planner._drop_queued_reminder_speech(self.rt, record)
        release.set()
        self.assertTrue(first.wait(2))
        self.assertTrue(queued.wait(2))
        self.assertEqual(heard, ["uzun yanıt"])

    def test_the_same_reminder_is_never_announced_twice_out_loud(self):
        # A second tick or a retry for the same record must not reach the
        # speaker again; the user already heard it, so nothing is complained about.
        heard = []
        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "Kadın", "piper", "a.onnx"),)),
            lambda spec, text, cancel: heard.append(text) or b"audio",
            lambda audio, cancel, on_start: on_start(),
        )
        voice_runtime.register(lane)
        session = VoiceSession.__new__(VoiceSession)
        session.runtime, session.speak_enabled = self.rt, True
        session.voice_lane, session.voice_core_fault = lane, None
        # Barge-in watching needs the real wake-word listener; this test is about
        # what reaches the speaker, so it is not started here.
        self.enterContext(patch.object(VoiceSession, "_barge_watch", Mock()))
        identity = {"kind": "reminder", "event_id": "reminder:7"}
        session.speak("Hatırlatma: İlaç", shown=True, identity=identity)
        deadline = time.monotonic() + 2
        while lane.is_busy() and time.monotonic() < deadline:
            time.sleep(0.01)
        session.speak("Hatırlatma: İlaç", shown=True, identity=identity)
        self.assertEqual(heard, ["Hatırlatma: İlaç"])
        self.assertFalse(lane.is_busy())
        self.assertFalse(any(kind == "system" for kind, _ in self.rt.emitted))

    def _reminder_owner(self, name="Alice"):
        """A real Profile as the audible desktop user, in an isolated user store."""
        from modules import personalization
        users = Path(self.temp.name) / "users"
        users.mkdir(exist_ok=True)
        self.enterContext(patch.object(personalization, "USERS_DIR", users))
        profile = personalization.Profile(name)
        profile.data["prefs"]["voice"] = "tr_kadin"
        self.rt.profile = profile
        self.rt.pc_profile = lambda: profile
        return profile

    def _reminder_chain(self, clock):
        """The real reminder pipeline with only the synthesizer and player replaced.

        ``Profile.due_events`` → ``engine_background._reminder_tick`` →
        ``('say', text, owner, identity)`` → ``VoiceSession.speak`` → ``VoiceLane`` →
        ``VoiceCoordinator``, which is exactly how ``engine_loop`` dispatches a queued
        event. The record/occurrence identity that reaches the speaker is therefore
        produced by the production code, not by the test.
        """
        from modules import engine_background
        from modules.engine_voice import VoiceSession
        heard = []
        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "Kadın", "piper", "a.onnx"),)),
            lambda spec, text, cancel: heard.append(text) or b"audio",
            lambda audio, cancel, on_start: on_start(),
        )
        voice_runtime.register(lane)
        session = VoiceSession.__new__(VoiceSession)
        session.runtime, session.speak_enabled = self.rt, True
        session.voice_lane, session.voice_core_fault = lane, None
        self.enterContext(patch.object(VoiceSession, "_barge_watch", Mock()))
        events = []
        stub = SimpleNamespace(
            list_users=lambda: [self.rt.profile.name],
            _get_profile=lambda name: self.rt.profile,
            datetime=SimpleNamespace(now=clock), _emit_for=lambda *a, **k: None,
            pc_profile=lambda: self.rt.pc_profile(),
            threading=SimpleNamespace(Thread=Mock()),
            notify=Mock(), events=SimpleNamespace(put=events.append),
        )

        def ring(replayed=None):
            arrivals = replayed
            if arrivals is None:
                events.clear()
                engine_background._reminder_tick(stub)
                arrivals = list(events)
            for _kind, text, _owner, identity in arrivals:
                session.speak(text, shown=True, identity=dict(identity))
            deadline = time.monotonic() + 2
            while lane.is_busy() and time.monotonic() < deadline:
                time.sleep(0.01)
            return arrivals

        return ring, heard, lane

    @staticmethod
    def _daily(profile, when="2026-11-12T09:00", repeat="daily"):
        profile.data["events"].append({"id": 7, "title": "İlaç", "when": when,
                                       "notified": False, "repeat": repeat})

    def test_the_next_day_of_a_repeating_reminder_is_still_heard_out_loud(self):
        # Record identity and occurrence identity are separate on purpose: the
        # calendar keeps one id for a daily record, so an identity built from the
        # record alone makes tomorrow's ring a duplicate of the one already heard.
        from datetime import datetime
        now = datetime(2026, 11, 12, 9, 0)
        profile = self._reminder_owner()
        self._daily(profile)
        ring, heard, lane = self._reminder_chain(lambda: now)
        first = ring()
        self.assertEqual(["Hatırlatma: İlaç"], heard)
        now = datetime(2026, 11, 13, 9, 0)
        second = ring()
        self.assertEqual(["Hatırlatma: İlaç"] * 2, heard)   # not a duplicate of yesterday
        # The same record on a weekly rule: a repeating record only ever stores its
        # next ring, so this is the state a weekly record has on its own day.
        now = datetime(2026, 11, 19, 9, 0)
        profile.data["events"][0].update(
            repeat=f"weekly:{datetime(2026, 11, 19).weekday()}", when="2026-11-19T09:00")
        third = ring()
        self.assertEqual(["Hatırlatma: İlaç"] * 3, heard)
        # What carried each of those deliveries: the record stays the same, the
        # occurrence is what duplicate protection sees.
        self.assertEqual("reminder:7", first[0][3]["event_id"])
        self.assertEqual(["reminder:7@2026-11-12T09:00", "reminder:7@2026-11-13T09:00",
                          "reminder:7@2026-11-19T09:00"],
                         [event[0][3]["turn_id"] for event in (first, second, third)])
        self.assertFalse(lane.is_busy())

    def test_one_occurrence_is_never_announced_twice_even_when_replayed(self):
        # The other half of the split: replaying the very same occurrence is still
        # one delivery, and it does not depend on the delivered-result memory
        # having forgotten anything.
        from datetime import datetime
        now = datetime(2026, 11, 12, 9, 0)
        profile = self._reminder_owner()
        self._daily(profile)
        ring, heard, lane = self._reminder_chain(lambda: now)
        first = ring()
        ring(replayed=first)
        ring(replayed=first)
        self.assertEqual(["Hatırlatma: İlaç"], heard)
        self.assertFalse(any(kind == "system" for kind, _ in self.rt.emitted))
        self.assertFalse(lane.is_busy())

    def test_a_snoozed_and_a_moved_occurrence_are_each_heard(self):
        from datetime import datetime
        now = datetime(2026, 11, 12, 9, 0)
        profile = self._reminder_owner()
        self._daily(profile)
        ring, heard, lane = self._reminder_chain(lambda: now)
        ring()
        self.assertEqual(["Hatırlatma: İlaç"], heard)
        profile.snooze_event(7, "2026-11-12T09:30")    # "10 dakika sonra tekrar hatırla"
        now = datetime(2026, 11, 12, 9, 30)
        snoozed = ring()
        self.assertEqual(["Hatırlatma: İlaç"] * 2, heard)
        self.assertEqual("reminder:7@2026-11-12T09:30", snoozed[0][3]["turn_id"])
        profile.reschedule_event(7, "2026-11-12T11:00")  # "saat 11'e çek"
        now = datetime(2026, 11, 12, 11, 0)
        moved = ring()
        self.assertEqual(["Hatırlatma: İlaç"] * 3, heard)
        self.assertEqual("reminder:7@2026-11-12T11:00", moved[0][3]["turn_id"])
        self.assertFalse(lane.is_busy())

    def test_two_users_with_the_same_record_id_are_each_announced(self):
        # Record ids are per-profile, so Bob's record 7 can carry Alice's exact id
        # and title. Alice having heard hers cannot mark Bob's as already delivered.
        from datetime import datetime
        from modules import personalization
        now = datetime(2026, 11, 12, 9, 0)
        alice = self._reminder_owner("Alice")
        self._daily(alice)
        ring, heard, lane = self._reminder_chain(lambda: now)
        ring()
        self.assertEqual(["Hatırlatma: İlaç"], heard)
        bob = personalization.Profile("Bob")
        bob.data["prefs"]["voice"] = "tr_kadin"
        self._daily(bob)                                # same id, same title, same time
        self.rt.profile = bob
        self.rt.pc_profile = lambda: bob
        self.assertTrue(voice_runtime.on_owner_switch("alice", timeout=1))
        own = ring()
        self.assertEqual(["Hatırlatma: İlaç"] * 2, heard)   # Bob hears his own reminder
        self.assertEqual("reminder:7@2026-11-12T09:00", own[0][3]["turn_id"])
        self.assertFalse(any(kind == "system" for kind, _ in self.rt.emitted))

    def test_a_reminder_drop_selects_the_users_own_record_only(self):
        # Same record id and sentence for two users: the correction one of them
        # makes may only discard that user's queued audio, never the other's.
        entered, release = threading.Event(), threading.Event()
        heard = []

        def synth(spec, text, cancel):
            heard.append(text)
            if text == "uzun yanıt":
                entered.set()
                self.assertTrue(release.wait(2))
            return b"audio"

        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "Kadın", "piper", "a.onnx"),)),
            synth, lambda audio, cancel, on_start: on_start(),
        )
        voice_runtime.register(lane)
        from modules import engine_background, main_planner
        record = {"id": 7, "title": "İlaç", "fired": "2026-11-12T09:00"}
        identity = {"kind": "reminder",
                    "event_id": engine_background.reminder_speech_id(record),
                    "turn_id": engine_background.reminder_occurrence_id(record)}
        first = lane.say("alice", "tr_kadin", "uzun yanıt")   # holds the worker
        self.assertTrue(entered.wait(1))
        alices = lane.say("alice", "tr_kadin", "Hatırlatma: İlaç", background=True, **identity)
        self.rt.profile = SimpleNamespace(slug="bob", data={"prefs": {"voice": "tr_kadin"}})
        self.rt.pc_profile = lambda: self.rt.profile
        bobs = lane.say("bob", "tr_kadin", "Hatırlatma: İlaç", background=True, **identity)
        self.assertEqual(1, main_planner._drop_queued_reminder_speech(self.rt, record))
        # The pre-fix selector (record id alone) sees the other user's item too,
        # which is exactly what Bob's correction must not do.
        self.assertEqual(1, voice_runtime.invalidate(event_id=identity["event_id"],
                                                     turn_id=identity["turn_id"]))
        release.set()
        self.assertTrue(first.wait(2))
        self.assertTrue(alices.wait(2))
        self.assertTrue(bobs.wait(2))
        self.assertEqual(["uzun yanıt"], heard)

    def test_a_player_that_ignores_cancel_still_cannot_reach_the_new_user(self):
        # §4-A with the uncooperative player the review asked for: the stop is not
        # claimed when the device never honours cancel, and while the old chunk is
        # still in the speaker no further audio of the previous user can start.
        began, release = threading.Event(), threading.Event()
        started = []

        def play(audio, cancel, on_start):
            started.append(audio)
            on_start()
            began.set()
            release.wait(3)     # ignores cancel: a wedged stream, as on a real device

        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "K", "piper", "a.onnx"),)),
            lambda spec, text, cancel: b"audio", play,
        )
        voice_runtime.register(lane)
        first = lane.say("alice", "tr_kadin", "Birinci")
        self.assertTrue(began.wait(2))
        second = lane.say("alice", "tr_kadin", "İkinci")
        self.rt.pc_profile = lambda: SimpleNamespace(slug="bob", data={"prefs": {}})
        with patch.object(voice_runtime, "_record_failure") as failure:
            self.assertFalse(voice_runtime.on_owner_switch("alice", timeout=0.05))
        failure.assert_called_once_with("modules/voice_runtime.py:owner_switch_stop")
        self.assertEqual([b"audio"], started)     # nothing new reached the speaker
        release.set()
        self.assertTrue(first.wait(2))
        self.assertTrue(second.wait(2))
        self.assertEqual([b"audio"], started)     # the wedged chunk was the last of it

    def test_the_new_users_greeting_never_mixes_with_the_unstopped_old_audio(self):
        # The review's remaining boundary: if the device ignores the stop signal,
        # the previous user's audio in the speaker is NOT claimed to be cut. What
        # is proven here is the safety that still holds without that claim: the one
        # output worker never plays the new user's greeting over it, and no further
        # chunk of the previous user's utterance starts after the switch.
        began, release = threading.Event(), threading.Event()
        playing, overlap, threads = [], [], []
        guard = threading.Lock()

        def play(audio, cancel, on_start):
            threads.append(threading.current_thread().name)
            with guard:
                if playing:
                    overlap.append(list(playing))   # two utterances on the device at once
                playing.append(audio)
            on_start()
            if audio == b"eski":
                began.set()
                release.wait(3)                    # ignores cancel, like a wedged device
            with guard:
                playing.remove(audio)

        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "K", "piper", "a.onnx"),)),
            lambda spec, text, cancel: b"eski" if text.startswith("Alice") else b"yeni",
            play,
        )
        voice_runtime.register(lane)
        old = lane.say("alice", "tr_kadin", "Alice konuşuyor")
        self.assertTrue(began.wait(2))
        self.rt.pc_profile = lambda: SimpleNamespace(slug="bob", data={"prefs": {}})
        self.rt.profile = SimpleNamespace(slug="bob", data={"prefs": {"voice": "tr_kadin"}})
        with patch.object(voice_runtime, "_record_failure") as failure:
            stopped = voice_runtime.on_owner_switch("alice", timeout=0.05)
        self.assertFalse(stopped, "the unverified device cut is never reported as done")
        greeting = lane.say("bob", "tr_kadin", "Merhaba Bob", turn_id="bob-greeting")
        time.sleep(0.05)
        self.assertEqual(playing, [b"eski"], "the greeting waits behind the uncut audio")
        self.assertFalse(greeting.is_set(), "no new speech starts while the device is stuck")
        release.set()
        self.assertTrue(old.wait(2))
        self.assertTrue(greeting.wait(2))
        self.assertEqual(overlap, [], "one output owner never mixes two users' audio")
        self.assertEqual(set(threads), {"jarvis-voice-output"},
                         "both utterances played on the single production output worker")
        self.assertFalse(lane.is_busy())

    def test_a_same_turn_answer_arriving_after_the_cut_is_still_cut(self):
        # The window between the drain and the mute: a late answer for the turn the
        # user just stopped is enqueued inside it, so it carries the new generation
        # and the mute is not yet visible to it. The turn-targeted drop after the
        # mute is what stops the audio that already started.
        began, stopped = threading.Event(), []
        in_window = threading.Event()
        arriving = []

        def synth(spec, text, cancel):
            return b"ilk" if text.startswith("Turun") else b"gec"

        def play(audio, cancel, on_start):
            on_start()
            if audio == b"gec":
                began.set()
                stopped.append(cancel.wait(2))  # the cooperative player honours cancel

        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "Kadın", "piper", "a.onnx"),)),
            synth, play,
        )
        voice_runtime.register(lane)
        from modules import requests_state
        done = lane.say("alice", "tr_kadin", "Turun ilk konuşması", turn_id="t1")
        self.assertTrue(done.wait(2))          # t1 is the turn this owner last heard
        real_mute = requests_state.mute_speech

        def mute_in_the_window(user, rid=None):
            if not in_window.is_set() and rid == "t1":
                in_window.set()
                arriving.append(
                    lane.say(user, "tr_kadin", "Aynı turun geciken yanıtı", turn_id="t1"))
                self.assertTrue(began.wait(2))  # it is already at the real player
                return real_mute(user, rid)
            return real_mute(user, rid)

        with patch.object(requests_state, "mute_speech", side_effect=mute_in_the_window):
            self.assertTrue(voice_runtime.interrupt_active())
        deadline = time.monotonic() + 2
        while lane.is_busy() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(in_window.is_set())        # the answer really arrived inside the cut
        self.assertTrue(arriving[0].wait(2))       # acknowledged, never silently lost
        self.assertEqual([True], stopped)        # the stop reached the audio in progress
        self.assertFalse(lane.is_busy())

    def test_sus_without_the_late_answer_leaves_nothing_to_cut(self):
        # Control for the window test above: the same stop with no answer arriving
        # inside it cuts nothing and stays quiet.
        stopped = []
        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "Kadın", "piper", "a.onnx"),)),
            lambda spec, text, cancel: b"audio",
            lambda audio, cancel, on_start: (on_start(), stopped.append(cancel.wait(0.2))),
        )
        voice_runtime.register(lane)
        done = lane.say("alice", "tr_kadin", "Konuşma", turn_id="t1")
        self.assertTrue(done.wait(2))
        self.assertEqual([False], stopped)
        self.assertTrue(voice_runtime.interrupt_active())
        self.assertEqual([False], stopped)
        self.assertFalse(lane.is_busy())

    def cut_lane(self, mci):
        """A lane whose speech runs on the production EdgePlayer against fake winmm."""
        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "K", "edge", "tr-TR-EmelNeural"),)),
            lambda spec, text, cancel: b"mp3",
            voice_edge.EdgePlayer(poll_seconds=0, grace_seconds=0.05,
                                  wait_seconds=1.0, stop_verify_seconds=0.1),
        )
        voice_runtime.register(lane)
        self.enterContext(patch.object(voice_edge, "_mci_send", return_value=mci))
        return lane

    def say_and_hear(self, lane, text):
        done = lane.say("alice", "tr_kadin", text)
        deadline = time.monotonic() + 2
        while ("state", "speaking") not in self.rt.emitted and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIn(("state", "speaking"), self.rt.emitted)   # real playback boundary
        return done

    def test_cut_the_device_never_confirms_keeps_the_mic_protected(self):
        # §P1 end-to-end: the user says "sus", MCI refuses the stop and still
        # reports "playing", so sound is live on the speaker. The old code filed a
        # user interrupt, opened the microphone over that audio and told the UI it
        # was idle. Now the receipt says the cut failed, the notice is written, the
        # mic stays closed and no idle is claimed; the queue itself is still freed,
        # so nothing is locked and no Core work is touched.
        mci = CutWinmm(stop_code=263, after_stop="playing")
        lane = self.cut_lane(mci)
        done = self.say_and_hear(lane, "Kesilmeyi reddeden ses")
        lane.interrupt()
        self.assertTrue(done.wait(2))
        self.assertIn("stop jarvis_tts", mci.commands)          # the cut was asked for
        self.assertFalse(lane.is_busy())                        # worker/queue not stuck
        self.assertTrue(lane.stop_unconfirmed())
        self.assertFalse(voice_runtime.handoff_to_listen(timeout=0.2))  # mic stays protected
        self.assertNotIn(("state", "idle"), self.rt.emitted)    # no silence claim
        self.assertTrue(any(k == "system" and "kesilemedi" in m for k, m in self.rt.emitted))

    def test_confirmed_cut_still_frees_the_mic_and_claims_idle(self):
        # The protection must not become a permanent lock: when the device does
        # report silence after the stop, the same flow hands the microphone over
        # and the orb goes idle exactly as before.
        mci = CutWinmm(stop_code=0, after_stop="stopped")
        lane = self.cut_lane(mci)
        done = self.say_and_hear(lane, "Kesilebilen ses")
        lane.interrupt()
        self.assertTrue(done.wait(2))
        self.assertFalse(lane.stop_unconfirmed())
        self.assertTrue(voice_runtime.handoff_to_listen(timeout=0.5))
        self.assertIn(("state", "idle"), self.rt.emitted)

    def test_next_playback_that_ends_clears_an_unconfirmed_cut(self):
        # The flag describes the newest word about the speaker, not a latch: a
        # following utterance that provably ends must restore the normal mic and
        # idle behaviour, or one driver fault would keep Jarvis deaf forever.
        lane = self.cut_lane(CutWinmm(stop_code=263, after_stop="playing"))
        done = self.say_and_hear(lane, "Kesilmedi")
        lane.interrupt()
        self.assertTrue(done.wait(2))
        self.assertTrue(lane.stop_unconfirmed())
        self.assertFalse(voice_runtime.handoff_to_listen(timeout=0.2))
        # The next utterance plays and the device reports the end on its own.
        self.enterContext(patch.object(voice_edge, "_mci_send",
                                       return_value=CutWinmm(ends_after=2)))
        self.assertTrue(lane.say("alice", "tr_kadin", "Sonraki yanıt").wait(2))
        self.assertFalse(lane.stop_unconfirmed())
        self.assertTrue(voice_runtime.handoff_to_listen(timeout=0.5))

    def test_unstarted_mci_playback_is_a_failed_receipt_not_a_spoken_answer(self):
        # §4-D at the real user flow: the production EdgePlayer runs against a
        # winmm that accepts "play" but never reports "playing". The utterance
        # must never be filed as played, the UI must never claim speaking, the
        # written result must survive with an honest notice, no other voice may
        # be tried, and the single worker must not stay busy (mic handoff works).
        from modules import voice_edge

        class NeverPlayingWinmm:
            def __init__(self):
                self.path = None

            def __call__(self, command, buffer, length, hwnd):
                if command.startswith("open "):
                    self.path = command.split('"')[1]
                if command.startswith("status ") and buffer is not None:
                    buffer.value = "stopped"
                return 0

        winmm = NeverPlayingWinmm()
        synthesis = []
        lane = voice_runtime.VoiceLane(
            self.rt, VoiceCatalog((VoiceSpec("tr_kadin", "K", "edge", "tr-TR-EmelNeural"),)),
            lambda spec, text, cancel: synthesis.append(text) or b"mp3",
            voice_edge.EdgePlayer(poll_seconds=0, grace_seconds=0.05, wait_seconds=1.0),
        )
        voice_runtime.register(lane)
        with patch.object(voice_edge, "_mci_send", return_value=winmm):
            done = lane.say("alice", "tr_kadin", "Ses hiç başlamadı")
            self.assertTrue(done.wait(2))
        self.assertEqual(synthesis, ["Ses hiç başlamadı"])   # the exact voice was tried once
        self.assertNotIn(("state", "speaking"), self.rt.emitted)  # never claimed as speaking
        self.assertTrue(any("üretilemedi" in message for _k, message in self.rt.emitted))
        self.assertEqual([t for k, t, _x in self.rt.events if k == "speech"],
                         ["accepted", "synthesizing", "audio_ready"])  # no playback_started
        self.assertFalse(lane.is_busy())
        self.assertTrue(voice_runtime.handoff_to_listen(timeout=0.5))
        self.assertFalse(os.path.exists(winmm.path))         # temp file released on the error path


if __name__ == "__main__":
    unittest.main()
