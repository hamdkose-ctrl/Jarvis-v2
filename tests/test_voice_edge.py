"""Exact-voice Edge adapter inside the single coordinator; no network or real audio.

These tests prove the adapter contract (immutable identity, cooperative cancel,
real MCI playback boundary, temp-file cleanup), not human-audible Windows output.
"""
import ctypes
import os
import re
import sys
import threading
import types
import unittest
from unittest.mock import patch

from modules import voice_edge
from modules.voice_core import VoiceSpec


def edge_spec(rate=0, name="tr-TR-EmelNeural"):
    return VoiceSpec("tr_kadin", "Defne · Türkçe", "edge", name, speaking_rate=rate)


def fake_edge_module(communicate):
    module = types.ModuleType("edge_tts")
    module.Communicate = communicate
    return module


class EdgeSynthesizerTests(unittest.TestCase):
    def test_exact_voice_and_rate_are_snapshotted_not_substituted(self):
        seen = {}

        class Communicate:
            def __init__(self, text, voice, rate=None, pitch=None):
                seen["text"], seen["voice"], seen["rate"] = text, voice, rate
                seen["pitch"] = pitch

            def stream(self):
                async def gen():
                    yield {"type": "audio", "data": b"mp3-a"}
                    yield {"type": "audio", "data": b"mp3-b"}
                    yield {"type": "WordBoundary", "data": None}
                return gen()

        with patch.dict(sys.modules, {"edge_tts": fake_edge_module(Communicate)}):
            audio = voice_edge.EdgeSynthesizer()(edge_spec(rate=-12), "Merhaba", threading.Event())
        self.assertEqual(audio, b"mp3-amp3-b")
        # Düz kelime: ton eklenmez, kullanıcının hızı aynen kalır.
        self.assertEqual(seen, {"text": "Merhaba", "voice": "tr-TR-EmelNeural",
                                "rate": "-12%", "pitch": "+0Hz"})

    def test_cancel_mid_stream_returns_empty_without_finishing_download(self):
        cancel = threading.Event()
        reached = []

        class Communicate:
            def __init__(self, text, voice, rate=None, pitch=None):
                pass

            def stream(self):
                async def gen():
                    yield {"type": "audio", "data": b"first"}
                    cancel.set()
                    yield {"type": "audio", "data": b"second"}
                    reached.append("third")
                    yield {"type": "audio", "data": b"third"}
                return gen()

        with patch.dict(sys.modules, {"edge_tts": fake_edge_module(Communicate)}):
            audio = voice_edge.EdgeSynthesizer()(edge_spec(), "Metin", cancel)
        self.assertEqual(audio, b"")
        self.assertEqual(reached, [])

    def test_already_cancelled_does_not_open_the_service(self):
        cancel = threading.Event()
        cancel.set()

        class Communicate:
            def __init__(self, *args, **kwargs):
                raise AssertionError("must not contact Edge when cancelled")

        with patch.dict(sys.modules, {"edge_tts": fake_edge_module(Communicate)}):
            self.assertEqual(voice_edge.EdgeSynthesizer()(edge_spec(), "Metin", cancel), b"")

    def test_non_edge_spec_is_refused(self):
        spec = VoiceSpec("tr_kadin", "K", "piper", "a.onnx")
        with self.assertRaises(voice_edge.EdgeVoiceUnavailable):
            voice_edge.EdgeSynthesizer()(spec, "Metin", threading.Event())

    def test_service_error_raises_without_selecting_another_voice(self):
        class Communicate:
            def __init__(self, text, voice, rate=None, pitch=None):
                pass

            def stream(self):
                async def gen():
                    raise OSError("network down")
                    yield  # pragma: no cover
                return gen()

        with patch.dict(sys.modules, {"edge_tts": fake_edge_module(Communicate)}):
            with self.assertRaises(voice_edge.EdgeVoiceUnavailable):
                voice_edge.EdgeSynthesizer()(edge_spec(), "Metin", threading.Event())

    def test_hung_service_is_bounded_by_deadline_and_keeps_identity(self):
        # A stream that never yields audio must not stick the single output worker
        # (and the mic handoff) forever; the deadline is a typed failure, not a
        # substitute voice. Preserves the retired legacy queue's bounded wait.
        import asyncio

        class Communicate:
            def __init__(self, text, voice, rate=None, pitch=None):
                pass

            def stream(self):
                async def gen():
                    await asyncio.sleep(30)   # hung service: no audio part arrives
                    yield {"type": "audio", "data": b"late"}
                return gen()

        with patch.dict(sys.modules, {"edge_tts": fake_edge_module(Communicate)}):
            with self.assertRaises(voice_edge.EdgeVoiceUnavailable):
                voice_edge.EdgeSynthesizer(timeout_seconds=0.05)(edge_spec(), "Metin", threading.Event())

    def test_cancel_while_awaiting_first_item_frees_worker_immediately(self):
        # §4-B: a Sus during the very first network wait — before ANY audio byte —
        # must cooperatively end the provider coroutine and release the worker in
        # about one poll interval, not wait for the next part or the 45 s deadline.
        # The already-sent request is not claimed to stop server-side instantly;
        # only local consumption and the physical output worker are bounded.
        import asyncio
        import time

        closed = []
        cancel = threading.Event()

        class Communicate:
            def __init__(self, text, voice, rate=None, pitch=None):
                pass

            def stream(self):
                async def gen():
                    try:
                        await asyncio.sleep(30)          # hangs before the first byte
                        yield {"type": "audio", "data": b"late"}
                    finally:
                        closed.append("closed")          # teardown must run on cancel
                return gen()

        timer = threading.Timer(0.05, cancel.set)
        timer.start()
        self.addCleanup(timer.cancel)
        with patch.dict(sys.modules, {"edge_tts": fake_edge_module(Communicate)}):
            started = time.monotonic()
            audio = voice_edge.EdgeSynthesizer()(edge_spec(), "Metin", cancel)
            elapsed = time.monotonic() - started
        self.assertEqual(audio, b"")                     # late audio never gathered
        self.assertLess(elapsed, 2.0)                    # worker freed long before 30 s/45 s
        self.assertIn("closed", closed)                  # stream torn down, no orphan task


