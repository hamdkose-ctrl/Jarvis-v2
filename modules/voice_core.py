"""VOICE Core: one foreground audio owner with bounded, interruptible output.

Production can use this core only through an explicit opt-in adapter. No LLM,
Ollama, cloud provider, model installer, or OS audio dependency belongs here.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import queue
import threading
import time
from typing import Callable

from modules.diagnostics import record_failure as _record_failure


SPEECH_CHUNK_CHARS = 600
SPEECH_REQUEST_SCHEMA = "speech.request.v2"
# Event type is provenance for presentation, not an urgency the model may choose.
SPEECH_KINDS = frozenset({"reply", "notice", "reminder", "progress", "privacy", "preview"})
SPEECH_STAGES = ("accepted", "synthesizing", "audio_ready", "playback_started")
_ID_CHARS = 128
_MAX_TTL_SECONDS = 3600.0


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
    """One utterance with the identity Core supplied; voice never invents it.

    `lane` alone derives queue priority and preemption. `state_version` travels
    as provenance: a version bump by itself never clears audio, because only the
    event/result identity decides whether a spoken result is still current.
    """

    owner: str
    request_id: str
    voice_id: str
    text: str
    lane: str = "foreground"  # foreground conversation or background notification
    rate: int = 0  # -40 slower, +40 faster, immutable on this request
    kind: str = "reply"
    turn_id: str = ""
    event_id: str = ""
    goal_id: str = ""
    state_version: int = 0
    artifact_id: str = ""
    approval_id: str = ""
    ttl_seconds: float = 0.0  # 0 = no expiry; expires audio only, never the written result
    schema: str = SPEECH_REQUEST_SCHEMA

    def __post_init__(self):
        if (not all(isinstance(x, str) and x.strip()
                    for x in (self.owner, self.request_id, self.voice_id, self.text))
                or len(self.text) > 12000 or self.lane not in {"foreground", "background"}
                or type(self.rate) is not int or not -40 <= self.rate <= 40):
            raise ValueError("Invalid speech request.")
        if self.schema != SPEECH_REQUEST_SCHEMA or self.kind not in SPEECH_KINDS:
            raise ValueError("Unknown speech request version or event kind.")
        if not all(isinstance(x, str) and len(x) <= _ID_CHARS
                   for x in (self.turn_id, self.event_id, self.goal_id,
                             self.artifact_id, self.approval_id)):
            raise ValueError("Speech identity fields must be bounded strings.")
        if type(self.state_version) is not int or self.state_version < 0:
            raise ValueError("Speech state version must be a non-negative integer.")
        if (isinstance(self.ttl_seconds, bool)
                or not isinstance(self.ttl_seconds, (int, float))
                or not 0 <= self.ttl_seconds <= _MAX_TTL_SECONDS):
            raise ValueError("Speech TTL is outside supported bounds.")


@dataclass(frozen=True)
class SpeechReceipt:
    request_id: str
    owner: str
    voice_id: str
    status: str  # played, failed, cancelled, rejected
    reason_code: str
    turn_id: str = ""
    event_id: str = ""
    goal_id: str = ""
    kind: str = "reply"


class VoiceCoordinator:
    """Single-owner output worker: foreground is preferred, Core workers never wait.

    A speech adapter must cooperate with its cancellation Event and report its own
    real playback start through ``on_start``; ready WAV bytes are not speech.
    Interrupting speech never signals cancellation to the caller's background
    GoalState/work queue. ``stages`` and ``validate`` must stay local and cheap:
    no model, disk or network wait belongs on a control callback.
    """

    def __init__(
        self,
        catalog: VoiceCatalog,
        synthesize: Callable[[VoiceSpec, str, threading.Event], bytes],
        play: Callable[[bytes, threading.Event, Callable[[], None]], None],
        report: Callable[[SpeechReceipt], None],
        *,
        max_pending: int = 8,
        stages: Callable[[SpeechRequest, str], None] | None = None,
        validate: Callable[[SpeechRequest], str] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        if max_pending < 1:
            raise ValueError("Speech queue must be bounded.")
        self._catalog = catalog
        self._synthesize = synthesize
        self._play = play
        self._report = report
        self._stages = stages
        self._validate = validate
        self._clock = clock
        self._pending: queue.PriorityQueue = queue.PriorityQueue(maxsize=max_pending)
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._generation = 0
        self._sequence = 0
        self._current_cancel: threading.Event | None = None
        self._current_request: SpeechRequest | None = None
        self._current_lane: str | None = None
        self._cancel_reason = "VOICE_INTERRUPTED"
        self._worker = threading.Thread(target=self._run, name="jarvis-voice-output", daemon=True)
        self._worker.start()

    def submit(self, request: SpeechRequest) -> bool:
        """Nonblocking enqueue. Every refusal is a typed receipt, never a silent drop."""
        # Selected voice is validated at enqueue time, not changed by a later setting.
        # Snapshot per-request speed in an immutable spec. The installed
        # catalog and active voice ID are never mutated by a rate change.
        spec = replace(self._catalog.require(request.voice_id), speaking_rate=request.rate)
        invalid = self._validity(request)
        if invalid:
            self._notify(request, "rejected", invalid)
            return False
        with self._lock:
            closed = self._closed.is_set()
            full = False
            if not closed:
                self._sequence += 1
                priority = 0 if request.lane == "foreground" else 1
                try:
                    self._pending.put_nowait(
                        (priority, self._sequence, self._generation, request, spec, self._clock())
                    )
                except queue.Full:
                    full = True
                if not full and request.lane == "foreground" and self._current_lane == "background":
                    # Urgent conversation preempts only the audio notification, not its GoalState.
                    if self._current_cancel is not None:
                        self._cancel_reason = "VOICE_INTERRUPTED"
                        self._current_cancel.set()
        if closed:
            self._notify(request, "rejected", "VOICE_CLOSED")
            return False
        if full:
            self._notify(request, "rejected", "VOICE_QUEUE_FULL")
            return False
        self._stage(request, "accepted")
        return True

    def invalidate(self, *, owner: str = "", goal_id: str = "", turn_id: str = "",
                   event_id: str = "", request_id: str = "") -> int:
        """Drop audio for an explicit result identity; unrelated speech keeps its order.

        Core owns the decision that a result is stale. Voice only consumes it, and
        refuses an empty selector so a state refresh can never blind-clear the queue.
        """
        selectors = {key: value for key, value in (
            ("owner", owner), ("goal_id", goal_id), ("turn_id", turn_id),
            ("event_id", event_id), ("request_id", request_id),
        ) if isinstance(value, str) and value.strip()}
        if not selectors:
            raise ValueError("Speech invalidation requires an explicit identity.")

        def matches(request: SpeechRequest) -> bool:
            return all(getattr(request, key) == value for key, value in selectors.items())

        with self._lock:
            discarded, kept = [], []
            for item in self._drain_waiting_locked():
                (discarded if matches(item[3]) else kept).append(item)
            for item in kept:
                self._pending.put_nowait(item)
            hit_active = self._current_request is not None and matches(self._current_request)
            if hit_active and self._current_cancel is not None:
                self._cancel_reason = "VOICE_INVALIDATED"
                self._current_cancel.set()
            count = len(discarded) + (1 if hit_active else 0)
        for item in discarded:
            self._notify(item[3], "cancelled", "VOICE_INVALIDATED")
        return count

    def _drain_waiting_locked(self) -> list[tuple]:
        """Dequeue waiting items, preserving queue accounting for the caller."""
        items: list[tuple] = []
        while True:
            try:
                items.append(self._pending.get_nowait())
            except queue.Empty:
                return items
            self._pending.task_done()

    def interrupt_speech(self) -> None:
        """Interrupt playback and acknowledge all queued audio, not Core work."""
        with self._lock:
            self._generation += 1
            self._cancel_reason = "VOICE_INTERRUPTED"
            if self._current_cancel is not None:
                self._current_cancel.set()
            discarded = self._drain_waiting_locked()
        for item in discarded:
            self._notify(item[3], "cancelled", "VOICE_INTERRUPTED")

    def close(self) -> None:
        """Close without joining the TTS worker or leaving waiting receipts open."""
        with self._lock:
            self._closed.set()
            self._generation += 1
            self._cancel_reason = "VOICE_INTERRUPTED"
            if self._current_cancel is not None:
                self._current_cancel.set()
            discarded = self._drain_waiting_locked()
        for item in discarded:
            self._notify(item[3], "cancelled", "VOICE_INTERRUPTED")

    def _validity(self, request: SpeechRequest) -> str:
        """Cheap local checkpoint; an unreadable authority fails closed, not open."""
        if self._validate is None:
            return ""
        try:
            reason = self._validate(request)
        except Exception:
            _record_failure('modules/voice_core.py:validate')
            return "VOICE_VALIDITY_UNKNOWN"
        if reason is None or reason == "":
            return ""
        return reason if isinstance(reason, str) and reason.strip() else "VOICE_VALIDITY_UNKNOWN"

    def _expired(self, request: SpeechRequest, enqueued_at: float) -> bool:
        return bool(request.ttl_seconds) and self._clock() - enqueued_at >= request.ttl_seconds

    def _stage(self, request: SpeechRequest, stage: str) -> None:
        if self._stages is None:
            return
        try:
            self._stages(request, stage)
        except Exception:
            _record_failure('modules/voice_core.py:stage')

    def _cancelled_reason(self) -> str:
        with self._lock:
            return self._cancel_reason

    def _notify(self, request: SpeechRequest, status: str, reason: str) -> None:
        receipt = SpeechReceipt(request.request_id, request.owner, request.voice_id, status, reason,
                                turn_id=request.turn_id, event_id=request.event_id,
                                goal_id=request.goal_id, kind=request.kind)
        try:
            self._report(receipt)
        except Exception:
            _record_failure('modules/voice_core.py:notify')
            # An observation callback must not kill the dedicated speech worker.
            pass

    def _run(self) -> None:
        while not self._closed.is_set():
            try:
                _, _, generation, request, spec, enqueued_at = self._pending.get(timeout=0.1)
            except queue.Empty:
                continue
            cancel = threading.Event()
            with self._lock:
                if self._closed.is_set() or generation != self._generation:
                    cancel.set()
                else:
                    self._current_cancel = cancel
                    self._current_request = request
                    self._current_lane = request.lane
                    self._cancel_reason = "VOICE_INTERRUPTED"
            try:
                if cancel.is_set():
                    self._notify(request, "cancelled", self._cancelled_reason())
                    continue
                invalid = self._validity(request)
                if invalid:
                    self._notify(request, "rejected", invalid)
                    continue
                if self._expired(request, enqueued_at):
                    self._notify(request, "cancelled", "VOICE_TTL_EXPIRED")
                    continue
                try:
                    status, reason = "played", "VOICE_PLAYBACK_RETURNED"
                    announced_ready = False
                    announced_start = False

                    def on_start() -> None:
                        nonlocal announced_start
                        if not announced_start:
                            announced_start = True
                            self._stage(request, "playback_started")

                    self._stage(request, "synthesizing")
                    for chunk in split_speech_text(request.text):
                        if cancel.is_set():
                            status, reason = "cancelled", self._cancelled_reason()
                            break
                        if not chunk.strip():
                            # Pure whitespace is a non-audio separator, never
                            # an extra Piper invocation or a fake failure.
                            continue
                        audio = self._synthesize(spec, chunk, cancel)
                        if cancel.is_set():
                            status, reason = "cancelled", self._cancelled_reason()
                            break
                        if not isinstance(audio, bytes) or not audio:
                            status, reason = "failed", "VOICE_EMPTY_AUDIO"
                            break
                        if not announced_ready:
                            announced_ready = True
                            self._stage(request, "audio_ready")
                        if self._expired(request, enqueued_at):
                            status, reason = "cancelled", "VOICE_TTL_EXPIRED"
                            break
                        invalid = self._validity(request)
                        if invalid:
                            status, reason = "cancelled", invalid
                            break
                        self._play(audio, cancel, on_start)
                        if cancel.is_set():
                            status, reason = "cancelled", self._cancelled_reason()
                            break
                    self._notify(request, status, reason)
                except Exception:
                    _record_failure('modules/voice_core.py:adapter')
                    self._notify(request, "cancelled" if cancel.is_set() else "failed",
                                 self._cancelled_reason() if cancel.is_set() else "VOICE_ADAPTER_FAILED")
            finally:
                with self._lock:
                    if self._current_cancel is cancel:
                        self._current_cancel = None
                        self._current_request = None
                        self._current_lane = None
                self._pending.task_done()
