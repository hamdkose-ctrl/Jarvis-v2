"""VOICE Core: one foreground audio owner with bounded, interruptible output.

Production can use this core only through an explicit opt-in adapter. No LLM,
Ollama, cloud provider, model installer, or OS audio dependency belongs here.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import logging
from contextlib import nullcontext
import queue
import threading
import time
from typing import Callable

from modules.diagnostics import record_failure as _record_failure

voice_log = logging.getLogger("jarvis")


def _device_timing(player) -> str:
    """The adapter's own boundary durations, when it reports any.

    Splitting play time into device open and player wait is what tells a real
    device stall apart from a pipeline gap; without it every latency fix is a
    guess that can make the sound worse.
    """
    timing = getattr(player, "last_timing", None)
    if not isinstance(timing, dict):
        return ""
    parts = []
    for name, spec in (("open_ms", ".0f"), ("wait_ms", ".0f"), ("audio_ms", ".0f"), ("ratio", ".2f")):
        value = timing.get(name)
        if isinstance(value, (int, float)):
            parts.append(f"{name}={value:{spec}}")
    # Hangi aygıta çalındığı: aynı makinede izole 1.03x, canlı 1.13x ölçüldü.
    # Aygıt adı olmadan bu farkın hoparlör değişiminden mi süreçten mi geldiği
    # bilinemez; bir sonraki cevap kendi kanıtını yanında taşısın.
    endpoint = timing.get("out")
    if isinstance(endpoint, str) and endpoint:
        parts.append(f"out={endpoint}")
    return " ".join(parts)


def _cpu_window() -> dict:
    """Snapshot who is burning CPU for the next chunk.

    The voice plays smoothly in an isolated harness but stutters inside the live
    app, and the user sees CPU reach 100% exactly then. Wall time alone cannot
    say whether the player is starved by this process or by something else, so
    the chunk records real CPU time, the busiest threads of the same window and
    the machine's own load. Nothing here enumerates other processes: the probe
    must never add work to the voice path it measures.
    """
    snapshot = {"cpu": time.process_time(), "threads": {}, "names": {}}
    try:
        import psutil
        snapshot["threads"] = {t.id: t.user_time + t.system_time for t in psutil.Process().threads()}
        snapshot["names"] = {t.native_id: t.name for t in threading.enumerate() if t.native_id}
        snapshot["system"] = psutil.cpu_percent(None)
    except ImportError:
        snapshot["threads"] = {}
    return snapshot


def _cpu_report(before: dict, started_at: float) -> str:
    """CPU time, busiest threads and machine load for the chunk that just ended."""
    wall_ms = (time.monotonic() - started_at) * 1000
    cpu_ms = (time.process_time() - before.get("cpu", 0.0)) * 1000
    parts = [f"cpu_ms={cpu_ms:.0f}", f"wall_ms={wall_ms:.0f}"]
    try:
        import psutil
        now = {t.id: t.user_time + t.system_time for t in psutil.Process().threads()}
        parts.append(f"makine={psutil.cpu_percent(None):.0f}%")
    except ImportError:
        now = {}
    previous = before.get("threads") or {}
    names = before.get("names") or {}
    if now and previous:
        hot = sorted(((now[tid] - previous.get(tid, 0.0)) / max(wall_ms / 1000, 0.001) * 100, tid)
                     for tid in now)
        top = [f"{names.get(tid, 'tid' + str(tid))} %{pct:.0f}" for pct, tid in reversed(hot[-2:]) if pct >= 1]
        if top:
            parts.append("en çok: " + ", ".join(top))
    return " ".join(parts)


SPEECH_CHUNK_CHARS = 600
# A long answer must not wait for 600 characters to be synthesized before the
# first sound: its opening chunk stops at the first sentence end inside this
# bound. Text that fits one chunk is never re-cut, so a normal reply keeps
# exactly one provider call.
SPEECH_FIRST_CHUNK_CHARS = 200
# Fast speech start (setting fast_speech_start, owner default on): any spoken
# reply longer than this opens at its first sentence, so the first audio waits
# for one short sentence instead of the whole shortened reply. The shortened
# spoken text is capped below SPEECH_CHUNK_CHARS, so without this the ordinary
# max_chars gate never opens a normal reply early.
SPEECH_EARLY_OPEN_CHARS = 120
# Cümle tonu ancak cümle cümle üretilirse duyuluyor: bir blokta 2-3 cümle varsa
# tek bir perde kaydırması hepsine uygulanır ve etki kaybolur (ölçüm 21 Kasım:
# blok bazında perde hareketi 4.66 -> 4.95 yarım ton, yani duyulmaz; cümle
# bazında soru 135 -> 146 Hz). Hedef bu yüzden cümle boyu; uzun cevaplarda
# istek sayısı sınırlı kalsın diye blok büyür.
SPEECH_SENTENCE_CHARS = 170
# Bundan kısa parçayı tek başına çalmak, açılış maliyeti yüzünden okumayı
# yavaşlatıyor (ölçüm: 28 karakterlik parça 1.32 oranında çalındı).
SPEECH_MIN_CHUNK = 120
# Edge paralel istekleri kaldırıyor: 6 cümle paralel 1.8-2.5 sn (sırayla ~15 sn).
# Sınır, tek cevabın açabileceği eşzamanlı istek sayısıdır.
SPEECH_PARALLEL_SYNTH = 6
# Bir cevap için en çok bu kadar parça: cümle sayısı bunu aşarsa ardışık
# cümleler gruplanır (çok uzun cevapta istek yağmuru olmasın).
SPEECH_MAX_CHUNKS = 8
# A tail shorter than this is not worth a second synthesis and a second player
# start: the speaker would fall silent to prepare one short leftover word. Keep
# the answer in ONE chunk instead, so its audio never breaks.
SPEECH_MIN_TAIL_CHARS = 80
SPEECH_REQUEST_SCHEMA = "speech.request.v2"
# Event type is provenance for presentation, not an urgency the model may choose.
SPEECH_KINDS = frozenset({"reply", "notice", "reminder", "progress", "privacy", "preview"})
_ID_CHARS = 128
_MAX_TTL_SECONDS = 3600.0
# How many announced results are remembered as delivered. A recency bound keeps
# this from growing with uptime; forgetting only allows a *later* repeat, and Core
# re-offers of an utterance that never played release their claim immediately.
DELIVERED_RESULTS_KEPT = 64


def delivery_key(request: SpeechRequest) -> tuple | None:
    """Which result this utterance presents, or None for plain conversation.

    Only a request that names its own result can be a duplicate: two different
    turns may legitimately answer with the very same sentence, so an utterance
    with no result identity is never deduplicated.

    The owner is part of the key even though it is always present. Record ids
    are per-profile, so two users can announce the same id with the same
    sentence; marking one of them delivered must not silence the other.
    """
    result = (request.turn_id, request.event_id, request.goal_id,
              request.state_version, request.artifact_id, request.approval_id)
    return ((request.owner, *result), request.text.strip()) if any(result) else None


def _first_sentence_end(text: str, limit: int) -> int:
    """Where the first complete sentence of `text[:limit]` ends, or 0 when it has none.

    A sentence shorter than twelve characters is not worth a synthesis call of its
    own, so the search keeps going from it; a dot inside a word (an abbreviation or
    a decimal) is not a sentence end. Nothing found means the caller opens the
    utterance with its ordinary window, exactly as before.
    """
    bound = min(limit, len(text))
    pos = 0
    while pos < bound:
        if text[pos] in ".!?;:。！？":
            after = pos + 1
            if after == len(text) or text[after].isspace():
                end = after
                while end < len(text) and text[end].isspace():
                    end += 1
                if end <= bound and end >= 12:
                    return end
                pos = end
                continue
        pos += 1
    return 0


_SENTENCE_END = ".!?…"


def _sentences(text: str) -> list[str]:
    """Metni cümlelere böler, hiçbir karakteri kaybetmeden (bitişik ekler dahil)."""
    parts: list[str] = []
    start = 0
    for index, char in enumerate(text):
        if char in _SENTENCE_END:
            end = index + 1
            while end < len(text) and text[end].isspace():
                end += 1
            parts.append(text[start:end])
            start = end
    if start < len(text):
        parts.append(text[start:])
    return [part for part in parts if part.strip()]


def speech_chunks(text: str, open_early_at: int = 0) -> tuple[str, ...]:
    """Bir cevabın seslendirilecek parçaları — varsayılan olarak birer cümle.

    Ton ancak cümle cümle üretilirse duyuluyor: blok içinde tek perde kaydırması
    bütün cümlelere uygulanır ve etki kaybolur (ölçüm 21 Kasım: blok bazında
    perde hareketi 4.66 -> 4.95, cümle bazında soru 135 -> 146 Hz).
    İstek sayısı sınırlı kalsın diye cümle sayısı SPEECH_MAX_CHUNKS'ı aşarsa
    ardışık cümleler eşit gruplara birleştirilir; tek başına sığmayan cümle
    kelime sınırından kırılır. Hiçbir karakter düşmez ya da eklenmez.
    """
    if not isinstance(text, str) or not text.strip():
        return ()
    sentences = _sentences(text)
    if not sentences:
        return ()
    if len(sentences) > SPEECH_MAX_CHUNKS:
        step = -(-len(sentences) // SPEECH_MAX_CHUNKS)
        sentences = ["".join(sentences[i:i + step])
                     for i in range(0, len(sentences), step)]
    # Kısa cümle tek başına çalınınca ölçülen açılış maliyeti sesin kendisinden
    # büyük oluyor (28 karakterlik cümle: 1898 ms ses, 2578 ms çalma = 1.32) ve
    # kullanıcı bunu "okuma yavaşladı" diye duyuyor. Bu yüzden komşu kısa
    # cümleler, parça en az SPEECH_MIN_CHUNK olana kadar birleştirilir.
    merged: list[str] = []
    for sentence in sentences:
        if merged and len(merged[-1]) < SPEECH_MIN_CHUNK and                 len(merged[-1]) + len(sentence) <= SPEECH_SENTENCE_CHARS:
            merged[-1] += sentence
        else:
            merged.append(sentence)
    sentences = merged
    parts: list[str] = []
    for sentence in sentences:
        if len(sentence) <= SPEECH_SENTENCE_CHARS:
            parts.append(sentence)
        else:
            parts.extend(split_speech_text(sentence, max_chars=SPEECH_SENTENCE_CHARS,
                                          first_max_chars=SPEECH_SENTENCE_CHARS))
    _ = open_early_at   # cümle bazında açılış zaten ilk cümleyle sınırlı
    return tuple(parts)


def split_speech_text(text: str, *, max_chars: int = SPEECH_CHUNK_CHARS,
                      first_max_chars: int = SPEECH_FIRST_CHUNK_CHARS,
                      open_early_at: int = 0) -> tuple[str, ...]:
    """Split a bounded utterance without dropping or rewriting any characters.

    Prefer complete sentence ends, then word boundaries, and hard-cut only when
    a single word itself exceeds the limit. The same selected voice is used
    for every chunk; callers may cooperatively stop between chunks.

    Only an answer that really needs more than one chunk is opened early: its
    first chunk stops at the first sentence end inside `first_max_chars`, so the
    speaker starts after one short sentence instead of after the whole ordinary
    window has been synthesized. Text that fits one chunk is returned untouched —
    a normal reply still costs exactly one provider call.

    `open_early_at` overrides that single-chunk economy on request: when the
    text exceeds it (and a worthwhile sentence end exists inside
    `first_max_chars`), the first sentence opens the utterance early even though
    the whole text would fit one chunk. The remainder still travels as its own
    chunk, so joining always reproduces the text exactly.
    """
    if not isinstance(text, str) or not text.strip() or len(text) > 12000:
        raise ValueError("Speech text invalid or too long.")
    for name, value in (("chunk", max_chars), ("first chunk", first_max_chars)):
        if type(value) is not int or not 32 <= value <= 12000:
            raise ValueError(f"Speech {name} size outside supported bounds.")
    if (type(open_early_at) is not int or not 0 <= open_early_at <= 12000
            or (0 < open_early_at < 32)):
        raise ValueError("Speech early-open size outside supported bounds.")
    parts: list[str] = []
    cursor = 0
    if len(text) > max_chars or (open_early_at and len(text) > open_early_at):
        opening = _first_sentence_end(text, min(first_max_chars, max_chars))
        # Opening a short reply early only pays off when what remains is worth a
        # second synthesis and a second play. A 128-character answer split at 120
        # produced an 8-character tail: the speaker went silent to synthesize and
        # start a whole new chunk for one word. Below the tail floor the answer
        # stays one chunk, so its audio is continuous.
        if opening and len(text) - opening >= SPEECH_MIN_TAIL_CHARS:
            parts.append(text[:opening])
            cursor = opening
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


def speech_pace_note(*, request_id: str, voice_id: str, chars: int, status: str,
                     reason: str = "", queue_ms: int | None = None,
                     synth_ms: int | None = None, first_audio_ms: int | None = None,
                     total_ms: int | None = None) -> str:
    """One line about how long one utterance took: identifiers and durations, never words.

    "The voice arrives seconds after the text" is a timing question, so the log
    answers it with the waits the user actually feels — how long the request sat in
    the single output queue, how long the provider took to produce the first audio,
    how long until the device admitted it started playing, and how long the whole
    utterance took. A wait that never happened is reported as "-", never as zero.
    No text, voice asset name or user identity travels in it, so it is safe to keep.
    """
    parts = [f"speech_pace id={request_id}", f"voice={voice_id}", f"chars={chars}",
             f"status={status}"]
    if reason:
        parts.append(f"reason={reason}")
    for name, value in (("queue_ms", queue_ms), ("synth_ms", synth_ms),
                        ("first_audio_ms", first_audio_ms), ("total_ms", total_ms)):
        parts.append(f"{name}={'-' if value is None else value}")
    return " ".join(parts)


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
    open_early_at: int = 0  # 0 = one-chunk economy; else open at first sentence above this size
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
        if (isinstance(self.open_early_at, bool)
                or not isinstance(self.open_early_at, int)
                or not 0 <= self.open_early_at <= 12000
                or 0 < self.open_early_at < 32):
            raise ValueError("Speech early-open size is outside supported bounds.")


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
    # Did any audio of this utterance really reach the player? The microphone
    # handoff and the owner switch may only treat a receipt as news about the
    # speaker when it does: an utterance that never started says nothing about
    # whether a cut the device did not confirm went silent.
    played: bool = False


class _AnyCancel:
    """İki bayraktan biri set olduğunda iptal: tur iptali ya da bayat üretim.

    Ses önde olsun diye: biten cevabın artık parçaları hâlâ üretiliyorsa, yeni
    komutun ilk parçası o üretimin arkasında bekliyordu (canlı ölçüm 18:34:
    sıcak bağlantı `hit` olmasına rağmen synth 2767 ms).
    """

    def __init__(self, *events):
        self._events = events

    def is_set(self) -> bool:
        return any(getattr(event, "is_set")() for event in self._events)

    def wait(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if self.is_set():
                return True
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(0.02)


class VoiceCoordinator:
    """Single-owner output worker: foreground is preferred, Core workers never wait.

    A speech adapter must cooperate with its cancellation Event and report its own
    real playback start through ``on_start``; ready WAV bytes are not speech.
    Interrupting speech never signals cancellation to the caller's background
    GoalState/work queue. ``stages`` and ``validate`` must stay local and cheap:
    no model, disk or network wait belongs on a control callback. ``echo_note``
    receives exactly the text whose audio the player just really started.
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
        echo_note: Callable[[SpeechRequest, str], None] | None = None,
        resource_scope: Callable[[SpeechRequest, str], object] | None = None,
        before_play: Callable[[SpeechRequest, threading.Event], None] | None = None,
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
        self._echo_note = echo_note
        # Only the production VoiceLane supplies this callback. Independent
        # VoiceCoordinator unit tests and the single output owner stay intact.
        self._resource_scope = resource_scope
        self._before_play = before_play
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
        self._delivered: dict[tuple, str] = {}   # announced result identity -> request id
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
            key = delivery_key(request)
            duplicate = not closed and key in self._delivered
            evicted: SpeechRequest | None = None
            full = False
            if not closed and not duplicate:
                self._sequence += 1
                priority = 0 if request.lane == "foreground" else 1
                entry = (priority, self._sequence, self._generation, request, spec, self._clock())
                try:
                    self._pending.put_nowait(entry)
                except queue.Full:
                    # A full notice queue must never cost the user an answer.
                    evicted = self._evict_notice_for_speech_locked(priority)
                    if evicted is not None:
                        # A second Full is unreachable: every other submitter holds
                        # this lock and the worker's get() only ever frees room.
                        self._pending.put_nowait(entry)
                    else:
                        full = True
                if not full and request.lane == "foreground" and self._current_lane == "background":
                    # Urgent conversation preempts only the audio notification, not its GoalState.
                    if self._current_cancel is not None:
                        self._cancel_reason = "VOICE_INTERRUPTED"
                        self._current_cancel.set()
                if not full and key is not None:
                    self._delivered[key] = request.request_id
                    while len(self._delivered) > DELIVERED_RESULTS_KEPT:
                        self._delivered.pop(next(iter(self._delivered)))
        if closed:
            self._notify(request, "rejected", "VOICE_CLOSED")
            return False
        if duplicate:
            # §7: one result is announced once. The claim belongs to the utterance
            # that already holds it, so this refusal cannot cancel that one.
            self._notify(request, "rejected", "VOICE_DUPLICATE_DELIVERY")
            return False
        if full:
            self._notify(request, "rejected", "VOICE_QUEUE_FULL")
            return False
        if evicted is not None:
            self._notify(evicted, "cancelled", "VOICE_NOTICE_EVICTED")
        self._stage(request, "accepted")
        return True

    def _evict_notice_for_speech_locked(self, priority: int) -> SpeechRequest | None:
        """Free exactly one slot by coalescing the stalest waiting notification.

        Called while the queue is full. Only a WAITING notice less urgent than
        the arrival is eligible: the utterance already in the player is preempted
        by the caller, and a queued foreground answer is itself user speech —
        dropping it would answer the newest question by discarding an earlier
        real one. Because the condition needs a strictly higher priority, a
        background arrival never evicts anything and keeps its own typed
        backpressure receipt instead. Within the eligible notices the oldest
        loses first, since a newer notification already supersedes its
        information; the priority queue pops notices in submission order, so the
        first eligible entry it yields is the oldest.
        """
        waiting = self._drain_waiting_locked()
        # The entry's first field is the lane-derived urgency, so a strict
        # comparison cannot promote a notice over an answer.
        index = next((pos for pos, item in enumerate(waiting) if item[0] > priority), -1)
        if index < 0:
            for item in waiting:
                self._pending.put_nowait(item)
            return None
        dropped = waiting.pop(index)
        for item in waiting:
            self._pending.put_nowait(item)
        return dropped[3]

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

    def current_request_id(self) -> str:
        """Read the existing output owner; this snapshot grants no cut authority."""
        with self._lock:
            return self._current_request.request_id if self._current_request is not None else ""

    def interrupt_speech(self, *, expected_request_id: str = "") -> tuple[SpeechRequest, ...]:
        """Interrupt playback and acknowledge all queued audio, not Core work.

        The cut utterances are returned so the caller can see exactly which
        speech this stop covered; deciding what that means for later answers is
        not the coordinator's authority and nothing here signals a cancellation
        to a GoalState or work queue.
        """
        with self._lock:
            active = self._current_request
            if expected_request_id and (active is None or active.request_id != expected_request_id):
                return ()
            if not expected_request_id:
                self._generation += 1
            self._cancel_reason = "VOICE_INTERRUPTED"
            if self._current_cancel is not None:
                self._current_cancel.set()
            discarded = self._drain_waiting_locked()
            if expected_request_id:
                kept=[item for item in discarded if item[3].owner!=active.owner]
                discarded=[item for item in discarded if item[3].owner==active.owner]
                for item in kept:
                    self._pending.put_nowait(item)
        stopped = tuple(([active] if active is not None else [])
                        + [item[3] for item in discarded])
        for item in discarded:
            self._notify(item[3], "cancelled", "VOICE_INTERRUPTED")
        return stopped

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

    def _await_prefetch(self, worker: threading.Thread, cancel: threading.Event,
                        limit: float = 120.0) -> bool:
        """Wait for the next chunk without ignoring a stop signal or a hung provider.

        A prefetched synthesis runs on its own thread; joining it blindly would
        make an interruption (or a stuck provider) wait for audio the user already
        stopped caring about. Returns False when it must not be awaited further.
        """
        deadline = time.monotonic() + limit
        while worker.is_alive():
            if cancel.is_set() or time.monotonic() >= deadline:
                return False
            worker.join(timeout=0.05)
        return True

    def _expired(self, request: SpeechRequest, enqueued_at: float) -> bool:
        return bool(request.ttl_seconds) and self._clock() - enqueued_at >= request.ttl_seconds

    def _stage(self, request: SpeechRequest, stage: str) -> None:
        if self._stages is None:
            return
        try:
            self._stages(request, stage)
        except Exception:
            _record_failure('modules/voice_core.py:stage')

    def _note_played(self, request: SpeechRequest, text: str) -> None:
        """Hand the owning adapter the exact words whose audio really started.

        A long answer is played in chunks, so only the chunk currently on the
        speaker may suppress a matching microphone result. Registering the whole
        utterance at its first start would silently discard the user's own words
        taken from a part Jarvis has not read yet.
        """
        if self._echo_note is None:
            return
        try:
            self._echo_note(request, text)
        except Exception:
            _record_failure('modules/voice_core.py:echo_note')

    def _cancelled_reason(self) -> str:
        with self._lock:
            return self._cancel_reason

    def _notify(self, request: SpeechRequest, status: str, reason: str,
                *, played: bool = False) -> None:
        if not played:
            # An utterance that never started is not a delivery: Core may re-offer
            # the same result (a full queue, an interrupt) and must not be silenced
            # by its own earlier attempt.
            with self._lock:
                key = delivery_key(request)
                if self._delivered.get(key) == request.request_id:
                    self._delivered.pop(key, None)
        receipt = SpeechReceipt(request.request_id, request.owner, request.voice_id, status, reason,
                                turn_id=request.turn_id, event_id=request.event_id,
                                goal_id=request.goal_id, kind=request.kind, played=played)
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
            stale = threading.Event()
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
                status, reason = "played", "VOICE_PLAYBACK_RETURNED"
                announced_ready = False
                announced_start = False

                def start_notifier(chunk: str):
                    """The real player boundary for this chunk, not for the whole answer."""
                    def on_start() -> None:
                        nonlocal announced_start
                        if not announced_start:
                            announced_start = True
                            self._stage(request, "playback_started")
                        self._note_played(request, chunk)
                    return on_start

                try:
                    self._stage(request, "synthesizing")
                    chunks = [chunk for chunk in speech_chunks(
                        request.text, request.open_early_at) if chunk.strip()]
                    # Prepare the NEXT chunk while the current one is still on the
                    # speaker. Synthesizing strictly after each playback ended made
                    # the voice stop between chunks: the user hears the answer as
                    # stuttering even though every chunk played completely.
                    prefetched: dict[int, tuple[threading.Thread, dict]] = {}

                    def synthesize_chunk(chunk: str) -> bytes:
                        # Kilit çağrı boyunca bir kez alınır (aşağıdaki with);
                        # parça başına almak paralel hazırlıkta çakışıyordu.
                        # `stale`: tur bitince artık parçaların üretimi kesilir,
                        # böylece yeni komut tek "tts" kilidini beklemez.
                        return self._synthesize(spec, chunk, _AnyCancel(cancel, stale))

                    def prefetch(index: int, depth: int = 1) -> None:
                        # `depth` > 1 hazırlığı öne alır: cümle bazlı üretimde tek
                        # tek beklemek konuşmayı yeniden duraklatırdı. Hepsi tek
                        # "tts" kilidi altında çalışır; aynı sağlayıcı için ikinci
                        # bir kilit talebi reddedilirdi (LeaseConflict).
                        for ahead in range(index, min(index + depth, len(chunks))):
                            _prefetch_one(ahead)

                    def _prefetch_one(index: int) -> None:
                        if index >= len(chunks) or index in prefetched:
                            return
                        box: dict = {}

                        def work() -> None:
                            try:
                                box["audio"] = synthesize_chunk(chunks[index])
                            except BaseException as exc:   # noqa: BLE001 - re-raised below
                                box["error"] = exc

                        worker = threading.Thread(target=work, daemon=True,
                                                  name="jarvis-tts-prefetch")
                        prefetched[index] = (worker, box)
                        worker.start()

                    # Bütün hazırlık TEK "tts" kilidi altında: paralel parçalar aynı
                    # sağlayıcıyı kullanır, ikinci bir kilit talebi reddedilirdi.
                    _tts_scope = (nullcontext() if self._resource_scope is None
                                  else self._resource_scope(request, "tts"))
                    with _tts_scope:
                        prefetch(0, SPEECH_PARALLEL_SYNTH)
                        for position, chunk in enumerate(chunks):
                            if cancel.is_set():
                                status, reason = "cancelled", self._cancelled_reason()
                                break
                            pending = prefetched.pop(position, None)
                            if pending is None:
                                audio = synthesize_chunk(chunk)
                            else:
                                worker, box = pending
                                if not self._await_prefetch(worker, cancel):
                                    if cancel.is_set():
                                        status, reason = "cancelled", self._cancelled_reason()
                                        break
                                    # Never claim audio that is still being produced; the
                                    # existing adapter failure path reports it honestly.
                                    status, reason = "failed", "VOICE_PREFETCH_TIMEOUT"
                                    break
                                if "error" in box:
                                    raise box["error"]
                                audio = box.get("audio")
                            if cancel.is_set():
                                status, reason = "cancelled", self._cancelled_reason()
                                break
                            if not isinstance(audio, bytes) or not audio:
                                status, reason = "failed", "VOICE_EMPTY_AUDIO"
                                break
                            if not announced_ready:
                                announced_ready = True
                                self._stage(request, "audio_ready")
                            if self._before_play is not None:
                                self._before_play(request,cancel)
                            if cancel.is_set():
                                status, reason = 'cancelled', self._cancelled_reason()
                                break
                            if self._expired(request, enqueued_at):
                                status, reason = "cancelled", "VOICE_TTL_EXPIRED"
                                break
                            invalid = self._validity(request)
                            if invalid:
                                status, reason = "cancelled", invalid
                                break
                            prefetch(position + 1, SPEECH_PARALLEL_SYNTH)
                            started_at = time.monotonic()
                            cpu_before = _cpu_window()
                            if self._resource_scope is None:
                                self._play(audio, cancel, start_notifier(chunk))
                            else:
                                with self._resource_scope(request, "output_device"):
                                    self._play(audio, cancel, start_notifier(chunk))
                            # Chunk timing is the evidence for a stuttering answer: a
                            # long play next to its own audio length is a device stall,
                            # a long prepare is a pipeline gap, and a chunk that burns
                            # a whole core of CPU time explains why the device starves.
                            voice_log.info("speech_chunk index=%s of=%s chars=%s play_ms=%.0f %s %s",
                                           position + 1, len(chunks), len(chunk),
                                           (time.monotonic() - started_at) * 1000,
                                           _device_timing(self._play),
                                           _cpu_report(cpu_before, started_at))
                            if cancel.is_set():
                                status, reason = "cancelled", self._cancelled_reason()
                                break
                    stale.set()      # biten cevabın artık parçaları üretilmesin
                    for worker, _box in prefetched.values():
                        worker.join(timeout=0.5)
                    self._notify(request, status, reason, played=announced_start)
                except Exception as exc:
                    _record_failure('modules/voice_core.py:adapter')
                    stale.set()
                    # An adapter may declare the exact outcome it could not prove
                    # (a stop the device never confirmed). That declaration can only
                    # downgrade the receipt: an adapter can never claim "played",
                    # so an unproven cut cannot be filed as a user interrupt the
                    # microphone handoff or the UI would then trust.
                    declared = getattr(exc, "speech_status", "")
                    declared_reason = getattr(exc, "speech_reason", "")
                    if (declared in {"failed", "cancelled", "rejected"}
                            and isinstance(declared_reason, str) and declared_reason.strip()):
                        self._notify(request, declared, declared_reason,
                                     played=announced_start)
                    else:
                        self._notify(request, "cancelled" if cancel.is_set() else "failed",
                                     self._cancelled_reason() if cancel.is_set() else "VOICE_ADAPTER_FAILED",
                                     played=announced_start)
            finally:
                with self._lock:
                    if self._current_cancel is cancel:
                        self._current_cancel = None
                        self._current_request = None
                        self._current_lane = None
                self._pending.task_done()
