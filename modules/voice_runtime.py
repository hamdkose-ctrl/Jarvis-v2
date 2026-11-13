"""Single always-active speech owner for the engine (Piper opt-in, exact Edge default).

The user's per-profile voice key and rate remain the only identity authority. An
explicit, valid Voice Core config selects offline Piper voices; otherwise the
existing exact Edge catalog runs inside the SAME VoiceCoordinator, so installs
without Piper keep speaking. An invalid explicit config fails closed and never
silently falls back to another engine or identity. All synthesis/playback runs in
the coordinator's dedicated worker; no LLM/Ollama, automatic model download or
mid-request voice switch. This is a gated integration, not evidence of
human-audible Windows output.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
import shutil
import threading
import time

from modules.diagnostics import record_failure as _record_failure
from modules.voice_core import (
    SpeechRequest, VoiceCatalog, VoiceCoordinator, VoiceSpec, speech_pace_note,
)
from modules.voice_edge import EdgePlayer, EdgeSynthesizer
from modules.voice_offline import OfflineVoiceUnavailable, PiperSynthesizer, WavePlayer


CONFIG_NAME = "voice_core.json"
_ALLOWED_VOICES = frozenset({
    "tr_erkek", "tr_kadin", "ml_erkek", "ml_kadin", "ml_erkek2", "ml_kadin2",
})
_ACTIVE_LOCK = threading.Lock()
_ACTIVE = None
_BLOCK_LEGACY = False  # explicit configuration fault must not trigger a second voice
# A recency bound on "whose speech was last audible", so the record cannot grow
# with uptime; the mute scope of "sus" only ever consults the current owner.
_LAST_AUDIBLE_OWNERS_KEPT = 8
# In-flight utterances whose output boundaries are still being timed. A receipt
# always clears its own record, so this only bounds requests that never produced
# one; the number is a memory ceiling, not a delivery guarantee.
_PACE_RECORDS_KEPT = 32
_log = logging.getLogger("jarvis")


class VoiceConfigurationError(ValueError):
    pass


def _read_config(path: Path):
    if not path.is_file():
        return None
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise VoiceConfigurationError("Voice Core yapılandırma dosyası okunamadı.") from exc
    if size > 32_768:
        raise VoiceConfigurationError("Voice Core yapılandırması çok büyük.")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise VoiceConfigurationError("Voice Core yapılandırması okunamadı.") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema", "enabled", "voices"}:
        raise VoiceConfigurationError("Voice Core yapılandırma şeması geçersiz.")
    if raw["schema"] != "voice_core.config.v1" or type(raw["enabled"]) is not bool:
        raise VoiceConfigurationError("Voice Core yapılandırma sürümü veya enabled geçersiz.")
    if not raw["enabled"]:
        return None
    voices = raw["voices"]
    if not isinstance(voices, dict) or not voices or len(voices) > len(_ALLOWED_VOICES):
        raise VoiceConfigurationError("Voice Core ses listesi boş veya geçersiz.")
    specs = []
    for key, entry in voices.items():
        if key not in _ALLOWED_VOICES or not isinstance(entry, dict) or set(entry) != {"label", "model"}:
            raise VoiceConfigurationError("Voice Core bilinmeyen ses veya katalog alanı.")
        label, model = entry["label"], entry["model"]
        if not isinstance(label, str) or not label.strip() or len(label) > 100:
            raise VoiceConfigurationError("Voice Core ses etiketi geçersiz.")
        if not isinstance(model, str) or not model or len(model) > 200:
            raise VoiceConfigurationError("Voice Core model yolu geçersiz.")
        asset = Path(model)
        if asset.is_absolute() or ".." in asset.parts or asset.suffix.lower() != ".onnx":
            raise VoiceConfigurationError("Voice Core yalnız yerel .onnx model yolu kabul eder.")
        # PiperSynthesizer revalidates path confinement and regular files on
        # each request, also preventing model replacement via symlink.
        specs.append(VoiceSpec(key, label, "piper", model))
    return VoiceCatalog(tuple(specs))


def _edge_catalog(runtime) -> VoiceCatalog:
    """The living exact-Edge voice table is the default catalog's single source."""
    voices = getattr(getattr(runtime, "voice", None), "VOICES", None)
    if not isinstance(voices, dict) or not voices:
        raise VoiceConfigurationError("Edge ses kataloğu bulunamadı.")
    specs = []
    for key, entry in voices.items():
        if key not in _ALLOWED_VOICES or not isinstance(entry, (tuple, list)) or len(entry) != 2:
            raise VoiceConfigurationError("Edge ses kataloğu geçersiz.")
        label, name = entry
        if not isinstance(label, str) or not label.strip() or len(label) > 100:
            raise VoiceConfigurationError("Edge ses etiketi geçersiz.")
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise VoiceConfigurationError("Edge ses adı geçersiz.")
        specs.append(VoiceSpec(key, label, "edge", name))
    return VoiceCatalog(tuple(specs))


