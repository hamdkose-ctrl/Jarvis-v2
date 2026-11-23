"""Yerel motorların çıkışı tek akıştan geçer (takılma düzeltmesi).

Canlı kusur (23 Kasım, kullanıcı "ses takılıyor"): WavePlayer her cümle için
cihazı yeniden açıp kapatıyordu; 2,6 sn'lik ses 3,8 sn sürüyordu (oran 1,48) ve
üç cümlelik cevapta toplam oran 1,51'e çıkıyordu. Ölçüm (aynı metin, WaveSink):
oran 1,08-1,11, en büyük boşluk 0 ms, underrun 0.
"""
import io
import threading
import unittest
import wave
from unittest.mock import patch

from modules import voice_offline


def _wav(ms: int = 200, rate: int = 22050) -> bytes:
    """Sessiz ses reddedilir; ölçüm için gerçek bir ton üretilir."""
    import math
    frames = int(rate * ms / 1000)
    tone = b"".join(int(8000 * math.sin(2 * math.pi * 440 * i / rate)).to_bytes(
        2, "little", signed=True) for i in range(frames))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(tone)
    return buffer.getvalue()


_SINKS = []


def _factory(**options):
    _SINKS.append(_FakeSink(**options))
    return _SINKS[-1]


class _FakeSink:
    def __init__(self, **options):
        self.options = options
        self.played = []
        self.closed = False

    def play(self, wav, cancel, on_start):
        self.played.append(wav)
        return {"wait_ms": 200.0, "audio_ms": 200.0, "ratio": 1.0, "underruns": 0}

    def close(self):
        self.closed = True


class LocalSink(unittest.TestCase):
    def test_delegates_to_single_stream(self):
        with patch("modules.voice_edge.PcmSink", side_effect=_factory):
            sink = voice_offline.WaveSink()
        fake = _SINKS[-1]
        sink(_wav(), threading.Event(), lambda: None)
        sink(_wav(), threading.Event(), lambda: None)
        self.assertEqual(len(fake.played), 2)          # aynı akış iki cümle
        self.assertEqual(sink.last_timing["ratio"], 1.0)

    def test_join_silence_default_is_shared(self):
        with patch("modules.voice_edge.PcmSink", side_effect=_factory):
            voice_offline.WaveSink()
        fake = _SINKS[-1]
        self.assertEqual(fake.options["join_silence_ms"], 120.0)
        self.assertEqual(fake.options["idle_seconds"], 25.0)

    def test_rejects_non_wave_audio(self):
        with patch("modules.voice_edge.PcmSink", side_effect=_factory):
            sink = voice_offline.WaveSink()
        with self.assertRaises(Exception):
            sink(b"not a wave", threading.Event(), lambda: None)

    def test_cancelled_call_is_silent(self):
        with patch("modules.voice_edge.PcmSink", side_effect=_factory):
            sink = voice_offline.WaveSink()
        fake = _SINKS[-1]
        cancel = threading.Event()
        cancel.set()
        sink(_wav(), cancel, lambda: None)
        self.assertEqual(fake.played, [])

    def test_device_is_forwarded(self):
        with patch("modules.voice_edge.PcmSink", side_effect=_factory):
            voice_offline.WaveSink(device=3)
        self.assertEqual(_SINKS[-1].options["device"], 3)

    def test_close_releases_device(self):
        with patch("modules.voice_edge.PcmSink", side_effect=_factory):
            sink = voice_offline.WaveSink()
        fake = _SINKS[-1]
        sink.close()
        self.assertTrue(fake.closed)

    def test_runtime_local_lanes_use_sink(self):
        source = (voice_offline.__file__ or "")
        self.assertTrue(source.endswith("voice_offline.py"))
        from pathlib import Path
        runtime = Path(source).with_name("voice_runtime.py").read_text(encoding="utf-8")
        self.assertIn("WaveSink()", runtime)
        self.assertNotIn("WavePlayer()", runtime)


if __name__ == "__main__":
    unittest.main()
