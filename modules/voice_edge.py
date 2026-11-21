"""Exact-voice Edge TTS adapter owned by the single VoiceCoordinator.

This is not an independent speech loop: synthesis and playback run only in the
coordinator's dedicated worker, snapshot one immutable VoiceSpec per request and
cooperate with its cancellation Event. Edge voices are online, so the lane's
privacy gate refuses egress in local-only mode instead of substituting another
physical identity. No automatic download, no voice switch on error, no forced
thread kill. Real Windows speaker output is accepted separately on the PC.
"""
from __future__ import annotations

import asyncio
import ctypes
import io
import os
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Callable

from modules.diagnostics import record_failure as _record_failure
from modules.voice_core import VoiceSpec


class EdgeVoiceUnavailable(ValueError):
    """The selected exact Edge voice could not be produced; identity is kept."""


class EdgePlaybackStopUnconfirmed(OSError):
    """The device never confirmed the cut, so the stop is not a completed interrupt.

    Declared to the coordinator as a failed outcome (never `played` and never a
    user interrupt) so neither the receipt, the mic handoff nor the UI can claim
    silence that was not proven. The selected voice is not changed and no second
    player is opened.
    """

    speech_status = "failed"
    speech_reason = "VOICE_STOP_UNCONFIRMED"


# Modes that mean the speaker is not currently producing this alias's audio.
_SILENT_MODES = frozenset({"stopped", "paused", "notplaying"})


def _mci_send():
    return ctypes.windll.winmm.mciSendStringW


def _ffmpeg_exe():
    """Decoder used to turn Edge MP3 into PCM before playback.

    Measured on this PC for the same 7.08 s sentence:

    * MP3 through MCI ``mpegvideo``: ``play`` alone blocks **1.23 s** before any
      sound, then 7.27 s of playback (8.6 s total).
    * the same audio as PCM through MCI ``waveaudio``: ``play`` blocks **0.41 s**,
      then 7.21 s (7.7 s total).

    Decoding costs ~0.19 s and happens off the speech path (the chunk is already
    prefetched), so the user hears the first word ~0.8 s earlier and the gap
    between chunks shrinks. Returns None when no decoder is installed; the caller
    then keeps the MP3 path exactly as before.
    """
    found = shutil.which("ffmpeg")
    if found:
        return found
    fallback = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet"
    if fallback.is_dir():
        for candidate in sorted(fallback.glob("**/bin/ffmpeg.exe")):
            if candidate.is_file():
                return str(candidate)
    return None


def _wave_length_ms(payload: bytes) -> float:
    """Duration of a PCM WAV payload in milliseconds; 0 for anything else."""
    try:
        with wave.open(io.BytesIO(payload), "rb") as handle:
            rate = handle.getframerate()
            frames = handle.getnframes()
            if rate > 0 and frames > 0:
                return frames / rate * 1000
    except (wave.Error, EOFError, OSError):
        return 0.0
    return 0.0


def _winsound():
    """waveOut tabanlı oynatıcı (yalnız Windows); yoksa None."""
    try:
        import winsound
    except ImportError:
        _record_failure("modules/voice_edge.py:winsound_import")
        return None
    return winsound


# Edge TTS kendi cevabına uzun sessizlikler koyuyor: aynı cevapta ölçüldü
# (21 Kasım) başta 0.42 sn, cümleler arasında 1.33 sn, sonda 1.08 sn — 11.42 sn'lik
# sesin 2.8 sn'si sessizlik. Kullanıcı bunu "aralarda fazla duruyor" diye duyuyor.
# Kırpma konuşmayı değiştirmez: yalnız -40 dB altındaki boşluklar, iç boşluk en çok
# 0.30 sn kalacak şekilde kısaltılır (baş/son tamamen alınır).
_SILENCE_TRIM = (
    "silenceremove=start_periods=1:start_duration=0:start_threshold=-45dB:detection=peak,"
    "silenceremove=stop_periods=-1:stop_duration=0.30:stop_threshold=-40dB:detection=peak,"
    "areverse,"
    "silenceremove=start_periods=1:start_duration=0:start_threshold=-45dB:detection=peak,"
    "areverse"
)