def maybe_start(runtime):
    """Return (voice_lane, piper_enabled); the lane is the single active owner.

    Absent/disabled Piper config selects the exact Edge catalog inside the same
    coordinator. An invalid explicit config raises and fails closed (no Edge
    fallback), so a requested-but-broken local voice never becomes another voice.
    """
    global _BLOCK_LEGACY
    _BLOCK_LEGACY = False
    data_dir = getattr(runtime, "DATA_DIR", None)
    catalog = _read_config(data_dir / CONFIG_NAME) if isinstance(data_dir, Path) else None
    if catalog is not None:
        lane = VoiceLane(runtime, catalog, PiperSynthesizer(data_dir / "voice_models"), WavePlayer())
        enabled = True
    else:
        lane = VoiceLane(runtime, _edge_catalog(runtime), EdgeSynthesizer(), EdgePlayer())
        enabled = False
    try:
        register(lane)
    except VoiceConfigurationError:
        lane.close()
        raise
    return lane, enabled


def register(lane):
    global _ACTIVE
    with _ACTIVE_LOCK:
        if _ACTIVE is not None and _ACTIVE is not lane:
            raise VoiceConfigurationError("Birden fazla Voice Core çıkış sahibi açılamaz.")
        _ACTIVE = lane


def active():
    with _ACTIVE_LOCK:
        return _ACTIVE


def block_legacy_on_fault():
    """An invalid explicit Voice Core configuration cannot select old TTS."""
    global _BLOCK_LEGACY
    _BLOCK_LEGACY = True


def legacy_blocked() -> bool:
    return bool(_BLOCK_LEGACY)


def interrupt_active() -> bool:
    """Stop audible speech now, and keep that speech's own late answers off the speaker.

    "Sus" is the speech scope of the three cancel scopes: the queued and active
    audio is interrupted here, and the turn that audio carried is speech-muted, so
    the remaining chunks of that answer and a model response for the same turn that
    arrives later cannot restart output the user just stopped. The mute is bounded
    to that turn: a background job the user has in flight but that was never given
    to the voice owner keeps its future spoken result, because "sus" was about the
    speech being heard, not about every request. Nothing is cancelled: Core keeps
    the written result, the GoalState and the running work, and "dur/stop" stays
    the explicit Core-level stop.

    The mute is applied after the cut, so a same-turn answer enqueued inside that
    window would carry the post-interrupt generation and survive the fence. The
    turn-targeted drop after the mute closes it: whatever arrived in between is
    discarded by identity, and whatever arrives later is refused by the now-visible
    mute at its own gate.
    """
    lane = active()
    if lane is None:
        return False
    turns = lane.interrupt()
    if not turns:
        return True
    try:
        from modules import requests_state
        owner = lane.runtime.pc_profile().slug
        for turn_id in turns:
            requests_state.mute_speech(owner, turn_id)
    except Exception:
        _record_failure("modules/voice_runtime.py:mute_speech")
    for turn_id in turns:
        invalidate(turn_id=turn_id)
    return True


