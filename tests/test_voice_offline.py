"""Offline voice adapters: deterministic, no model download, no audio hardware."""
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from modules.voice_core import VoiceSpec
from modules.voice_offline import (OfflineVoiceUnavailable, PiperSynthesizer, WavePlayer,
                                   _piper_inprocess, _validate_wave, piper_available,
                                   piper_length_scale)


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

    def test_piper_available_accepts_the_inprocess_package_or_the_cli(self):
        # Kullanıcının kurulumunda paket vardı, CLI yoktu: ses "kurulu değil"
        # sayılıyordu. Bu ikisinden biri yeterli olmalı.
        with patch("modules.voice_offline._piper_executable", return_value=None):
            with patch.dict(sys.modules, {"piper": SimpleNamespace(PiperVoice=object)}):
                self.assertTrue(piper_available())
            with patch.dict(sys.modules, {"piper": None}):
                self.assertFalse(piper_available())
        with patch.dict(sys.modules, {"piper": None}), \
                patch("modules.voice_offline._piper_executable", return_value=r"C:\tools\piper.exe"):
            self.assertTrue(piper_available())

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

    def fake_device(self, *, underflow=False):
        """Cihaz sesi kendi çeker: callback'i PortAudio çağırır, biz taklit ediyoruz."""
        class Stop(Exception): pass
        class Abort(Exception): pass
        class Stream:
            def __init__(self, *, callback, blocksize, **kwargs):
                self.callback, self.blocksize = callback, blocksize
                self.latency = 0.05
                self.played = 0
            def __enter__(self):
                for _ in range(16):
                    out = bytearray(self.blocksize * 2)
                    status = SimpleNamespace(output_underflow=True) if underflow else None
                    try:
                        self.callback(memoryview(out), self.blocksize, None, status)
                    except (Stop, Abort):
                        break
                    self.played += 1
                return self
            def __exit__(self, *args): pass
        return patch.dict(sys.modules, {"sounddevice": SimpleNamespace(
            RawOutputStream=lambda **kwargs: Stream(**kwargs),
            CallbackStop=Stop, CallbackAbort=Abort,
            query_devices=lambda **kwargs: {"name": "Hoparlor"})})

    def test_player_reports_audio_length_and_device_underrun(self):
        # Takılma ölçülebilir olmalı: ses uzunluğu, oran, hazır ses ve cihazın
        # kendi "tampon tükendi" bayrağı. Bunlar yoksa "takılmıyor" tahmindir.
        player = WavePlayer(frames_per_write=256)
        with self.fake_device():
            player(wav_bytes(), threading.Event(), lambda: None)
        self.assertAlmostEqual(player.last_timing["audio_ms"], 500 / 16000 * 1000, places=1)
        self.assertEqual(player.last_timing["underruns"], 0)
        self.assertIn("ratio", player.last_timing)
        self.assertEqual(player.last_timing["out"], "Hoparlor")

    def test_player_reports_underrun_when_device_starves(self):
        # Kullanıcının duyduğu takılma cihazın susuz kalmasıdır; artık ölçülüyor.
        player = WavePlayer(frames_per_write=256)
        with self.fake_device(underflow=True):
            player(wav_bytes(), threading.Event(), lambda: None)
        self.assertGreater(player.last_timing["underruns"], 0)

    def test_cancellation_aborts_the_device_feed(self):
        cancel = threading.Event()
        player = WavePlayer(frames_per_write=256)
        def on_start():
            cancel.set()
        with self.fake_device():
            player(wav_bytes(), cancel, on_start)
        self.assertNotIn("ratio", player.last_timing)   # yarıda kesildi, çalma oranı yok

    def test_no_playback_when_cancelled(self):
        cancel = threading.Event()
        cancel.set()
        with patch.dict(sys.modules, {"sounddevice": SimpleNamespace(
                RawOutputStream=lambda **kwargs: self.fail("must not open output"))}):
            WavePlayer()(wav_bytes(), cancel, lambda: self.fail("must not report playback start"))


if __name__ == "__main__":
    unittest.main()