def _mp3_to_wave(audio: bytes, decoder: str, timeout: float = 20.0) -> bytes:
    """Decode one MP3 to a self-contained PCM WAV; any failure keeps the MP3 path."""
    folder = tempfile.mkdtemp(prefix="jarvis_edge_")
    source = os.path.join(folder, "speech.mp3")
    target = os.path.join(folder, "speech.wav")
    try:
        with open(source, "wb") as handle:
            handle.write(audio)
        for chain in (_SILENCE_TRIM, None):
            args = [decoder, "-v", "error", "-nostdin", "-y", "-i", source]
            if chain:
                args += ["-af", chain]
            args += ["-ac", "1", "-ar", "24000", "-f", "wav", target]
            completed = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
            if not completed.returncode and os.path.isfile(target) and os.path.getsize(target) > 44:
                with open(target, "rb") as handle:
                    return handle.read()
        # Kırpma da düz çözme de başarısızsa MP3 yolu korunur; sessizlik kırpılamadı
        # diye cevabı kaybetmek yanlış olur.
        _record_failure("modules/voice_edge.py:decode")
        return b""
    except (OSError, subprocess.SubprocessError):
        _record_failure("modules/voice_edge.py:decode_error")
        return b""
    finally:
        for path in (source, target):
            try:
                os.remove(path)
            except OSError:
                pass
        try:
            os.rmdir(folder)
        except OSError:
            pass


class EdgeSynthesizer:
    """Produce MP3 bytes for one exact Edge voice, never changing the identity.

    The online stream is bounded by a synthesis deadline so a hung service cannot
    stick the single output worker (and thus the mic handoff) forever; expiry is a
    typed failure that keeps the selected identity, never a substitute voice.
    """

    def __init__(self, timeout_seconds: float = 45.0):
        if not 0 < timeout_seconds <= 180:
            raise ValueError("Edge synthesis timeout outside accepted limits.")
        self.timeout_seconds = timeout_seconds

    def __call__(self, voice: VoiceSpec, text: str, cancel: threading.Event) -> bytes:
        if voice.backend != "edge":
            raise EdgeVoiceUnavailable("Edge adapter requires an edge voice spec.")
        if cancel.is_set():
            return b""
        name = voice.asset_id
        if not isinstance(name, str) or not name.strip():
            raise EdgeVoiceUnavailable("Edge voice asset id is missing.")
        rate = f"{voice.speaking_rate:+d}%"
        try:
            return asyncio.run(asyncio.wait_for(
                self._stream(name, text, rate, cancel), timeout=self.timeout_seconds))
        except EdgeVoiceUnavailable:
            raise
        except asyncio.TimeoutError as exc:
            _record_failure("modules/voice_edge.py:timeout")
            raise EdgeVoiceUnavailable("Edge speech service timed out.") from exc
        except Exception as exc:
            _record_failure("modules/voice_edge.py:synthesize")
            raise EdgeVoiceUnavailable("Edge speech service unavailable.") from exc

    async def _stream(self, name: str, text: str, rate: str, cancel: threading.Event) -> bytes:
        """Collect one exact Edge voice's MP3, cancellable even while awaiting data.

        The provider coroutine is raced against a cheap cooperative poller for
        EVERY wait — before the first audio byte and between parts — so a Sus or
        user switch frees the single output worker within one poll interval, not
        only when the next chunk happens to arrive. Cancelling the in-flight
        ``__anext__`` throws GeneratorExit into the provider, which runs the
        stream's own teardown, so no asyncio task or socket is orphaned and no
        audio gathered after the stop signal is returned. The already-submitted
        remote request is not claimed to stop or stop billing instantly on the
        server: only local consumption and the physical output worker are bounded.
        """
        import edge_tts

        stream = edge_tts.Communicate(text, name, rate=rate).stream()
        chunks: list[bytes] = []
        while True:
            next_part = asyncio.ensure_future(stream.__anext__())
            stop_watcher = asyncio.ensure_future(self._await_cancel(cancel))
            _, pending = await asyncio.wait(
                {next_part, stop_watcher}, return_when=asyncio.FIRST_COMPLETED)
            # Retire the losing task first. Cancelling an in-flight __anext__
            # throws GeneratorExit, which unwinds and closes the provider stream
            # through its own teardown; cancelling the idle poller is trivial.
            # Either way no task is left dangling on the next await.
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            if cancel.is_set():
                return b""                   # interrupted: nothing after here is audible
            try:
                part = next_part.result()    # provider errors propagate to the caller
            except StopAsyncIteration:
                break
            if part.get("type") == "audio" and part.get("data"):
                chunks.append(part["data"])
        return b"".join(chunks)

    @staticmethod
    async def _await_cancel(cancel: threading.Event, poll_seconds: float = 0.02) -> None:
        """Cooperative waiter that completes as soon as the stop signal is raised."""
        while not cancel.is_set():
            await asyncio.sleep(poll_seconds)