class FakeMCI:
    """Records MCI commands and simulates a mode timeline; never touches winmm."""

    def __init__(self, modes, open_code=0, play_code=0, status_code=263,
                 stop_code=0, close_code=0, after_stop=None):
        self.commands = []
        self.modes = list(modes)
        self.open_code = open_code
        self.play_code = play_code
        self.status_code = status_code
        self.stop_code = stop_code
        self.close_code = close_code
        # Mode forced on every status read once "stop" was sent: a mode string, or
        # "error" for a driver that stops answering the status command at all.
        self.after_stop = after_stop
        self._stop_sent = False
        self.path = None

    def __call__(self, command, buffer, length, hwnd):
        self.commands.append(command)
        if command.startswith("open "):
            match = re.search(r'open "([^"]+)"', command)
            self.path = match.group(1) if match else None
            return self.open_code
        if command.startswith("play "):
            return self.play_code
        if command.startswith("stop "):
            self._stop_sent = True
            return self.stop_code
        if command.startswith("close "):
            return self.close_code
        if command.startswith("status "):
            if self._stop_sent and self.after_stop is not None:
                if self.after_stop == "error":
                    return self.status_code
                if buffer is not None:
                    buffer.value = self.after_stop
                return 0
            if self.modes and self.modes[0] is None:
                self.modes.pop(0)         # the status read itself failed
                return self.status_code
            mode = self.modes.pop(0) if self.modes else "stopped"
            if buffer is not None:
                buffer.value = mode
            return 0
        return 0


