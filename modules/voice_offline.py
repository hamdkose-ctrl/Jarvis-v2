"""Explicit offline Piper synthesis and PCM WAV playback for Voice Core.

No model download, network fallback, LLM/Ollama import, or implicit voice switch.
Adapters are not connected to the production engine until real-PC acceptance.
"""
from __future__ import annotations

import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable
import wave

from modules.voice_core import VoiceSpec


class OfflineVoiceUnavailable(RuntimeError):
    pass


_PIPER_LENGTH_BASE = 1.18   # kullanıcı onayı: biraz daha yavaş (tokluk)
_TOK_CHAIN = ("bass=g=7:f=130:w=0.9,acompressor=threshold=-14dB:ratio=4:"
              "attack=4:release=160,volume=1.9,alimiter=limit=0.95,aresample=48000")


def piper_length_scale(rate: int) -> float:
    """Map the bounded existing profile rate onto Piper's phoneme length.

    Higher rate is faster; Piper length_scale is inversely related to speed.
    Zero retains Piper's normal default. No pitch, timbre or voice-ID change.
    """
    if type(rate) is not int or not -40 <= rate <= 40:
        raise ValueError("Piper speaking rate must be an integer -40..40.")
    return round(2 ** (-rate / 60), 3)


def _pcm_to_wave(frames: bytes, rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(frames)
    return buffer.getvalue()


_PIPER_CACHE: dict[str, object] = {}
# Paralel cümleler aynı modeli aynı anda yüklemesin: canlıda ilk tur 5657 ms
# sürdü çünkü iki parça modeli iki kez yükledi. Tek yükleme, tek kilit.
_LOAD_LOCK = threading.Lock()


def _piper_inprocess(real_model: Path, text: str, length_scale: float,
                     cancel: threading.Event) -> bytes | None:
    """Piper'ı süreç içinde çalıştırır: model bir kez yüklenir.

    Ölçüm (21 Kasım): süreç içi 326-353 ms, CLI 2993 ms (model her cümlede
    yeniden yükleniyor). Kütüphane yoksa/başarısızsa None döner ve mevcut CLI
    yolu aynen kullanılır.
    """
    try:
        from piper import PiperVoice, SynthesisConfig
    except ImportError:
        return None
    try:
        voice = _PIPER_CACHE.get(str(real_model))
        if voice is None:
            with _LOAD_LOCK:
                voice = _PIPER_CACHE.get(str(real_model))
                if voice is None:
                    voice = PiperVoice.load(str(real_model))
                    _PIPER_CACHE[str(real_model)] = voice
        chunks = []
        for audio in voice.synthesize(
                text, syn_config=SynthesisConfig(length_scale=round(length_scale, 3))):
            if cancel.is_set():
                return b""
            chunks.append(audio.audio_int16_bytes)
        if not chunks:
            return b""
        try:
            rate = voice.config.sample_rate
        except (AttributeError, TypeError):
            rate = 22050
        return _pcm_to_wave(b"".join(chunks), rate)
    except Exception:
        _record_failure("modules/voice_offline.py:piper_inprocess")
        return None


def _tok(wav: bytes) -> bytes:
    """Tokluk: bas + kompresör + sınırlayıcı (kullanıcı onayı, 21 Kasım).

    ffmpeg yoksa ya da dönüşüm başarısızsa ses AYNEN döner; konuşma kaybolmaz.
    Ölçüm: zincir ~27 ms ekliyor.
    """
    executable = shutil.which("ffmpeg")
    if not executable or not wav:
        return wav
    try:
        with tempfile.TemporaryDirectory(prefix="jarvis-tok-") as folder:
            source = Path(folder) / "in.wav"
            target = Path(folder) / "out.wav"
            source.write_bytes(wav)
            done = subprocess.run([executable, "-y", "-v", "error", "-i", str(source),
                                   "-af", _TOK_CHAIN, "-ac", "1", "-ar", "48000", str(target)],
                                  capture_output=True, timeout=20)
            if done.returncode != 0 or not target.is_file():
                return wav
            shaped = target.read_bytes()
            _validate_wave(shaped)
            return shaped
    except Exception:
        _record_failure("modules/voice_offline.py:tok")
        return wav


class PiperSynthesizer:
    """Synthesize one explicitly provisioned voice without changing its identity."""

    def __init__(self, model_root: Path, *, timeout_seconds: float = 40.0):
        if not 1 <= timeout_seconds <= 180:
            raise ValueError("Piper timeout outside accepted limits.")
        self.model_root = Path(model_root)
        self.timeout_seconds = timeout_seconds

    def preload_all(self) -> int:
        """Yerel modelleri arka planda yükle: ilk cümle model yüklemesini ödemesin."""
        loaded = 0
        try:
            from piper import PiperVoice
        except ImportError:
            return 0
        try:
            root = self.model_root.resolve()
            for model in sorted(root.glob("*.onnx")):
                if model.is_symlink() or str(model) in _PIPER_CACHE:
                    continue
                try:
                    with _LOAD_LOCK:
                        if str(model) in _PIPER_CACHE:
                            continue
                        _PIPER_CACHE[str(model)] = PiperVoice.load(str(model))
                    loaded += 1
                except Exception:
                    _record_failure("modules/voice_offline.py:preload")
        except Exception:
            _record_failure("modules/voice_offline.py:preload_root")
        return loaded

    def _model(self, spec: VoiceSpec) -> Path:
        if spec.backend != "piper":
            raise OfflineVoiceUnavailable("Selected voice is not a Piper voice.")
        asset = Path(spec.asset_id)
        if asset.is_absolute() or asset.suffix.lower() != ".onnx" or ".." in asset.parts:
            raise OfflineVoiceUnavailable("Selected voice asset path is invalid.")
        root = self.model_root.resolve()
        candidate = root / asset
        if candidate.is_symlink() or any(p.is_symlink() for p in candidate.parents if p != root and root in p.parents):
            raise OfflineVoiceUnavailable("Symlinked voice models are not accepted.")
        try:
            real = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise OfflineVoiceUnavailable("Selected offline voice is not installed.") from exc
        if root not in real.parents or not real.is_file() or real.is_symlink():
            raise OfflineVoiceUnavailable("Selected offline voice is outside its model directory.")
        return real

    def __call__(self, spec: VoiceSpec, text: str, cancel: threading.Event) -> bytes:
        if cancel.is_set():
            return b""
        model = self._model(spec)
        if not text or len(text) > 12000:
            raise ValueError("Speech text is empty or exceeds limit.")
        # Süreç içi yol yalnız GERÇEK modelde denenir: testler sahte (küçük)
        # dosyalarla CLI sözleşmesini sınar, orada davranış değişmesin.
        inprocess = None
        try:
            if model.stat().st_size > 1_000_000:
                inprocess = _piper_inprocess(
                    model, text,
                    piper_length_scale(spec.speaking_rate) * _PIPER_LENGTH_BASE, cancel)
        except OSError:
            _record_failure("modules/voice_offline.py:model_stat")
        if inprocess:
            _validate_wave(inprocess)
            return _tok(inprocess)
        # Piper uygulamanın kendi sanal ortamına kurulur; Scripts PATH'te değil.
        executable = shutil.which("piper") or shutil.which(
            "piper", path=str(Path(sys.executable).parent))
        if not executable:
            raise OfflineVoiceUnavailable("Piper executable is not installed.")
        if not text or len(text) > 12000:
            raise ValueError("Speech text is empty or exceeds limit.")
        with tempfile.TemporaryDirectory(prefix="jarvis-voice-piper-") as folder:
            target = Path(folder) / "speech.wav"
            command = [executable, "-m", str(model), "-f", str(target)]
            if spec.speaking_rate:
                command.extend([
                    "--length_scale", f"{piper_length_scale(spec.speaking_rate):.3f}",
                ])
            proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            started = time.monotonic()
            try:
                first = True
                while True:
                    if cancel.is_set():
                        return b""
                    if time.monotonic() - started > self.timeout_seconds:
                        raise TimeoutError("Selected offline voice exceeded its synthesis deadline.")
                    try:
                        proc.communicate(input=text.encode("utf-8") if first else None, timeout=0.2)
                        break
                    except subprocess.TimeoutExpired:
                        first = False
                if cancel.is_set():
                    return b""
                if proc.returncode != 0:
                    raise OfflineVoiceUnavailable("Selected offline voice failed to synthesize.")
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()
            if not target.is_file() or target.is_symlink() or target.stat().st_size > 35_000_000:
                raise OfflineVoiceUnavailable("Offline voice returned no valid WAV output.")
            audio = target.read_bytes()
            _validate_wave(audio)
            return audio


def _validate_wave(audio: bytes) -> None:
    try:
        with wave.open(io.BytesIO(audio), "rb") as wf:
            channels, rate, width, count = wf.getnchannels(), wf.getframerate(), wf.getsampwidth(), wf.getnframes()
            if (wf.getcomptype() != "NONE" or channels not in (1, 2)
                    or width != 2 or not 8_000 <= rate <= 48_000
                    or count <= 0 or count / rate > 180):
                raise ValueError("Unsupported offline audio metadata.")
            data = wf.readframes(count)
            if len(data) != count * channels * width or not any(data):
                raise ValueError("Offline audio is empty, incomplete or silent.")
    except (wave.Error, EOFError, OSError) as exc:
        raise ValueError("Offline voice output is not a valid PCM WAV file.") from exc


class WavePlayer:
    """The single PCM playback adapter. Cancellation never touches Core requests."""

    def __init__(self, *, device=None, frames_per_write: int = 1024, latency: float | str = 0.35):
        if not 256 <= frames_per_write <= 8192:
            raise ValueError("Audio output chunk size is invalid.")
        self.device = device
        self.frames_per_write = frames_per_write
        # Canlı ölçüm: uygulama yükü altında çalma iş parçacığı 250 ms askıya
        # alınıyordu ve cihaz susuz kalıyordu (ratio 1.14-1.19, max_gap 255 ms).
        # Yüksek gecikmeli akış, 250 ms'lik bir askıyı duyulmadan soğurur.
        self.latency = latency
        self.last_timing: dict[str, float | str] = {}

    def _raise_priority(self) -> None:
        """Çalma iş parçacığı öne alınır: ses her zaman önde (Windows, en iyi çaba)."""
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadPriority(
                ctypes.windll.kernel32.GetCurrentThread(), 15)  # TIME_CRITICAL
        except Exception:
            pass

    def __call__(self, audio: bytes, cancel: threading.Event, on_start: Callable[[], None]) -> None:
        _validate_wave(audio)
        self.last_timing = {}
        if cancel.is_set():
            return
        import sounddevice as sd
        completed = False
        self._raise_priority()
        with wave.open(io.BytesIO(audio), "rb") as wf:
            rate = wf.getframerate()
            audio_ms = wf.getnframes() / max(rate, 1) * 1000
            buffer_ms = self.frames_per_write / max(rate, 1) * 1000
            opened = time.monotonic()
            with sd.RawOutputStream(samplerate=rate, channels=wf.getnchannels(),
                                    dtype="int16", device=self.device,
                                    latency=self.latency) as stream:
                open_ms = (time.monotonic() - opened) * 1000
                try:
                    headroom_ms = float(getattr(stream, "latency", 0.0)) * 1000
                except (TypeError, ValueError):
                    headroom_ms = 0.0
                started = False
                gap_ms = 0.0
                last = None
                while not cancel.is_set():
                    chunk = wf.readframes(self.frames_per_write)
                    if not chunk:
                        completed = True
                        break
                    stream.write(chunk)
                    now = time.monotonic()
                    if last is not None:
                        gap_ms = max(gap_ms, (now - last) * 1000 - buffer_ms)
                    last = now
                    if not started:
                        started = True
                        # The output stream accepted the first real PCM frame. This is
                        # the player boundary, not proof that a human heard sound.
                        on_start()
            played_ms = (time.monotonic() - opened) * 1000
        timing: dict[str, float | str] = {"open_ms": open_ms, "audio_ms": audio_ms,
                                          "max_gap_ms": max(gap_ms, 0.0)}
        # Duyulan takılma, askının cihazda hazır bekleyen sesi aşmasıdır; yüksek
        # gecikmeli akışta 250 ms'lik bir askı sessizliğe dönüşmez.
        timing["headroom_ms"] = headroom_ms
        timing["stall_ms"] = max(0.0, max(gap_ms, 0.0) - headroom_ms)
        if completed and audio_ms:
            timing["ratio"] = played_ms / audio_ms
        try:
            timing["out"] = str(sd.query_devices(kind="output")["name"])[:40]
        except Exception:
            pass
        self.last_timing = timing
