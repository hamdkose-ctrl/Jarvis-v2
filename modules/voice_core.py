"""VOICE Core: one foreground audio owner with bounded, interruptible output.

Production can use this core only through an explicit opt-in adapter. No LLM,
Ollama, cloud provider, model installer, or OS audio dependency belongs here.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import queue
import threading
from typing import Callable

from modules.diagnostics import record_failure as _record_failure


SPEECH_CHUNK_CHARS = 600


def split_speech_text(text: str, *, max_chars: int = SPEECH_CHUNK_CHARS) -> tuple[str, ...]:
    """Split a bounded utterance without dropping or rewriting any characters.

    Prefer complete sentence ends, then word boundaries, and hard-cut only when
    a single word itself exceeds the limit. The same selected voice is used
    for every chunk; callers may cooperatively stop between chunks.
    """
    if not isinstance(text, str) or not text.strip() or len(text) > 12000:
        raise ValueError("Speech text invalid or too long.")
    if type(max_chars) is not int or not 32 <= max_chars <= 12000:
        raise ValueError("Speech chunk size outside supported bounds.")
    parts: list[str] = []
    cursor = 0
    while len(text) - cursor > max_chars:
        window = text[cursor:cursor + max_chars]
        first = max(12, max_chars // 3)
        sentence_break = 0
        space_break = 0
        pos = 0
        while pos < len(window):
            char = window[pos]
            if char.isspace():
                end = pos + 1
                while end < len(window) and window[end].isspace():
                    end += 1
                if end >= first:
                    space_break = end
                pos = end
                continue
            if char in ".!?;:。！？":
                after = cursor + pos + 1
                if after == len(text) or text[after].isspace():
                    end = pos + 1
                    while end < len(window) and window[end].isspace():
                        end += 1
                    if end >= first:
                        sentence_break = end
            pos += 1
        cut = sentence_break or space_break or len(window)
        # Boundaries are measured from the original string, so no text is lost.
        parts.append(text[cursor:cursor + cut])
        cursor += cut
    if cursor < len(text):
        parts.append(text[cursor:])
    return tuple(parts)


@dataclass(frozen=True)
class VoiceSpec:
    voice_id: str
    label: str
    backend: str
    asset_id: str
    speaking_rate: int = 0  # immutable per-request prosody, not voice identity

    def __post_init__(self):
        if (not self.voice_id or not self.label or not self.asset_id
                or self.backend not in {"edge", "piper", "sapi"}
                or type(self.speaking_rate) is not int
                or not -40 <= self.speaking_rate <= 40):
            raise ValueError("Voice specification is incomplete.")


class VoiceCatalog:
    """Developer-controlled installed voice bindings; never chooses alternatives."""

    def __init__(self, specs: tuple[VoiceSpec, ...]):
        ids = [item.voice_id for item in specs]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("Voice catalog must contain unique, named voices.")
        self._by_id = {item.voice_id: item for item in specs}

    def choices(self) -> tuple[VoiceSpec, ...]:
        """Expose developer-approved choices without mutating the active voice."""
        return tuple(self._by_id.values())

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
    rate: int = 0  # -40 slower, +40 faster, immutable on this request

    def __post_init__(self):
        if (not all(isinstance(x, str) and x.strip()
                    for x in (self.owner, self.request_id, self.voice_id, self.text))
                or len(self.text) > 12000 or self.lane not in {"foreground", "background"}
                or type(self.rate) is not int or not -40 <= self.rate <= 40):
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
        synthesize: Callable[[VoiceSpec, str, threading.Event], bytes],
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
        # Snapshot per-request speed in an immutable spec. The installed
        # catalog and active voice ID are never mutated by a rate change.
        spec = replace(self._catalog.require(request.voice_id), speaking_rate=request.rate)
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

    def _drain_waiting_locked(self) -> list[SpeechRequest]:
        """Cancel queued requests immediately, preserving queue accounting."""
        discarded: list[SpeechRequest] = []
        while True:
            try:
                _, _, _, request, _ = self._pending.get_nowait()
            except queue.Empty:
                break
            discarded.append(request)
            self._pending.task_done()
        return discarded

    def interrupt_speech(self) -> None:
        """Interrupt playback and acknowledge all queued audio, not Core work."""
        with self._lock:
            self._generation += 1
            if self._current_cancel is not None:
                self._current_cancel.set()
            discarded = self._drain_waiting_locked()
        for request in discarded:
            self._notify(request, "cancelled", "VOICE_INTERRUPTED")

    def close(self) -> None:
        """Close without joining the TTS worker or leaving waiting receipts open."""
        with self._lock:
            self._closed.set()
            self._generation += 1
            if self._current_cancel is not None:
                self._current_cancel.set()
            discarded = self._drain_waiting_locked()
        for request in discarded:
            self._notify(request, "cancelled", "VOICE_INTERRUPTED")

    def _notify(self, request: SpeechRequest, status: str, reason: str) -> None:
        receipt = SpeechReceipt(request.request_id, request.owner, request.voice_id, status, reason)
        try:
            self._report(receipt)
        except Exception:
            _record_failure('modules/voice_core.py:notify')
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
                    status, reason = "played", "VOICE_PLAYBACK_RETURNED"
                    for chunk in split_speech_text(request.text):
                        if cancel.is_set():
                            status, reason = "cancelled", "VOICE_INTERRUPTED"
                            break
                        if not chunk.strip():
                            # Pure whitespace is a non-audio separator, never
                            # an extra Piper invocation or a fake failure.
                            continue
                        audio = self._synthesize(spec, chunk, cancel)
                        if cancel.is_set():
                            status, reason = "cancelled", "VOICE_INTERRUPTED"
                            break
                        if not isinstance(audio, bytes) or not audio:
                            status, reason = "failed", "VOICE_EMPTY_AUDIO"
                            break
                        self._play(audio, cancel)
                        if cancel.is_set():
                            status, reason = "cancelled", "VOICE_INTERRUPTED"
                            break
                    self._notify(request, status, reason)
                except Exception:
                    _record_failure('modules/voice_core.py:adapter')
                    self._notify(request, "cancelled" if cancel.is_set() else "failed",
                                 "VOICE_INTERRUPTED" if cancel.is_set() else "VOICE_ADAPTER_FAILED")
            finally:
                with self._lock:
                    if self._current_cancel is cancel:
                        self._current_cancel = None
                        self._current_lane = None
                self._pending.task_done()