def handoff_to_listen(timeout: float = 0.6) -> bool:
    """Safe push-to-talk handoff: cut speech, verify output stopped, then allow mic.

    Returns True only when no speech is outstanding (the player acknowledged the
    interrupt) AND the newest cut was confirmed by the device, so the microphone
    never opens onto Jarvis's own speaker output. This is half-duplex
    stop-then-listen, not full-duplex AEC. If the player does not stop within the
    bound, or the stop was never confirmed, it returns False and the caller keeps
    its protection. The wait is on local playback acknowledgement only — never
    model/disk/network.
    """
    lane = active()
    if lane is None:
        return True
    if not lane.is_busy():
        # Nothing is queued, but a cut the device never confirmed may still be
        # audible; receipt acknowledgement alone is not proof of silence.
        return not lane.stop_unconfirmed()
    lane.interrupt()
    deadline = time.monotonic() + max(0.0, timeout)
    while lane.is_busy() and time.monotonic() < deadline:
        time.sleep(0.01)
    return not lane.is_busy() and not lane.stop_unconfirmed()


def on_owner_switch(previous_owner: str, timeout: float = 0.6) -> bool:
    """A user switch must never leak the previous owner's audio to the new one.

    Targeted (not a blind clear): drop the previous owner's queued AND active
    speech, then verify the real player acknowledged the stop within a bound.
    Because the caller reassigns the active profile first, a request that had not
    yet started is also rejected by the per-chunk owner gate — this closes the
    window between a synthesis/playback start and the switch. Returns False (and
    records a privacy-safe failure) when the player did not stop in time, so the
    switch never claims a stop that was not verified.

    What a False still guarantees: the caller has already re-pointed the audible
    owner, so no further chunk of the previous user's utterance — queued or the
    remainder of the one being played — can start after this returns. Only the
    audio the physical device still holds is unverified, which is exactly what the
    caller must not paper over. Nothing here touches Core work: a running goal or
    background job of the previous user keeps its written result and its own
    cancellation scope ("dur/stop"), and the new user's session cannot be silenced
    by this call because it selects the previous owner alone.
    """
    lane = active()
    if lane is None or not previous_owner:
        return True
    lane.invalidate(owner=previous_owner)
    deadline = time.monotonic() + max(0.0, timeout)
    while lane.outstanding_owner(previous_owner) and time.monotonic() < deadline:
        time.sleep(0.01)
    # The receipt completes as soon as the player returns, so an empty outstanding
    # set alone is not proof of silence: a driver can confirm the request and still
    # carry live audio. The switch therefore has to require the same proof the
    # microphone handoff requires, or it claims a stop the device never made.
    if lane.outstanding_owner(previous_owner) or lane.stop_unconfirmed():
        _record_failure("modules/voice_runtime.py:owner_switch_stop")
        return False
    return True


def invalidate(**selectors) -> int:
    """Core says a result is no longer current; drop only that result's audio.

    This is the production entry for the explicit invalidation the contract has
    always allowed: a caller that changes or cancels a reminder, goal result or
    approval uses it so an utterance still waiting in the queue never announces
    something the user has just corrected. Nothing is invented here — an empty
    selector is refused by the coordinator, unrelated speech keeps its order, and
    the written chat result and GoalState are untouched. Returns how many
    utterances were dropped (0 when no owner is registered).
    """
    lane = active()
    if lane is None:
        return 0
    try:
        return lane.invalidate(**selectors)
    except Exception:
        _record_failure("modules/voice_runtime.py:invalidate")
        return 0