class EdgePlayerTests(unittest.TestCase):
    def test_start_is_reported_only_at_real_playing_boundary_once(self):
        started = []
        mci = FakeMCI(["stopped", "playing", "playing", "stopped"])
        with patch.object(voice_edge, "_mci_send", return_value=mci):
            voice_edge.EdgePlayer(poll_seconds=0)(b"mp3", threading.Event(), lambda: started.append(True))
        self.assertEqual(started, [True])
        self.assertIn("play jarvis_tts", mci.commands)
        self.assertFalse(os.path.exists(mci.path))
        self.assertEqual(mci.commands[-1], "close jarvis_tts")

    def test_cancel_stops_mci_cooperatively_and_removes_temp_file(self):
        cancel = threading.Event()
        mci = FakeMCI(["playing", "playing", "playing"])

        def on_start():
            cancel.set()

        with patch.object(voice_edge, "_mci_send", return_value=mci):
            voice_edge.EdgePlayer(poll_seconds=0)(b"mp3", cancel, on_start)
        self.assertIn("stop jarvis_tts", mci.commands)
        self.assertIn("close jarvis_tts", mci.commands)
        self.assertFalse(os.path.exists(mci.path))

    def test_open_failure_raises_and_cleans_up_without_start(self):
        started = []
        mci = FakeMCI([], open_code=263)
        with patch.object(voice_edge, "_mci_send", return_value=mci):
            with self.assertRaises(OSError):
                voice_edge.EdgePlayer(poll_seconds=0)(b"mp3", threading.Event(), lambda: started.append(True))
        self.assertEqual(started, [])
        self.assertFalse(os.path.exists(mci.path))
        self.assertNotIn("play jarvis_tts", mci.commands)

    def test_play_failure_raises_and_closes_alias_without_start(self):
        started = []
        mci = FakeMCI(["stopped"], play_code=277)
        with patch.object(voice_edge, "_mci_send", return_value=mci):
            with self.assertRaises(OSError):
                voice_edge.EdgePlayer(poll_seconds=0)(b"mp3", threading.Event(), lambda: started.append(True))
        self.assertEqual(started, [])
        self.assertIn("play jarvis_tts", mci.commands)
        self.assertEqual(mci.commands[-1], "close jarvis_tts")
        self.assertFalse(os.path.exists(mci.path))

    def test_already_cancelled_never_opens_a_player(self):
        cancel = threading.Event()
        cancel.set()
        mci = FakeMCI([])
        with patch.object(voice_edge, "_mci_send", return_value=mci):
            voice_edge.EdgePlayer(poll_seconds=0)(b"mp3", cancel, lambda: self.fail("must not start"))
        self.assertEqual(mci.commands, [])

    def test_empty_audio_is_refused(self):
        mci = FakeMCI([])
        with patch.object(voice_edge, "_mci_send", return_value=mci):
            with self.assertRaises(OSError):
                voice_edge.EdgePlayer(poll_seconds=0)(b"", threading.Event(), lambda: None)
        self.assertEqual(mci.commands, [])

    def player(self, modes, **kwargs):
        """A real EdgePlayer against a fake winmm, with test-sized time bounds."""
        options = {"poll_seconds": 0, "grace_seconds": 0.05, "wait_seconds": 1.0}
        options.update(kwargs)
        mci = FakeMCI(modes)
        self.enterContext(patch.object(voice_edge, "_mci_send", return_value=mci))
        return voice_edge.EdgePlayer(**options), mci

    def test_mci_that_never_reports_playing_is_a_typed_failure(self):
        # §4-D: play was accepted but the stream never entered "playing". The old
        # wait loop returned normally here, so the coordinator filed a "played"
        # receipt for audio that never existed. No start callback, and the alias
        # and temp file are still released.
        started = []
        player, mci = self.player([])
        with self.assertRaises(OSError):
            player(b"mp3", threading.Event(), lambda: started.append(True))
        self.assertEqual(started, [])
        self.assertIn("play jarvis_tts", mci.commands)   # the command went out…
        self.assertTrue(any(c.startswith("status ") for c in mci.commands))  # …and was watched
        self.assertEqual(mci.commands[-1], "close jarvis_tts")
        self.assertFalse(os.path.exists(mci.path))

    def test_unreadable_mci_status_is_never_reported_as_played(self):
        # A failing "status mode" command leaves the outcome unknown. Unknown is
        # a failure, not a finished playback, and not a substitute voice.
        started = []
        player, mci = self.player([None])
        with self.assertRaises(OSError):
            player(b"mp3", threading.Event(), lambda: started.append(True))
        self.assertEqual(started, [])
        self.assertEqual(mci.commands[-1], "close jarvis_tts")
        self.assertFalse(os.path.exists(mci.path))

    def test_playback_that_outlives_the_wait_bound_is_a_failure(self):
        # A stream stuck in a non-terminal mode must not be signed off as played
        # when the bound expires; the single worker is freed with a typed error.
        # The grace window is longer than the bound here, so only the bound can fire.
        started = []
        player, mci = self.player(["paused"] * 200, grace_seconds=1.0, wait_seconds=0.05)
        with self.assertRaises(OSError):
            player(b"mp3", threading.Event(), lambda: started.append(True))
        self.assertEqual(started, [])
        self.assertEqual(mci.commands[-1], "close jarvis_tts")
        self.assertFalse(os.path.exists(mci.path))

    def test_paused_after_a_real_start_is_not_reported_as_finished(self):
        # Only "stopped" ends a playback that actually started, so a momentary
        # pause cannot cut the utterance short and be filed as played.
        started = []
        player, mci = self.player(["playing", "paused", "paused", "playing", "stopped"])
        player(b"mp3", threading.Event(), lambda: started.append(True))
        self.assertEqual(started, [True])
        self.assertEqual(mci.commands[-1], "close jarvis_tts")
        self.assertFalse(os.path.exists(mci.path))

    def cut_player(self, stop_code=0, after_stop=None, modes=None):
        """A player that really starts, then receives a stop signal mid-stream.

        The returned callback both records the real ``playing`` boundary and
        raises the stop there, so "sus" is proven to arrive while sound is live
        rather than before it ever started.
        """
        cancel = threading.Event()
        started = []
        mci = FakeMCI(modes if modes is not None else ["playing"] * 200,
                      stop_code=stop_code, after_stop=after_stop)
        self.enterContext(patch.object(voice_edge, "_mci_send", return_value=mci))
        player = voice_edge.EdgePlayer(poll_seconds=0, grace_seconds=0.05,
                                       wait_seconds=1.0, stop_verify_seconds=0.1)

        def on_start():
            started.append(True)
            cancel.set()          # "sus" arrives while the speaker is running

        return player, mci, cancel, started, on_start

    def test_stop_refused_and_still_playing_is_a_typed_cut_failure(self):
        # §P1: winmm rejected the stop AND the device still reports "playing", so
        # the audio is live on the speaker. The old code returned normally, which
        # let the coordinator file a user interrupt, free the mic handoff and show
        # an idle orb over sound nobody stopped.
        player, mci, cancel, started, on_start = self.cut_player(
            stop_code=263, after_stop="playing")
        with self.assertRaises(voice_edge.EdgePlaybackStopUnconfirmed) as caught:
            player(b"mp3", cancel, on_start)
        self.assertEqual(started, [True])               # it really did start
        self.assertIn("stop jarvis_tts", mci.commands)  # the cut was requested…
        self.assertEqual(caught.exception.speech_status, "failed")
        self.assertEqual(caught.exception.speech_reason, "VOICE_STOP_UNCONFIRMED")
        self.assertEqual(mci.commands[-1], "close jarvis_tts")   # alias still released
        self.assertFalse(os.path.exists(mci.path))               # temp file removed

    def test_refused_stop_that_went_silent_anyway_is_a_confirmed_cut(self):
        # The proof is the device mode, not the return code alone: a driver that
        # answers the stop with an error code but is genuinely silent must not be
        # turned into a false failure (which would also keep the mic locked).
        player, mci, cancel, _, on_start = self.cut_player(stop_code=263, after_stop="stopped")
        player(b"mp3", cancel, on_start)                # no raise
        self.assertIn("stop jarvis_tts", mci.commands)

    def test_silent_driver_mode_after_stop_is_a_confirmed_cut(self):
        player, mci, cancel, _, on_start = self.cut_player(stop_code=0, after_stop="notplaying")
        player(b"mp3", cancel, on_start)
        self.assertIn("stop jarvis_tts", mci.commands)

    def test_unreadable_mode_after_stop_is_never_a_confirmed_cut(self):
        # A device that stops answering "status" leaves the outcome unknown.
        # Unknown is a typed cut failure, never a completed interrupt.
        player, _, cancel, _, on_start = self.cut_player(stop_code=0, after_stop="error")
        with self.assertRaises(voice_edge.EdgePlaybackStopUnconfirmed):
            player(b"mp3", cancel, on_start)

    def test_refused_close_is_recorded_without_rewriting_a_finished_playback(self):
        # The alias stays allocated and the next open's best-effort close reclaims
        # it; the already-proven playback outcome must not change.
        started, recorded = [], []
        mci = FakeMCI(["playing", "playing", "stopped"], close_code=614)
        self.enterContext(patch.object(voice_edge, "_mci_send", return_value=mci))
        self.enterContext(patch.object(voice_edge, "_record_failure",
                                       lambda tag, *a, **k: recorded.append(tag)))
        voice_edge.EdgePlayer(poll_seconds=0, grace_seconds=0.05, wait_seconds=1.0)(
            b"mp3", threading.Event(), lambda: started.append(True))   # no raise
        self.assertEqual(started, [True])
        # The fake payload is not real MP3, so the optional decode step reports its
        # own fallback. The seal is about the close outcome, not about that step.
        self.assertEqual([tag for tag in recorded if not tag.endswith(":decode")],
                         ["modules/voice_edge.py:mci_close"])

    def test_cut_verification_wait_is_bounded_by_accepted_limits(self):
        for bad in (-0.1, 11.0):
            with self.assertRaises(ValueError):
                voice_edge.EdgePlayer(stop_verify_seconds=bad)


