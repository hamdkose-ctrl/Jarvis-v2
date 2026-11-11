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
import os
import tempfile
import threading
import time
from typing import Callable

from modules.diagnostics import record_failure as _record_failure
from modules.voice_core import VoiceSpec


class EdgeVoiceUnavailable(ValueError):
    """The selected exact Edge voice could not be produced; identity is kept."""


def _mci_send():
    return ctypes.windll.winmm.mciSendStringW


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
        import edge_tts

        chunks: list[bytes] = []
        async for part in edge_tts.Communicate(text, name, rate=rate).stream():
            if cancel.is_set():
                return b""
            if part.get("type") == "audio" and part.get("data"):
                chunks.append(part["data"])
        return b"".join(chunks)


class EdgePlayer:
    """Play one MP3 through Windows MCI, reporting the real playback boundary.

    Only the coordinator worker calls this, so one fixed MCI alias is owned by a
    single playback at a time. Cancellation stops MCI cooperatively; the temporary
    file is always removed and no second player is opened.
    """

    def __init__(self, poll_seconds: float = 0.02):
        self._poll = poll_seconds

    def __call__(self, audio: bytes, cancel: threading.Event, on_start: Callable[[], None]) -> None:
        if cancel.is_set():
            return
        if not isinstance(audio, bytes) or not audio:
            raise OSError("Edge audio is empty.")
        mci = _mci_send()
        path = None
        opened = False
        try:
            fd, path = tempfile.mkstemp(suffix=".mp3", prefix="jarvis_voice_")
            with os.fdopen(fd, "wb") as handle:
                handle.write(audio)
            mci("close jarvis_tts", None, 0, 0)  # best-effort stale alias cleanup
            code = mci(f'open "{path}" type mpegvideo alias jarvis_tts', None, 0, 0)
            if code:
                raise OSError(f"Windows ses çalma başlatılamadı (MCI hata kodu: {code}).")
            opened = True
            code = mci("play jarvis_tts", None, 0, 0)
            if code:
                raise OSError(f"Windows ses oynatma başarısız (MCI hata kodu: {code}).")
            self._wait(mci, cancel, on_start)
        finally:
            if opened:
                mci("close jarvis_tts", None, 0, 0)
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass

    def _wait(self, mci, cancel: threading.Event, on_start: Callable[[], None]) -> None:
        started = False
        grace = time.monotonic() + 1.0
        deadline = time.monotonic() + 120.0
        while not cancel.is_set():
            mode = self._mode(mci)
            if mode == "playing":
                if not started:
                    started = True
                    # MCI confirmed real playback; this is the player boundary,
                    # not proof that a human heard sound.
                    on_start()
            elif started:
                break
            elif mode in ("stopped", "") and time.monotonic() > grace:
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(self._poll)
        if cancel.is_set():
            mci("stop jarvis_tts", None, 0, 0)

    @staticmethod
    def _mode(mci) -> str:
        buffer = ctypes.create_unicode_buffer(128)
        if mci("status jarvis_tts mode", buffer, 128, 0):
            return ""
        return buffer.value.strip().lower()