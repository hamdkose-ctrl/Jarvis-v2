"""Offline voice adapters: deterministic, no model download, no audio hardware."""
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from modules.voice_core import VoiceSpec
from modules.voice_offline import OfflineVoiceUnavailable, PiperSynthesizer, WavePlayer, _validate_wave, piper_length_scale


def wav_bytes(*, silent=False):
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\x00\x00" * 500 if silent else b"\x01\x00" * 500)
    return output.getvalue()


class FakeProcess:
    returncode = 0

    def communicate(self, input=None, timeout=None):
        return b"", b""

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9


class OfflineVoiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "female.onnx").write_bytes(b"model")
        (self.root / "male.onnx").write_bytes(b"model")

    def spec(self, model="female.onnx"):
        return VoiceSpec("female_calm", "Kadın sakin", "piper", model)

    def test_piper_uses_only_explicit_selected_model(self):
        commands = []
        def popen(args, **kwargs):
            commands.append(args)
            Path(args[-1]).write_bytes(wav_bytes())
            return FakeProcess()
        with patch("modules.voice_offline.shutil.which", return_value="C:/bin/piper.exe"), \
             patch("modules.voice_offline.subprocess.Popen", side_effect=popen):
            result = PiperSynthesizer(self.root)(self.spec(), "Merhaba", threading.Event())
        self.assertEqual(result, wav_bytes())
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][commands[0].index("-m")+1], str((self.root/"female.onnx").resolve()))
        self.assertNotIn("male.onnx", commands[0])

    def test_rate_maps_to_bounded_piper_length_scale_without_voice_change(self):
        self.assertEqual(piper_length_scale(0), 1.0)
        self.assertGreater(piper_length_scale(-40), 1.0)
        self.assertLess(piper_length_scale(40), 1.0)
        for rate in (True, -41, 41, 1.5, None):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                piper_length_scale(rate)

        commands = []
        def popen(args, **kwargs):
            commands.append(args)
            Path(args[args.index("-f") + 1]).write_bytes(wav_bytes())
            return FakeProcess()
        with (patch("modules.voice_offline.shutil.which", return_value="C:/bin/piper.exe"),
              patch("modules.voice_offline.subprocess.Popen", side_effect=popen)):
            base = self.spec("female.onnx")
            self.assertEqual(PiperSynthesizer(self.root)(
                VoiceSpec(base.voice_id, base.label, base.backend, base.asset_id,
                          speaking_rate=-20),
                "Yavaşça oku", threading.Event(),
            ), wav_bytes())
            self.assertEqual(PiperSynthesizer(self.root)(
                VoiceSpec(base.voice_id, base.label, base.backend, base.asset_id,
                          speaking_rate=25),
                "Hızlıca oku", threading.Event(),
            ), wav_bytes())
        self.assertEqual(len(commands), 2)
        for cmd in commands:
            self.assertEqual(cmd[cmd.index("-m") + 1],
                             str((self.root / "female.onnx").resolve()))
            self.assertNotIn("male.onnx", cmd)
            self.assertIn("--length_scale", cmd)
        self.assertGreater(float(commands[0][-1]), 1)
        self.assertLess(float(commands[1][-1]), 1)

    def test_unavailable_model_fails_without_switching_or_network(self):
        with self.assertRaises(OfflineVoiceUnavailable):
            PiperSynthesizer(self.root)(self.spec("missing.onnx"), "Merhaba", threading.Event())
        with self.assertRaises(OfflineVoiceUnavailable):
            PiperSynthesizer(self.root)(self.spec("../outside.onnx"), "Merhaba", threading.Event())
        with self.assertRaises(OfflineVoiceUnavailable):
            PiperSynthesizer(self.root)(VoiceSpec("female_calm", "Kadın", "edge", "female.onnx"),
                                        "Merhaba", threading.Event())
        with patch("modules.voice_offline.shutil.which", return_value=None):
            with self.assertRaises(OfflineVoiceUnavailable):
                PiperSynthesizer(self.root)(self.spec(), "Merhaba", threading.Event())

    def test_cancel_before_model_probe_is_noop(self):
        cancelled=threading.Event()
        cancelled.set()
        self.assertEqual(PiperSynthesizer(self.root)(self.spec("missing.onnx"), "Merhaba", cancelled), b"")

    def test_invalid_silent_or_truncated_output_rejected(self):
        with self.assertRaises(ValueError):
            _validate_wave(wav_bytes(silent=True))
        with self.assertRaises(ValueError):
            _validate_wave(b"not a wave file")
        with self.assertRaises(ValueError):
            _validate_wave(wav_bytes()[:70])

    def test_pcm_player_cooperates_with_cancellation(self):
        chunks = []
        cancel = threading.Event()
        class Stream:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def write(self, data):
                chunks.append(data)
                cancel.set()
        with patch.dict(sys.modules, {"sounddevice": SimpleNamespace(RawOutputStream=lambda **kwargs: Stream())}):
            WavePlayer(frames_per_write=256)(wav_bytes(), cancel, lambda: None)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(len(chunks[0]), 256 * 2)

    def test_no_playback_when_cancelled(self):
        cancel = threading.Event()
        cancel.set()
        with patch.dict(sys.modules, {"sounddevice": SimpleNamespace(
                RawOutputStream=lambda **kwargs: self.fail("must not open output"))}):
            WavePlayer()(wav_bytes(), cancel, lambda: self.fail("must not report playback start"))


if __name__ == "__main__":
    unittest.main()
