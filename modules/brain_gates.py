"""Bounded, non-authoritative gates for the canonical Brain migration.

The state gate only recognizes exact replies to already-observed bounded
protocols.  The fast gate only recognizes exact deterministic shortcuts.
Neither gate routes semantic requests or mutates the observed state.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping

from modules.brain_contracts import ActiveContext, ContextReference
from modules.confirmation import decision


_CONTINUE = frozenset({"devam", "devam et", "sürdür", "surdur", "hedef devam", "hedef sürdür", "hedef surdur"})
_CANCEL = frozenset({"iptal", "vazgeç", "vazgec", "boşver", "bosver"})
_JOB_CONTINUE = frozenset({"devam", "devam et", "sürdür", "surdur"})
_JOB_OPEN = frozenset({"interrupted", "incomplete", "approval"})
_GOAL_CLOSED = frozenset({"done", "cancelled"})
_YES = frozenset({"evet", "tamam", "olur", "onayla", "onaylıyorum", "onayliyorum"})
_PENDING_SESSION_IDS = frozenset({
    "pending_confirm", "pending_action", "pending_organize", "pending_msg",
    "pending_level", "pending_voice", "pending_event_title", "pending_app",
    "pending_weather_location", "pending_request", "pending_desktop", "pending_visual",
})
_VOICE_NAMES = frozenset({
    "kerem", "defne", "liam", "olivia", "noah", "mia",
    "mert", "zeynep", "emir", "asya", "ahmet", "emel", "andrew", "ava", "brian", "emma",
})


@dataclass(frozen=True)
class GateObservation:
    owner: str
    request_id: str
    gate: str
    matched: bool
    reason_code: str
    protocol: str | None = None
    selection: str | int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "request_id": self.request_id,
            "gate": self.gate,
            "matched": self.matched,
            "reason_code": self.reason_code,
            "protocol": self.protocol,
            "selection": self.selection,
        }


def _required(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} boş olamaz.")
    return value


def _norm(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = value.translate(str.maketrans("İI", "iı")).lower().replace("’", "'")
    return re.sub(r"\s+", " ", text).strip(" .!?;:,")


def _value(reference: ContextReference) -> Any:
    return reference.provenance.get("value")


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _validate_context(owner: str, request_id: str, active_context: ActiveContext) -> None:
    if not isinstance(active_context, ActiveContext):
        raise ValueError("active_context ActiveContext olmalı.")
    if active_context.owner != owner:
        raise ValueError("ActiveContext owner eşleşmiyor.")
    if active_context.request_id != request_id:
        raise ValueError("ActiveContext request_id eşleşmiyor.")


def _validate_reference(reference: ContextReference, owner: str, request_id: str) -> None:
    if not isinstance(reference, ContextReference):
        raise ValueError("state_references yalnız ContextReference taşımalı.")
    if reference.owner != owner:
        raise ValueError("State reference başka owner'a ait.")
    ref_request = reference.provenance.get("request_id")
    if ref_request is not None and str(ref_request).strip() and str(ref_request) != request_id:
        raise ValueError("State reference request_id eşleşmiyor.")
    value = _mapping(_value(reference))
    embedded_owner = value.get("owner") if value is not None else None
    if embedded_owner is not None and str(embedded_owner) != owner:
        raise ValueError("Pending state başka owner'a ait.")


def _refs(active_context: ActiveContext, state_references: tuple[ContextReference, ...], owner: str, request_id: str) -> tuple[ContextReference, ...]:
    if not isinstance(state_references, tuple):
        raise ValueError("state_references tuple olmalı.")
    rows = (
        active_context.pending_references
        + active_context.active_goal_references
        + active_context.active_task_references
        + state_references
    )
    unique: list[ContextReference] = []
    seen: set[int] = set()
    for reference in rows:
        _validate_reference(reference, owner, request_id)
        marker = id(reference)
        if marker not in seen:
            seen.add(marker)
            unique.append(reference)
    return tuple(unique)


def _hit(owner: str, request_id: str, gate: str, protocol: str, selection: str | int, reason: str) -> GateObservation:
    return GateObservation(owner, request_id, gate, True, reason, protocol, selection)


def _miss(owner: str, request_id: str, gate: str, reason: str) -> GateObservation:
    return GateObservation(owner, request_id, gate, False, reason)


def _confirmation(text: str, *, extra: Iterable[str] = ()) -> str | None:
    result = decision(text, extra=tuple(extra))
    if result is True:
        return "yes"
    if result is False:
        return "no"
    return None


def _goal_open(reference: ContextReference) -> bool:
    return reference.kind == "goal" and reference.source == "goal_state" and str(reference.provenance.get("state") or "") not in _GOAL_CLOSED


def _goal_match(reference: ContextReference, text: str, owner: str, request_id: str) -> GateObservation | None:
    if not _goal_open(reference):
        return None
    state = str(reference.provenance.get("state") or "")
    if state == "approval" and text in {"evet", "onaylıyorum", "onayliyorum", "onayla", "hedef onayla"}:
        return _hit(owner, request_id, "state", "goal.approval", "yes", "BOUNDED_GOAL_APPROVAL")
    if text in _CANCEL or text == "hedef iptal":
        return _hit(owner, request_id, "state", "goal.cancel", "cancel", "BOUNDED_GOAL_CANCEL")
    if text in _CONTINUE:
        return _hit(owner, request_id, "state", "goal.resume", "resume", "BOUNDED_GOAL_RESUME")
    return None


def _job_match(reference: ContextReference, text: str, owner: str, request_id: str, *, goal_open: bool) -> GateObservation | None:
    if goal_open or reference.source != "task_agents" or reference.kind != "task_job":
        return None
    state = str(reference.provenance.get("state") or "")
    if state not in _JOB_OPEN or reference.provenance.get("stale") is True:
        return None
    if text in _JOB_CONTINUE:
        return _hit(owner, request_id, "state", "job.resume", "resume", "BOUNDED_JOB_RESUME")
    if text in _CANCEL:
        return _hit(owner, request_id, "state", "job.cancel", "cancel", "BOUNDED_JOB_CANCEL")
    return None


def _session_match(reference: ContextReference, text: str, owner: str, request_id: str) -> GateObservation | None:
    if reference.source != "session_state" or reference.id not in _PENDING_SESSION_IDS:
        return None
    value = _value(reference)
    data = _mapping(value)

    if reference.id == "pending_app":
        if data is None:
            return None
        choices = data.get("choices")
        if not isinstance(choices, (tuple, list)) or not choices or not all(isinstance(item, str) and item.strip() for item in choices):
            return None
        if text in _CANCEL:
            return _hit(owner, request_id, "state", "session.pending_app.cancel", "cancel", "BOUNDED_APP_CANCEL")
        numeric = re.fullmatch(r"(\d+)(?:\s*(?:numara|numarayı|olanı|aç))?", text)
        if numeric:
            index = int(numeric.group(1))
            if 1 <= index <= len(choices):
                return _hit(owner, request_id, "state", "session.pending_app.select", choices[index - 1], "BOUNDED_APP_SELECTION")
            return None
        matches = [item for item in choices if _norm(item) == text]
        if len(matches) == 1:
            return _hit(owner, request_id, "state", "session.pending_app.select", matches[0], "BOUNDED_APP_SELECTION")
        return None

    if reference.id == "pending_action":
        if data is None or data.get("stage") == "clarify":
            return None
        answer = _confirmation(text)
        return _hit(owner, request_id, "state", "session.pending_action.confirm", answer, "BOUNDED_ACTION_CONFIRM") if answer else None

    if reference.id == "pending_organize":
        answer = _confirmation(text, extra=("düzenle", "duzenle", "evet düzenle", "evet duzenle"))
        return _hit(owner, request_id, "state", "session.pending_organize.confirm", answer, "BOUNDED_ORGANIZE_CONFIRM") if answer else None

    if reference.id == "pending_confirm":
        answer = _confirmation(text)
        return _hit(owner, request_id, "state", "session.pending_confirm.confirm", answer, "BOUNDED_FINAL_CONFIRM") if answer else None

    if reference.id == "pending_msg":
        if data is None or data.get("stage") != "confirm":
            return None
        answer = _confirmation(text, extra=("gönder", "gonder", "evet gönder", "evet gonder", "gönder gitsin", "gonder gitsin"))
        return _hit(owner, request_id, "state", "session.pending_msg.confirm", answer, "BOUNDED_MESSAGE_CONFIRM") if answer else None

    if reference.id == "pending_event_title":
        if data is None or "confirm" not in data:
            return None
        answer = _confirmation(text)
        return _hit(owner, request_id, "state", "session.pending_event_title.confirm", answer, "BOUNDED_EVENT_CONFIRM") if answer else None

    if reference.id == "pending_level":
        options = {"ses": "volume", "parlaklık": "brightness", "parlaklik": "brightness"}
        selection = options.get(text)
        return _hit(owner, request_id, "state", "session.pending_level.select", selection, "BOUNDED_LEVEL_SELECTION") if selection else None

    if reference.id == "pending_visual":
        if data is None or data.get("stage") != "source":
            return None
        options = {"sohbet": "chat", "dosya": "file"}
        selection = options.get(text)
        return _hit(owner, request_id, "state", "session.pending_visual.select", selection, "BOUNDED_VISUAL_SELECTION") if selection else None

    if reference.id == "pending_voice":
        if text in _CANCEL:
            return _hit(owner, request_id, "state", "session.pending_voice.cancel", "cancel", "BOUNDED_VOICE_CANCEL")
        pending = _norm(value)
        if pending == "sor" and text in _VOICE_NAMES:
            return _hit(owner, request_id, "state", "session.pending_voice.select", text, "BOUNDED_VOICE_SELECTION")
        if pending in {"tr", "ml"} and text in {"erkek", "kadın", "kadin", "bayan"}:
            gender = "kadın" if text in {"kadın", "kadin", "bayan"} else "erkek"
            return _hit(owner, request_id, "state", "session.pending_voice.select", f"{pending}:{gender}", "BOUNDED_VOICE_SELECTION")
        return None

    # weather location, generic pending_request and generic pending_desktop are
    # deliberately observations only; they require semantic/domain handling.
    return None


def _learning_match(reference: ContextReference, text: str, owner: str, request_id: str) -> GateObservation | None:
    if reference.source != "learning" or reference.id != "pending_facts":
        return None
    values = reference.provenance.get("value")
    if not isinstance(values, (tuple, list)) or not values:
        return None
    approve_all = re.fullmatch(r"(?:öğrendi(?:k)?lerini(?:n)?\s+(?:hepsini\s+)?|hepsini\s+)(?:kaydet|onayla|hatırla|sakla)", text)
    reject_all = re.fullmatch(r"(?:öğrendi(?:k)?lerini(?:n)?\s+(?:hepsini\s+)?(?:kaydetme|sil|unut|at|onaylama)|hiçbirini\s+(?:kaydetme|hatırlama))", text)
    numbered = re.fullmatch(r"öğrendiğin\s+(\d+)\s*\.?\s*(?:bilgiyi|maddeyi|şeyi)?\s*(kaydetme|kaydet|onayla|hatırla|sil|unut)", text)
    if approve_all:
        return _hit(owner, request_id, "state", "learning.pending_facts.select", "approve:all", "BOUNDED_LEARNING_SELECTION")
    if reject_all:
        return _hit(owner, request_id, "state", "learning.pending_facts.select", "reject:all", "BOUNDED_LEARNING_SELECTION")
    if numbered:
        number = int(numbered.group(1))
        if not 1 <= number <= len(values):
            return None
        action = "approve" if numbered.group(2) in {"kaydet", "onayla", "hatırla"} else "reject"
        return _hit(owner, request_id, "state", "learning.pending_facts.select", f"{action}:{number}", "BOUNDED_LEARNING_SELECTION")
    return None


def _hoca_match(reference: ContextReference, text: str, owner: str, request_id: str) -> GateObservation | None:
    if reference.source != "profile.hoca" or reference.id != "lesson.pending":
        return None
    options = {
        "sonraki adım": "next", "bir sonraki adım": "next", "ilerle": "next", "geç": "next",
        "dersi bitir": "exit", "dersten çık": "exit",
    }
    selection = options.get(text)
    return _hit(owner, request_id, "state", "hoca.lesson.control", selection, "BOUNDED_HOCA_CONTROL") if selection else None


def _desktop_match(reference: ContextReference, text: str, owner: str, request_id: str) -> GateObservation | None:
    if reference.source != "desktop_agent" or reference.id != "consent" or reference.provenance.get("status") != "consent":
        return None
    yes = {"evet", "izin ver", "izin veriyorum", "tamam", "olur"}
    no = {"hayır", "hayir", "izin verme", "verme", "istemiyorum"}
    if text in yes:
        return _hit(owner, request_id, "state", "desktop.consent", "yes", "BOUNDED_DESKTOP_CONSENT")
    if text in no:
        return _hit(owner, request_id, "state", "desktop.consent", "no", "BOUNDED_DESKTOP_CONSENT")
    return None


def _photo_match(reference: ContextReference, text: str, owner: str, request_id: str) -> GateObservation | None:
    if reference.source != "engine_commands" or reference.id != "pending_photo":
        return None
    cancel = {"vazgeç", "vazgec", "iptal", "boşver", "bosver", "gerek yok", "hiçbir şey", "hicbir sey", "bir şey yapma", "bir sey yapma"}
    if text in cancel:
        return _hit(owner, request_id, "state", "phone_photo.cancel", "cancel", "BOUNDED_PHOTO_CANCEL")
    return None


def exact_state_gate(
    *,
    owner: str,
    request_id: str,
    text: str,
    active_context: ActiveContext,
    state_references: tuple[ContextReference, ...] = (),
) -> GateObservation:
    """Observe whether *this utterance* exactly fits an observed bounded protocol."""
    owner = _required("owner", owner)
    request_id = _required("request_id", request_id)
    if not isinstance(text, str):
        raise ValueError("text string olmalı.")
    _validate_context(owner, request_id, active_context)
    rows = _refs(active_context, state_references, owner, request_id)
    normalized = _norm(text)
    goal_open = any(_goal_open(reference) for reference in rows)
    matches: list[GateObservation] = []
    for reference in rows:
        match = (
            _goal_match(reference, normalized, owner, request_id)
            or _job_match(reference, normalized, owner, request_id, goal_open=goal_open)
            or _session_match(reference, normalized, owner, request_id)
            or _learning_match(reference, normalized, owner, request_id)
            or _hoca_match(reference, normalized, owner, request_id)
            or _desktop_match(reference, normalized, owner, request_id)
            or _photo_match(reference, normalized, owner, request_id)
        )
        if match is not None:
            matches.append(match)
    if not matches:
        return _miss(owner, request_id, "state", "NO_BOUNDED_STATE_MATCH")
    if len(matches) != 1:
        return _miss(owner, request_id, "state", "MULTIPLE_BOUNDED_STATE_MATCHES")
    return matches[0]


def deterministic_fast_gate(
    *,
    owner: str,
    request_id: str,
    text: str,
    active_context: ActiveContext,
    sleeping: bool = False,
    source: str = "yazı",
) -> GateObservation:
    """Recognize only exact local shortcuts; return an observation, never dispatch."""
    owner = _required("owner", owner)
    request_id = _required("request_id", request_id)
    if not isinstance(text, str):
        raise ValueError("text string olmalı.")
    _validate_context(owner, request_id, active_context)
    normalized = _norm(text)
    src = _norm(source)

    self_close = re.fullmatch(
        r"(?:(?:hey\s+)?jarvis(?:'i|i)?|kendini|uygulamayı|uygulamayi)\s+"
        r"(?:kapat|kapan|çık|cik|sonlandır|sonlandir)\w*",
        normalized,
    )
    if self_close and src != "telefon" and not re.search(r"\b(?:bilgisayar|pc|windows|sistem)\b", normalized):
        return _hit(owner, request_id, "fast", "fast.engine.close", "close", "EXACT_ENGINE_CONTROL")

    if normalized in {"uyu", "uyku moduna geç", "uyku moduna gec", "uyku modu", "hazırda bekle", "hazirda bekle", "beklemeye geç", "beklemeye gec", "bekleme moduna geç", "bekleme moduna gec"}:
        return _hit(owner, request_id, "fast", "fast.engine.sleep", "sleep", "EXACT_ENGINE_CONTROL")

    if sleeping and normalized in {"uyan", "kalk", "uyku modundan çık", "uyku modundan cik"}:
        return _hit(owner, request_id, "fast", "fast.engine.wake", "wake", "EXACT_ENGINE_CONTROL")

    mic = re.fullmatch(r"mikrofon(?:u|umu)?\s+(kapat|aç|ac)", normalized)
    if mic:
        selection = "mic_off" if mic.group(1) == "kapat" else "mic_on"
        return _hit(owner, request_id, "fast", "fast.mic.toggle", selection, "EXACT_MIC_CONTROL")

    if re.fullmatch(r"(?:konuşmayı|konuşmanı|cevabı|seslendirmeyi)\s+(?:durdur|kes|sustur)", normalized):
        return _hit(owner, request_id, "fast", "fast.speech.stop", "stop_speaking", "EXACT_SPEECH_CONTROL")

    if normalized in {"saat kaç", "saat kac", "saat ne", "saati"}:
        return _hit(owner, request_id, "fast", "fast.time.read", "time", "EXACT_LOCAL_READ")

    if re.fullmatch(
        r"(?:bugün\s+)?(?:günlerden(?:\s+ne)?|hangi\s+gün(?:deyiz)?|ayın\s+kaçı|"
        r"tarih(?:i)?(?:\s+(?:ne|nedir|kaç|söyle|göster))?|bugünün\s+tarihi)(?:\s+(?:ne|nedir|söyle|göster))?",
        normalized,
    ):
        return _hit(owner, request_id, "fast", "fast.date.read", "date", "EXACT_LOCAL_READ")

    if normalized in {"sistem durumu", "bilgisayar durumu", "pc durumu"}:
        return _hit(owner, request_id, "fast", "fast.system.status", "status", "EXACT_LOCAL_READ")

    return _miss(owner, request_id, "fast", "NO_EXACT_FAST_MATCH")