def announce_active(text: str, *, background: bool = True) -> bool:
    """Route direct local notices/STT feedback through the same owner when active.

    background=True for privacy/device notices; background=False for foreground
    STT feedback ("anlayamadım") that answers the user's current turn.
    """
    lane = active()
    if lane is None:
        return bool(_BLOCK_LEGACY)
    runtime = lane.runtime
    if not runtime.flags.get("speak", True):
        return True  # mute never starts a new private-mode voice notice
    owner = runtime.pc_profile()
    voice_key = owner.data["prefs"].get("voice") or "tr_erkek"
    raw_rate = owner.data["prefs"].get("rate", 0)
    rate = raw_rate if type(raw_rate) is int and -40 <= raw_rate <= 40 else 0
    try:
        lane.say(owner.slug, voice_key, text, background=background, rate=rate)
    except ValueError:
        # No fallback to Edge or a different local identity.
        runtime.emit("system", "Seçilen ses kurulu değil; bildirim yalnız yazılı gösterildi.")
    return True


class VoiceLane:
    def __init__(self, runtime, catalog, synthesize, play):
        self.runtime = runtime
        self.catalog = catalog
        self._synthesize = synthesize
        self._lock = threading.RLock()
        self._outstanding = {}
        self._last_audible = {}  # owner -> turn id of the speech it last heard
        # request id -> the real output boundaries this utterance crossed, kept only
        # until its receipt reports how long the whole thing took.
        self._pace = {}
        # True while a cut the device never confirmed is the newest word about the
        # speaker; the mic handoff and the UI idle claim both consult it.
        self._stop_unconfirmed = False
        self.busy_event = threading.Event()
        self._closed = False
        self._coordinator = VoiceCoordinator(
            catalog, synthesize, play, self._receipt, max_pending=8,
            stages=self._stage_event, validate=self._privacy_gate,
            echo_note=self._echo_note,
        )

    def _echo_note(self, request: SpeechRequest, text: str) -> None:
        """Register the words that really started on the speaker, one chunk at a time.

        The living echo guard must reject the speaker's own output returning to
        the mic, so only audio that actually started is registered: a
        privacy-rejected or cancelled utterance never plays and must not suppress
        a matching user command. Registering the whole answer at its first start
        would have done the same to the not-yet-read tail, so this is fed by the
        per-chunk player boundary instead of the UI stage event.
        """
        try:
            from modules import stt_guard
            stt_guard.note_said(text)
        except Exception:
            _record_failure("modules/voice_runtime.py:echo")

    def _pace_mark(self, request: SpeechRequest, stage: str) -> None:
        """Record when this utterance really crossed each output boundary, by request id.

        "The voice arrives seconds after the text" cannot be fixed by guessing, and
        the stage events are the boundaries themselves: the queue hand-off, the
        provider synthesis, the first ready audio and the player's own admission. The
        marks carry identifiers and numbers only — never the words, the asset name or
        the user — and a bounded FIFO keeps a never-played request from growing with
        uptime.
        """
        with self._lock:
            entry = self._pace.get(request.request_id)
            if entry is None:
                entry = self._pace[request.request_id] = {"voice": request.voice_id,
                                                          "chars": len(request.text),
                                                          "marks": {}}
            entry["marks"].setdefault(stage, time.monotonic())
            while len(self._pace) > _PACE_RECORDS_KEPT:
                self._pace.pop(next(iter(self._pace)))

    def _pace_report(self, receipt) -> None:
        """One log line per finished utterance: the waits it went through, in ms."""
        with self._lock:
            entry = self._pace.pop(receipt.request_id, None)
        if entry is None:
            return
        marks = entry["marks"]

        def span(start: str, end: str):
            if start not in marks or end not in marks:
                return None
            return int((marks[end] - marks[start]) * 1000)

        note = speech_pace_note(
            request_id=receipt.request_id, voice_id=receipt.voice_id,
            chars=entry["chars"], status=receipt.status, reason=receipt.reason_code,
            queue_ms=span("accepted", "synthesizing"),
            synth_ms=span("synthesizing", "audio_ready"),
            first_audio_ms=span("accepted", "playback_started"),
            total_ms=None if "accepted" not in marks
            else int((time.monotonic() - marks["accepted"]) * 1000))
        try:
            _log.info(note)
        except Exception:
            _record_failure("modules/voice_runtime.py:pace")

    def _stage_event(self, request: SpeechRequest, stage: str) -> None:
        """Present the real player boundary, never enqueue/WAV readiness, as speech.

        ``playback_started`` comes from the adapter's own player callback, so the
        orb only claims "speaking" when audio actually starts. Identity travels as
        JSON in the existing extra channel so the UI can correlate the related
        card; a late stage event never idles a newer utterance (idle is owned by
        the busy-guarded receipt) and never fronts the user's window.
        """
        if self._closed:
            return
        self._pace_mark(request, stage)
        if stage == "playback_started":
            # Remember whose speech the speaker last carried: "sus" may only mute
            # the turn the user actually heard, never a job that never spoke.
            if request.turn_id:
                with self._lock:
                    self._last_audible.pop(request.owner, None)
                    self._last_audible[request.owner] = request.turn_id
                    while len(self._last_audible) > _LAST_AUDIBLE_OWNERS_KEPT:
                        self._last_audible.pop(next(iter(self._last_audible)))
        try:
            if request.owner != self.runtime.pc_profile().slug:
                return
            if stage == "playback_started":
                self.runtime.emit("state", "speaking")
            identity = {
                "speech_id": request.request_id, "voice_id": request.voice_id,
                "kind": request.kind, "turn_id": request.turn_id,
                "event_id": request.event_id, "goal_id": request.goal_id,
                "state_version": request.state_version,
                "artifact_id": request.artifact_id, "approval_id": request.approval_id,
            }
            self.runtime.emit("speech", stage, json.dumps(identity, ensure_ascii=False))
        except Exception:
            _record_failure("modules/voice_runtime.py:stage")

    def _privacy_gate(self, request: SpeechRequest) -> str:
        """Audible owner/privacy/suspension boundary, checked at enqueue and per chunk.

        Offline Piper voices are unaffected by privacy mode. Online Edge voices
        must not egress in local-only mode; identity is kept. Separately, a queued
        utterance whose owner is no longer the active desktop user must never reach
        the physical speaker: switching users mid-queue must not leak the previous
        user's audio to the new one. The UI stage/receipt already gate on owner;
        this closes the audible boundary. It fails closed so an unreadable profile
        never plays audio to an unknown user.

        The third check is the speech cancel scope (§6): "Sus" mutes the turn whose
        audio it stopped, so the remaining chunks of that answer and a late model
        response for the same turn never restart audio. Only the turn that was on
        the speaker is muted — a different job the user has running keeps its own
        future spoken result. This is presentation only: the written result, the
        GoalState and the running work are untouched. An unreadable mute check keeps
        speaking, because a lost answer would be worse than the noise the user asked
        to stop, and unlike the owner check this is a preference, not a privacy
        boundary.
        """
        try:
            if request.owner != self.runtime.pc_profile().slug:
                return "VOICE_OWNER_SWITCHED"
        except Exception:
            _record_failure("modules/voice_runtime.py:owner_gate")
            return "VOICE_OWNER_SWITCHED"
        if request.turn_id:
            try:
                from modules import requests_state
                if requests_state.speech_muted(request.owner, request.turn_id):
                    return "VOICE_SUSPENDED_TURN"
            except Exception:
                _record_failure("modules/voice_runtime.py:mute_gate")
        spec = self.catalog.require(request.voice_id)
        if spec.backend == "edge":
            from modules import privacy
            if privacy.mode() == "yerel":
                return "VOICE_PRIVACY_LOCAL_ONLY"
        return ""

    def check_voice(self, voice_id: str):
        """Do not persist a new voice choice when its local model is missing.

        An exact Edge voice is a real catalog identity; its online availability is
        only known at synthesis, so it is never pre-blocked or substituted here.
        """
        spec = self.catalog.require(voice_id)
        if isinstance(self._synthesize, PiperSynthesizer):
            try:
                model_path = self._synthesize._model(spec)
            except OfflineVoiceUnavailable as exc:
                raise ValueError("Seçilen yerel ses modeli kurulu değil.") from exc
            metadata_path = Path(str(model_path) + ".json")
            if not metadata_path.is_file() or metadata_path.is_symlink():
                raise ValueError("Seçilen Piper modelinin doğrulanmış .onnx.json metaverisi eksik.")
            if not shutil.which("piper"):
                raise ValueError("Seçilen Piper motoru kurulu değil.")
        return spec

    def say(self, owner: str, voice_id: str, text: str, *,
            background: bool = False, rate: int = 0, kind: str = "reply",
            turn_id: str = "", event_id: str = "", goal_id: str = "", state_version: int = 0,
            artifact_id: str = "", approval_id: str = "", ttl_seconds: float = 0.0):
        """Enqueue without waiting for synthesis or blocking caller's Core work.

        An unknown identity raises (no receipt, no fallback). A bounded-queue,
        closed, invalid or privacy refusal is a typed rejected receipt and an
        already-acknowledged Event, never a silent drop or a second voice. The
        result identity (turn/event/goal/version/artifact) is supplied by the
        caller's Core context; voice never invents it and only carries it for
        presentation, duplicate protection and explicit invalidation.
        """
        voice_id = voice_id if isinstance(voice_id, str) else ""
        self.catalog.require(voice_id)  # explicit exact voice; no implicit fallback
        request_id = self.runtime.secrets.token_hex(16)
        request = SpeechRequest(owner=owner, request_id=request_id,
                                voice_id=voice_id, text=text,
                                lane="background" if background else "foreground",
                                rate=rate, kind=kind, turn_id=turn_id, event_id=event_id,
                                goal_id=goal_id, state_version=state_version,
                                artifact_id=artifact_id,
                                approval_id=approval_id, ttl_seconds=ttl_seconds)
        done = threading.Event()
        with self._lock:
            if self._closed:
                raise ValueError("Voice Core kapatılmış.")
            self._outstanding[request_id] = (owner, done)
            self.busy_event.set()
        try:
            accepted = self._coordinator.submit(request)
        except Exception:
            _record_failure("modules/voice_runtime.py:submit")
            self._forget(request_id)
            raise
        if not accepted:
            self._forget(request_id)
        return done

    def _forget(self, request_id: str):
        with self._lock:
            entry = self._outstanding.pop(request_id, None)
            if not self._outstanding:
                self.busy_event.clear()
        if entry is not None:
            entry[1].set()

    def outstanding_owner(self, owner: str) -> bool:
        """True while any accepted-but-unacknowledged request belongs to owner.

        The player/adapter acknowledges stop by completing its receipt, which
        forgets the id here; so a cleared set for the previous owner is the real
        stop signal, not a UI-hide assumption.
        """
        with self._lock:
            return any(current_owner == owner
                       for current_owner, _done in self._outstanding.values())

    def _notice_for(self, receipt) -> str | None:
        if receipt.status == "failed":
            if receipt.reason_code == "VOICE_STOP_UNCONFIRMED":
                return ("Ses kesilemedi; aygıt kesintiyi doğrulamadı. Başka sese geçilmedi, "
                        "yanıt yazılı korundu.")
            return "Seçilen ses üretilemedi veya oynatılamadı; başka sese geçilmedi, yanıt yazılı korundu."
        if receipt.status == "rejected":
            if receipt.reason_code == "VOICE_PRIVACY_LOCAL_ONLY":
                return "Yerel modda çevrimiçi ses buluta gönderilmez; ses tercihin korundu, yanıt yalnız yazılı gösterildi."
            if receipt.reason_code == "VOICE_QUEUE_FULL":
                return "Ses kuyruğu dolu; bu yanıtın sesi atlandı, yazılı sonuç korundu."
            if receipt.reason_code == "VOICE_CLOSED":
                return None
            if receipt.reason_code == "VOICE_OWNER_SWITCHED":
                return None  # another user's audio; this user gets their own result, not a notice
            if receipt.reason_code == "VOICE_SUSPENDED_TURN":
                return None  # the user asked for quiet; silence is the requested behavior
            if receipt.reason_code == "VOICE_DUPLICATE_DELIVERY":
                return None  # the same result was already announced; no second notice
            return "Ses bu sonuç için geçerli değil; yazılı sonuç korundu."
        return None

    def _receipt(self, receipt):
        # The device truth is recorded before any presentation decision, so a
        # stopped-but-unconfirmed cut cannot be answered with an "idle" UI state or
        # an open microphone while audio may still be on the speaker. A later
        # playback the device did acknowledge clears it: the newest word wins.
        #
        # Only a receipt whose audio really reached the player is news about the
        # speaker. An utterance that never started (a queued notice whose TTL
        # expired, a cancel accepted before its first chunk) says nothing about
        # whether the cut that is still audible ever went silent, so it must not
        # erase that proof — which is exactly how the microphone used to be handed
        # over over live audio again.
        with self._lock:
            if receipt.reason_code == "VOICE_STOP_UNCONFIRMED":
                self._stop_unconfirmed = True
            elif receipt.played and receipt.status in {"played", "cancelled"}:
                self._stop_unconfirmed = False
        self._forget(receipt.request_id)
        self._pace_report(receipt)
        if self._closed:
            return
        try:
            if receipt.owner == self.runtime.pc_profile().slug:
                notice = self._notice_for(receipt)
                if notice:
                    self.runtime.emit("system", notice)
                if not self.busy_event.is_set() and not self.stop_unconfirmed():
                    self.runtime.emit("state", "idle")
        except Exception:
            _record_failure("modules/voice_runtime.py:receipt")

    def stop_unconfirmed(self) -> bool:
        """True while the newest cut of this output owner was never device-confirmed."""
        with self._lock:
            return self._stop_unconfirmed

    def interrupt(self) -> tuple[str, ...]:
        """Cut audible audio and return exactly the turns that audio belonged to.

        The scope is the utterance in the player, the utterances still waiting in
        the speech queue, and the turn this owner last actually heard. A request
        the lane was never given is not in the scope, so stopping one conversation
        cannot silence a different job's later spoken result.
        """
        stopped = self._coordinator.interrupt_speech()  # NEVER cancels GoalState/worker
        # Busy remains set until the worker acknowledges pending receipts.
        turns = []
        for request in stopped:
            if request.turn_id and request.turn_id not in turns:
                turns.append(request.turn_id)
        owners = {request.owner for request in stopped}
        try:
            owners.add(self.runtime.pc_profile().slug)
        except Exception:
            _record_failure("modules/voice_runtime.py:interrupt_owner")
        for owner in sorted(owners):
            last = self._last_audible.get(owner)
            if last and last not in turns:
                turns.append(last)
        return tuple(turns)

    def invalidate(self, **selectors) -> int:
        """Drop queued/active audio for an explicit Core result identity."""
        return self._coordinator.invalidate(**selectors)

    def close(self):
        global _ACTIVE, _BLOCK_LEGACY
        with self._lock:
            self._closed = True
            self._pace.clear()
        self._coordinator.close()
        with _ACTIVE_LOCK:
            if _ACTIVE is self:
                _ACTIVE = None
                _BLOCK_LEGACY = False

    def is_busy(self) -> bool:
        return self.busy_event.is_set()