class EdgePlayer:
    """Play one MP3 through Windows MCI, reporting the real playback boundary.

    Only the coordinator worker calls this, so one fixed MCI alias is owned by a
    single playback at a time. Cancellation stops MCI and the silence is then read
    back from the device; an unconfirmed cut is a typed failure, never a completed
    interrupt. The temporary file is always removed and no second player is
    opened. A playback that never started is a typed failure, never a success
    receipt.
    """

    def __init__(self, poll_seconds: float = 0.02, grace_seconds: float = 1.0,
                 wait_seconds: float = 120.0, stop_verify_seconds: float = 1.0):
        if (not 0 <= poll_seconds <= 0.5 or not 0 <= grace_seconds <= 10
                or not 0 < wait_seconds <= 300 or not 0 <= stop_verify_seconds <= 10):
            raise ValueError("Edge player bounds are outside accepted limits.")
        self._poll = poll_seconds
        self._grace = grace_seconds
        self._wait_seconds = wait_seconds
        self._stop_verify = stop_verify_seconds
        # The last real playback boundary durations, for the caller's receipt.
        # Without them a "stuttering voice" cannot be split into device open,
        # player wait or synthesis, so every fix is a guess.
        self.last_timing: dict[str, float] = {}

    def __call__(self, audio: bytes, cancel: threading.Event, on_start: Callable[[], None]) -> None:
        if cancel.is_set():
            return
        if not isinstance(audio, bytes) or not audio:
            raise OSError("Edge audio is empty.")
        mci = _mci_send()
        path = None
        opened = False
        suffix = ".mp3"
        device_type = "mpegvideo"
        payload = audio
        decoder = _ffmpeg_exe()
        if decoder:
            wave_bytes = _mp3_to_wave(audio, decoder)
            if wave_bytes:
                payload = wave_bytes
                suffix = ".wav"
                device_type = "waveaudio"
        # waveOut is clocked by the device, so CPU load cannot stretch it the way it
        # stretches MCI's sequencer: live turns measured 1.6-2.0x while an isolated
        # harness on the same WAV measured 1.02x (21 Kasım 09:57-10:06).
        if suffix == ".wav" and _winsound() is not None:
            fd, path = tempfile.mkstemp(suffix=".wav", prefix="jarvis_voice_")
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
            try:
                self._play_wave(path, cancel, on_start)
                length_ms = _wave_length_ms(payload)
                if length_ms:
                    self.last_timing["audio_ms"] = length_ms
                    self.last_timing["ratio"] = self.last_timing["wait_ms"] / length_ms
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass
            return
        try:
            fd, path = tempfile.mkstemp(suffix=suffix, prefix="jarvis_voice_")
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
            mci("close jarvis_tts", None, 0, 0)  # best-effort stale alias cleanup
            opened_at = time.monotonic()
            code = mci(f'open "{path}" type {device_type} alias jarvis_tts', None, 0, 0)
            if code:
                raise OSError(f"Windows ses çalma başlatılamadı (MCI hata kodu: {code}).")
            opened = True
            open_ms = (time.monotonic() - opened_at) * 1000
            code = mci("play jarvis_tts", None, 0, 0)
            if code:
                raise OSError(f"Windows ses oynatma başarısız (MCI hata kodu: {code}).")
            wait_at = time.monotonic()
            self._wait(mci, cancel, on_start)
            self.last_timing = {"open_ms": open_ms,
                                "wait_ms": (time.monotonic() - wait_at) * 1000}
            length_ms = _wave_length_ms(payload)
            if length_ms:
                # The file's own length is the only honest denominator: without it
                # "slow playback" is a guess about how long this answer should last.
                self.last_timing["audio_ms"] = length_ms
                self.last_timing["ratio"] = self.last_timing["wait_ms"] / length_ms
        finally:
            if opened:
                # A refused close leaves the alias allocated; the next open's
                # best-effort close reclaims it. Recorded as a device fault, never
                # rewritten into the outcome of audio that already played.
                if mci("close jarvis_tts", None, 0, 0):
                    _record_failure("modules/voice_edge.py:mci_close")
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass

    def _play_wave(self, path: str, cancel: threading.Event, on_start: Callable[[], None]) -> None:
        """Play one WAV on the device clock; a stop request must really stop it.

        The same truth rules as the MCI path: "finished" only after the player
        reported the end, and a stop that cannot be confirmed raises instead of
        claiming a clean interruption.
        """
        winsound = _winsound()
        if winsound is None:
            raise OSError("Windows ses oynatıcısı bulunamadı.")
        done = threading.Event()
        error: list[BaseException] = []

        def runner() -> None:
            try:
                winsound.PlaySound(path, winsound.SND_FILENAME)
            except BaseException as exc:          # noqa: BLE001 - player boundary
                error.append(exc)
            finally:
                done.set()

        thread = threading.Thread(target=runner, name="jarvis-wav-out", daemon=True)
        opened_at = time.monotonic()
        thread.start()
        on_start()
        while not done.wait(self._poll):
            if cancel.is_set():
                winsound.PlaySound(None, winsound.SND_PURGE)
                if not done.wait(2.0):
                    _record_failure("modules/voice_edge.py:wave_stop")
                    raise EdgePlaybackStopUnconfirmed("Windows ses kesintisi doğrulanamadı.")
                break
        self.last_timing = {"open_ms": (time.monotonic() - opened_at) * 1000,
                            "wait_ms": (time.monotonic() - opened_at) * 1000}
        if error:
            _record_failure("modules/voice_edge.py:wave_play")
            raise OSError(f"Windows ses oynatma başarısız: {type(error[0]).__name__}.")

    def _wait(self, mci, cancel: threading.Event, on_start: Callable[[], None]) -> str:
        """Return only a real outcome; anything else raises instead of claiming speech.

        "finished" means MCI confirmed ``playing`` and then confirmed it ended,
        and "interrupted" means the stop signal was honored. Both of those are
        truthful terminal states. Everything else raises: an alias that never
        reported ``playing`` produced no audio at all, an unreadable status leaves
        the outcome unknown, and a wait that runs out never saw an end. Returning
        normally in those cases would let the coordinator file a played receipt
        for speech the user never heard, which is exactly the false success this
        boundary exists to prevent. Even on the failure paths this proves only
        that MCI reported the mode, not that a human heard sound.
        """
        started = False
        grace = time.monotonic() + self._grace
        deadline = time.monotonic() + self._wait_seconds
        while not cancel.is_set():
            mode = self._mode(mci)
            if mode is None:
                _record_failure("modules/voice_edge.py:mci_status")
                raise OSError("Windows ses oynatma durumu okunamadı (MCI).")
            if mode == "playing":
                if not started:
                    started = True
                    # MCI confirmed real playback; this is the player boundary,
                    # not proof that a human heard sound.
                    on_start()
            elif mode == "stopped":
                if started:
                    return "finished"
                if time.monotonic() > grace:
                    # A short grace window lets the device open, then a still
                    # unstarted stream is a failure rather than silent success.
                    _record_failure("modules/voice_edge.py:playback_not_started")
                    raise OSError("Windows ses oynatma başlamadı (MCI).")
            if time.monotonic() >= deadline:
                _record_failure("modules/voice_edge.py:playback_wait")
                raise OSError("Windows ses oynatma tamamlanmadan zaman aşımına uğradı.")
            time.sleep(self._poll)
        # Only a stop signal can leave the loop without a terminal mode, so this
        # is the cooperative interrupt path: never a played, never a silent success.
        code = mci("stop jarvis_tts", None, 0, 0)
        if not self._cut_confirmed(mci):
            _record_failure("modules/voice_edge.py:playback_stop")
            raise EdgePlaybackStopUnconfirmed(
                f"Windows ses kesintisi doğrulanamadı (MCI hata kodu: {code}).")
        return "interrupted"

    def _cut_confirmed(self, mci) -> bool:
        """Bounded, device-read proof that the stopped alias really went silent.

        A zero return code only says winmm accepted the stop request; a driver
        that ignores it still reports ``playing``, and a device that stops
        answering at all yields an unreadable mode. Both are unknown, so the cut
        stays unconfirmed instead of becoming a completed interrupt the mic
        handoff could safely run against. The wait is bounded and happens in the
        single output worker: it holds no Core lock, never blocks the queue and
        cancels no GoalState or work item.
        """
        deadline = time.monotonic() + self._stop_verify
        while True:
            mode = self._mode(mci)
            if mode in _SILENT_MODES:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(self._poll)

    @staticmethod
    def _mode(mci) -> str | None:
        """Current MCI mode, or None when the status command itself is unusable.

        An empty buffer and a non-zero return code both mean "unknown"; they are
        never collapsed into "stopped", which would read as a finished playback.
        """
        buffer = ctypes.create_unicode_buffer(128)
        if mci("status jarvis_tts mode", buffer, 128, 0):
            return None
        return buffer.value.strip().lower() or None