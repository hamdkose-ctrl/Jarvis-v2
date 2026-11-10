"""VOICE-01: provider-independent foreground speech queue contract.

This is deliberately not connected to the production voice engine yet. Adapters may
be integrated only after exact-head and real-PC acceptance. No LLM, Ollama, cloud
provider, model installer, or operating-system audio dependency belongs here.
"""
from __future__ import annotations

from dataclasses import dataclass
import queue
import threading
from typing import Callable


@dataclass(frozen=True)
class VoiceSpec:
    voice_id: str
    label: str
    backend: str
    asset_id: str

    def __post_init__(self):
        if (not self.voice_id or not self.label or not self.asset_id
                or self.backend not in {"edge", "piper", "sapi"}):
            raise ValueError("Voice specification is incomplete.")


class VoiceCatalog:
    """Developer-controlled installed voice bindings; never chooses alternatives."""

    def __init__(self, specs: tuple[VoiceSpec, ...]):
        ids = [item.voice_id for item in specs]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("Voice catalog must contain unique, named voices.")
        self._by_id = {item.voice_id: item for item in specs}

    def require(self, voice_id: str) -> VoiceSpec:
        try:
            return self._by_id[voice_id]
        except (KeyError, TypeError):
            raise ValueError("Selected voice is unavailable; not switching voices.") from None


@dataclass(frozen=True)
class SpeechRequest:
    owner: str
    request_id: str
    voice_id: str
    text: str
    lane: str = "foreground"  # foreground conversation or background notification
    rate: int = -8

    def __post_init__(self):
        if (not all(isinstance(x, str) and x.strip()
                    for x in (self.owner, self.request_id, self.voice_id, self.text))
                or len(self.text) > 12000 or self.lane not in {"foreground", "background"}
                or type(self.rate) is not int or not -50 <= self.rate <= 50):
            raise ValueError("Invalid speech request.")


@dataclass(frozen=True)
class SpeechReceipt:
    request_id: str
    owner: str
    voice_id: str
    status: str  # played, failed, cancelled, rejected
    reason_code: str


class VoiceCoordinator:
    """Single-owner output worker: foreground is preferred, Core workers never wait.

    A speech adapter must cooperate with its cancellation Event. Interrupting speech
    never signals cancellation to the caller's background GoalState/work queue.
    """

    def __init__(
        self,
        catalog: VoiceCatalog,
        synthesize: Callable[[VoiceSpec, SpeechRequest, threading.Event], bytes],
        play: Callable[[bytes, threading.Event], None],
        report: Callable[[SpeechReceipt], None],
        *,
        max_pending: int = 8,
    ):
        if max_pending < 1:
            raise ValueError("Speech queue must be bounded.")
        self._catalog = catalog
        self._synthesize = synthesize
        self._play = play
        self._report = report
        self._pending: queue.PriorityQueue = queue.PriorityQueue(maxsize=max_pending)
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._generation = 0
        self._sequence = 0
        self._current_cancel: threading.Event | None = None
        self._current_lane: str | None = None
        self._worker = threading.Thread(target=self._run, name="jarvis-voice-output", daemon=True)
        self._worker.start()

    def submit(self, request: SpeechRequest) -> bool:
        # Selected voice is validated at enqueue time, not changed by a later setting.
        spec = self._catalog.require(request.voice_id)
        with self._lock:
            if self._closed.is_set():
                return False
            self._sequence += 1
            priority = 0 if request.lane == "foreground" else 1
            try:
                self._pending.put_nowait((priority, self._sequence, self._generation, request, spec))
                if request.lane == "foreground" and self._current_lane == "background":
                    # Urgent conversation preempts only the audio notification, not its GoalState.
                    if self._current_cancel is not None:
                        self._current_cancel.set()
            except queue.Full:
                return False
        return True

    def interrupt_speech(self) -> None:
        """Forget queued speech and cooperatively interrupt active playback only."""
        with self._lock:
            self._generation += 1
            if self._current_cancel is not None:
                self._current_cancel.set()

    def close(self) -> None:
        with self._lock:
            self._closed.set()
            self._generation += 1
            if self._current_cancel is not None:
                self._current_cancel.set()

    def _notify(self, request: SpeechRequest, status: str, reason: str) -> None:
        receipt = SpeechReceipt(request.request_id, request.owner, request.voice_id, status, reason)
        try:
            self._report(receipt)
        except Exception:
            # An observation callback must not kill the dedicated speech worker.
            pass

    def _run(self) -> None:
        while not self._closed.is_set():
            try:
                _, _, generation, request, spec = self._pending.get(timeout=0.1)
            except queue.Empty:
                continue
            cancel = threading.Event()
            with self._lock:
                if self._closed.is_set() or generation != self._generation:
                    cancel.set()
                else:
                    self._current_cancel = cancel
                    self._current_lane = request.lane
            try:
                if cancel.is_set():
                    self._notify(request, "cancelled", "VOICE_INTERRUPTED")
                    continue
                try:
                    audio = self._synthesize(spec, request, cancel)
                    if cancel.is_set():
                        self._notify(request, "cancelled", "VOICE_INTERRUPTED")
                    elif not isinstance(audio, bytes) or not audio:
                        self._notify(request, "failed", "VOICE_EMPTY_AUDIO")
                    else:
                        self._play(audio, cancel)
                        if cancel.is_set():
                            self._notify(request, "cancelled", "VOICE_INTERRUPTED")
                        else:
                            self._notify(request, "played", "VOICE_PLAYBACK_RETURNED")
                except Exception:
                    self._notify(request, "cancelled" if cancel.is_set() else "failed",
                                 "VOICE_INTERRUPTED" if cancel.is_set() else "VOICE_ADAPTER_FAILED")
            finally:
                with self._lock:
                    if self._current_cancel is cancel:
                        self._current_cancel = None
                        self._current_lane = None
                self._pending.task_done()