if __name__ == "__main__":
    unittest.main()

class PcmSinkTests(unittest.TestCase):
    """Tek akış: cümle başına cihaz açılmaz; tükenme cihazın kendi bayrağıyla."""

    def wav(self):
        import io, wave as w
        buf = io.BytesIO()
        with w.open(buf, "wb") as writer:
            writer.setnchannels(1); writer.setsampwidth(2); writer.setframerate(16000)
            writer.writeframes(bytes([1, 0]) * 800)
        return buf.getvalue()

    def test_second_sentence_reuses_the_open_device_and_reports_underrun(self):
        opened = []
        class Stream:
            def __init__(self, callback): self.callback = callback
            def start(self): pass
            def stop(self): pass
            def close(self): pass
        fake = types.SimpleNamespace(
            RawOutputStream=lambda **kwargs: opened.append(kwargs) or Stream(kwargs["callback"]))
        sink = voice_edge.PcmSink(idle_seconds=30)
        ses = self.wav()

        def oynat():
            return sink.play(ses, threading.Event(), lambda: None)

        sonuc = []
        with patch.dict(sys.modules, {"sounddevice": fake}):
            import time
            worker = threading.Thread(target=lambda: sonuc.append(oynat()))
            worker.start()
            for _ in range(200):
                try:
                    sink._callback(bytearray(1024), 512, None,
                                   types.SimpleNamespace(output_underflow=True))
                except Exception:
                    pass
                if sonuc:
                    break
                time.sleep(0.01)
            worker.join(timeout=3)
            ikinci = oynat()
        self.assertEqual(len(opened), 1)                       # tek cihaz açılışı
        self.assertGreater(sonuc[0]["underruns"], 0)            # cihaz tükendi, ölçüldü
        self.assertEqual(ikinci["open_ms"], 0)                  # ikinci cümle beklemez
        sink.close()


class PcmSinkIdleTests(unittest.TestCase):
    """Boşta kapatma çalma sürerken devreye giremez (canlıda sesi kesti)."""

    def test_idle_timer_never_closes_an_active_playback(self):
        sink = voice_edge.PcmSink(idle_seconds=0.01)
        sink._playing = True
        sink._touch()
        self.assertIsNone(sink._timer)          # çalarken zamanlayıcı kurulmaz
        sink._playing = False
        sink._touch()
        self.assertIsNotNone(sink._timer)       # bitince kurulur
        sink.close()
