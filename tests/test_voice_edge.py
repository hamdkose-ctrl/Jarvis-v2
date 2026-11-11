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
            def __init__(self, text, voice, rate=None):
                seen["text"], seen["voice"], seen["rate"] = text, voice, rate

            def stream(self):
                async def gen():
                    yield {"type": "audio", "data": b"mp3-a"}
                    yield {"type": "audio", "data": b"mp3-b"}
                    yield {"type": "WordBoundary", "data": None}
                return gen()

        with patch.dict(sys.modules, {"edge_tts": fake_edge_module(Communicate)}):
            audio = voice_edge.EdgeSynthesizer()(edge_spec(rate=-12), "Merhaba", threading.Event())
        self.assertEqual(audio, b"mp3-amp3-b")
        self.assertEqual(seen, {"text": "Merhaba", "voice": "tr-TR-EmelNeural", "rate": "-12%"})

    def test_cancel_mid_stream_returns_empty_without_finishing_download(self):
        cancel = threading.Event()
        reached = []

        class Communicate:
            def __init__(self, text, voice, rate=None):
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
            def __init__(self, text, voice, rate=None):
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
            def __init__(self, text, voice, rate=None):
                pass

            def stream(self):
                async def gen():
                    await asyncio.sleep(30)   # hung service: no audio part arrives
                    yield {"type": "audio", "data": b"late"}
                return gen()

        with patch.dict(sys.modules, {"edge_tts": fake_edge_module(Communicate)}):
            with self.assertRaises(voice_edge.EdgeVoiceUnavailable):
                voice_edge.EdgeSynthesizer(timeout_seconds=0.05)(edge_spec(), "Metin", threading.Event())


class FakeMCI:
    """Records MCI commands and simulates a mode timeline; never touches winmm."""

    def __init__(self, modes, open_code=0, play_code=0):
        self.commands = []
        self.modes = list(modes)
        self.open_code = open_code
        self.play_code = play_code
        self.path = None

    def __call__(self, command, buffer, length, hwnd):
        self.commands.append(command)
        if command.startswith("open "):
            match = re.search(r'open "([^"]+)"', command)
            self.path = match.group(1) if match else None
            return self.open_code
        if command.startswith("play "):
            return self.play_code
        if command.startswith("status "):
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


if __name__ == "__main__":
    unittest.main()