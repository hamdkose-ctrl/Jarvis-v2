"""Bounded, non-authoritative gates for the canonical Brain migration.

The state gate only recognizes exact replies to already-observed bounded
protocols.  The fast gate only recognizes exact deterministic shortcuts.
Neither gate routes semantic requests or mutates the observed state.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import time
from typing import Any, Iterable, Mapping

from modules.brain_contracts import ActiveContext, ContextReference
from modules.confirmation import choice_index, decision


_CONTINUE = frozenset({"devam", "devam et", "sürdür", "surdur", "hedef devam", "hedef sürdür", "hedef surdur"})
_CANCEL = frozenset({"iptal", "vazgeç", "vazgec", "boşver", "bosver"})
_JOB_CONTINUE = frozenset({"devam", "devam et", "sürdür", "surdur"})
_JOB_OPEN = frozenset({"interrupted", "incomplete", "approval"})
_GOAL_CLOSED = frozenset({"done", "cancelled"})
_YES = frozenset({"evet", "tamam", "olur", "onayla", "onaylıyorum", "onayliyorum"})
_PENDING_SESSION_IDS = frozenset({
    "pending_confirm", "pending_action", "pending_organize", "pending_msg",
    "pending_level", "pending_voice", "pending_event_title", "pending_app",
    "pending_weather_location", "pending_desktop", "pending_visual",
})
_VOICE_NAMES = frozenset({
    "kerem", "defne", "liam", "olivia", "noah", "mia",
    "mert", "zeynep", "emir", "asya", "ahmet", "emel", "andrew", "ava", "brian", "emma",
})
# The answer vocabulary of the "ses mi parlaklık mı?" question. Only the property noun may
# appear: a number or another domain word makes the sentence a new request, not this answer.
_LEVEL_SELECT = {
    "ses": "volume", "sesi": "volume", "sesin": "volume", "sesini": "volume",
    "ses seviyesi": "volume", "ses seviyesini": "volume",
    "parlaklık": "brightness", "parlaklığı": "brightness", "parlaklığını": "brightness",
    "parlaklik": "brightness", "parlakligi": "brightness", "parlakligini": "brightness",
    "ekran parlaklığı": "brightness", "ekran parlaklığını": "brightness",
    "ekran parlaklıgı": "brightness", "ekran parlakligi": "brightness",
}
_LEVEL_VERB_TAIL = re.compile(r"\s+(?:yap|olsun|ayarla|yapar mısın|yapsana)$")
# The answer vocabulary of "sohbetten mi, dosyadan mı?": the source noun plus an optional
# "olsun/yap/kullan". A longer sentence is a new request and keeps the question open.
_VISUAL_CHAT_SELECT = re.compile(
    r"(?:sohbet(?:ten|i)?|konuşma(?:dan|yı)?|geçmiş(?:ten)?)(?:\s+(?:olsun|yap|kullan))?")
_VISUAL_FILE_SELECT = re.compile(
    r"(?:dosya(?:dan|yı)?|belge(?:den|yi)?)(?:\s+(?:olsun|yap|kullan))?")
# The answer to "ne zaman?" is a whole time expression; the planner still parses the value.
_WHEN_DAY = (
    r"(?:bugün|yarın|öbür gün|ertesi gün|haftaya|"
    r"(?:haftaya\s+)?(?:pazartesi|salı|çarşamba|perşembe|cuma|cumartesi|pazar)|"
    r"\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?|"
    r"\d{1,2}\s+(?:ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık)(?:\s+\d{4})?)"
)
_WHEN_TIME = (
    r"(?:(?:saat\s+)?\d{1,2}(?:[:.]\d{2}|['’]?(?:da|de|ta|te))|"
    r"saat\s+\d{1,2}(?:\s*(?:buçuk|çeyrek))?|"
    r"(?:sabah|öğlen|öğleden sonra|akşam|gece)\s+\d{1,2}(?:(?:[:.]\d{2})|['’]?(?:da|de|ta|te))?|"
    r"öğlen)"
)
_WHEN_RELATIVE = r"(?:(?:\d+|bir|iki|üç|beş|on)\s*(?:dakika|dk|saat)\s*(?:sonra|içinde)|\d+\s*gün\s*sonra)"
_EVENT_WHEN_ANSWER = re.compile(rf"(?:{_WHEN_RELATIVE}|{_WHEN_DAY}(?:\s+{_WHEN_TIME})?|{_WHEN_TIME})")


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
    seen: set[tuple[str, str, str, str]] = set()
    for reference in rows:
        _validate_reference(reference, owner, request_id)
        # Bir bounded state iki taşıyıcıdan da gelebilir (ActiveContext + gözlem referansları);
        # nesne kimliği bunları ayırır ve aynı durum iki protokol hit'i sayar.
        marker = (reference.owner, reference.source, reference.kind, reference.id)
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


def _level_selection(text: str) -> str | None:
    base = _LEVEL_VERB_TAIL.sub("", text).strip()
    return _LEVEL_SELECT.get(base)


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
        if data is None:
            return None
        if data.get("stage") == "clarify":
            expires = data.get("expires")
            expired = isinstance(expires, (int, float)) and not isinstance(expires, bool) and expires < time.time()
            # An active clarification owns its own cancel: the user is closing the question the
            # system just asked, not issuing a long-lived Goal/Job control.
            if text in _CANCEL and not expired:
                return _hit(owner, request_id, "state", "session.pending_action.clarify_cancel", "cancel", "BOUNDED_ACTION_CLARIFY_CANCEL")
            # Only an answer that selects exactly one OFFERED choice belongs to the clarification.
            # Open-ended clarify (no resume choices) is never consumed: the reply is a new request.
            resume = _mapping(data.get("resume"))
            choices = resume.get("choices") if resume is not None else None
            if not isinstance(choices, (tuple, list)) or not choices or not all(isinstance(c, str) and c.strip() for c in choices):
                return None
            if expired:
                return None
            index = choice_index(text, choices)
            if index is None:
                return None
            return _hit(owner, request_id, "state", "session.pending_action.clarify_select", index + 1, "BOUNDED_ACTION_CLARIFY_SELECT")
        answer = _confirmation(text)
        return _hit(owner, request_id, "state", "session.pending_action.confirm", answer, "BOUNDED_ACTION_CONFIRM") if answer else None

    if reference.id == "pending_organize":
        answer = _confirmation(text, extra=("düzenle", "duzenle", "evet düzenle", "evet duzenle"))
        return _hit(owner, request_id, "state", "session.pending_organize.confirm", answer, "BOUNDED_ORGANIZE_CONFIRM") if answer else None

    if reference.id == "pending_confirm":
        answer = _confirmation(text)
        return _hit(owner, request_id, "state", "session.pending_confirm.confirm", answer, "BOUNDED_FINAL_CONFIRM") if answer else None

    if reference.id == "pending_msg":
        if data is not None and data.get("stage") in ("to", "text") and text in _CANCEL:
            return _hit(owner, request_id, "state", "session.pending_msg.cancel", "cancel", "BOUNDED_MESSAGE_CANCEL")
        if data is None or data.get("stage") != "confirm":
            return None
        answer = _confirmation(text, extra=("gönder", "gonder", "evet gönder", "evet gonder", "gönder gitsin", "gonder gitsin"))
        return _hit(owner, request_id, "state", "session.pending_msg.confirm", answer, "BOUNDED_MESSAGE_CONFIRM") if answer else None

    if reference.id == "pending_event_title":
        if isinstance(value, str) and value.strip() and text in _CANCEL:
            return _hit(owner, request_id, "state", "session.pending_event_title.cancel", "cancel", "BOUNDED_EVENT_CANCEL")
        if isinstance(value, str) and value.strip() and _EVENT_WHEN_ANSWER.fullmatch(text):
            return _hit(owner, request_id, "state", "session.pending_event_title.answer", "when", "BOUNDED_EVENT_WHEN")
        if data is None or "confirm" not in data:
            return None
        answer = _confirmation(text, extra=("ekle", "yine de ekle", "ekle gitsin"))
        return _hit(owner, request_id, "state", "session.pending_event_title.confirm", answer, "BOUNDED_EVENT_CONFIRM") if answer else None

    if reference.id == "pending_level":
        selection = _level_selection(text)
        return _hit(owner, request_id, "state", "session.pending_level.select", selection, "BOUNDED_LEVEL_SELECTION") if selection else None

    if reference.id == "pending_visual":
        if data is None or data.get("stage") != "source":
            return None
        if _VISUAL_CHAT_SELECT.fullmatch(text):
            return _hit(owner, request_id, "state", "session.pending_visual.select", "chat", "BOUNDED_VISUAL_SELECTION")
        if _VISUAL_FILE_SELECT.fullmatch(text):
            return _hit(owner, request_id, "state", "session.pending_visual.select", "file", "BOUNDED_VISUAL_SELECTION")
        return None

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

    if reference.id == "pending_weather_location":
        # "Hangi şehir?" question: only the cancel tokens are exact protocols. City names and
        # every other sentence stay with Understanding (ANSWER_TO_PENDING vs new request).
        if text in {"iptal", "vazgeç", "vazgec"}:
            return _hit(owner, request_id, "state", "session.pending_weather_location.cancel", "cancel", "BOUNDED_WEATHER_CANCEL")
        return None

    # Generic pending_desktop is deliberately observation-only; desktop consent has its own
    # domain protocol and free text requires semantic/domain handling.
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


# Explicit state precedence. A bare reply belongs to the interaction the system just asked
# about; a long-lived Goal/background Job may use it only when no foreground interaction claims
# it. Ranks are a fixed product contract, not list order:
#   0 explicit-qualified Goal control ("hedef iptal/onayla/devam")
#   1 foreground session interaction (pending_confirm/action/msg/organize/...)
#   2 domain-specific foreground prompt (learning/hoca/desktop consent/photo)
#   3 long-lived Goal state
#   4 background Job
# Equal rank means the utterance is genuinely ambiguous for this turn: fail closed.
_QUALIFIED_GOAL_PREFIX = "hedef "
_RANK_EXPLICIT_GOAL = 0
_RANK_SESSION = 1
_RANK_DOMAIN_PROMPT = 2
_RANK_GOAL = 3
_RANK_JOB = 4


def _state_rank(protocol: str, normalized: str) -> int:
    if protocol.startswith("session."):
        return _RANK_SESSION
    if protocol.startswith("goal."):
        return _RANK_EXPLICIT_GOAL if normalized.startswith(_QUALIFIED_GOAL_PREFIX) else _RANK_GOAL
    if protocol.startswith("job."):
        return _RANK_JOB
    return _RANK_DOMAIN_PROMPT


def _foreground_open(reference: ContextReference) -> bool:
    """Is this reference an interaction the system just asked the user about?

    Open-ended foreground states (weather city, free message text, photo follow-up) do not
    own every exact token. A bare cancel belongs to that interaction's semantic layer
    (Understanding), not to a long-lived Goal/Job; an unrelated continue may still resume
    background work.
    """
    if reference.source == "session_state" and reference.id in _PENDING_SESSION_IDS:
        if reference.id == "pending_action":
            return reference.provenance.get("active") is not False
        return True
    return (
        (reference.source == "learning" and reference.id == "pending_facts")
        or (reference.source == "profile.hoca" and reference.id == "lesson.pending")
        or (reference.source == "desktop_agent" and reference.id == "consent")
        or (reference.source == "engine_commands" and reference.id == "pending_photo")
    )


def exact_state_gate(
    *,
    owner: str,
    request_id: str,
    text: str,
    active_context: ActiveContext,
    state_references: tuple[ContextReference, ...] = (),
) -> GateObservation:
    """Observe whether *this utterance* exactly fits an observed bounded protocol.

    When several observed states match the same token, the fixed foreground-first precedence
    above selects exactly one owner. A tie at the winning rank stays ambiguous and fails closed."""
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
    best_rank = min(_state_rank(match.protocol or "", normalized) for match in matches)
    winners = [match for match in matches if _state_rank(match.protocol or "", normalized) == best_rank]
    if len(winners) != 1:
        return _miss(owner, request_id, "state", "MULTIPLE_BOUNDED_STATE_MATCHES")
    if (best_rank in {_RANK_GOAL, _RANK_JOB} and winners[0].selection == "cancel"
            and any(_foreground_open(reference) for reference in rows)):
        # A cancel token is not an exact protocol of the open-ended foreground interaction, but
        # it still belongs to that interaction's semantic layer: Understanding decides whether it
        # closes the question. Background work must not steal it. Unrelated continue ("devam")
        # keeps its Job/Goal owner.
        return _miss(owner, request_id, "state", "FOREGROUND_STATE_REQUIRES_UNDERSTANDING")
    return winners[0]


def goal_status_selection(text: object) -> str | None:
    """Single canonical recognizer for the exact goal-status phrases ('summary' | 'details').

    The engine queue answers these while the command loop is busy, so it must share this
    recognizer instead of keeping its own phrase list.
    """
    normalized = _norm(text)
    if normalized in {"hedef durumu", "işin durumu"}:
        return "summary"
    if normalized == "hedef ayrıntıları":
        return "details"
    return None


_TABLE_SUBJECT = (r"(?:(?:bunu|şunu|onu|bu|şu|mevcut|son)\s+(?:yanıt\w*|cevap\w*|listeyi|sonucu)?\s*|"
                  r"(?:yazıları|yazilari|metni|metin)\s+)?")
_TABLE_NOUN = r"(?:tablo|table|toplo)(?:'?(?:ya|ye|suna|laştır|a|e))?(?:\s+ha?line)?"
_TABLE_VERB = (r"(?:yap(?:ar\s+mısın)?|ver(?:ir\s+mısın)?|göster|çıkar|dök|oluştur|getir|çevir|cevir|"
               r"dönüştür|donustur)")
_TABLE_TAIL = r"(?:\s+(?:kısaca|madde\s+madde|lütfen|lwtfen|benim\s+için))?\s*"

# "tablo" kelimesi geçen + herhangi bir fiil geçen cümleleri sahiplenmek yerine,
# tüm cümlenin tabloya çevirme isteği olması aranır.
_TABLE_REQUEST = re.compile(rf"^{_TABLE_SUBJECT}{_TABLE_NOUN}\s+{_TABLE_VERB}{_TABLE_TAIL}$", re.I)


def table_request(text: object) -> bool:
    """Tek exact tabloya-çevirme tanıyıcısı; command_manager ve yüzeyler bunu paylaşır.

    'tabloda hangi sensörler yazıyordu' ya da 'yarınki toplantıda tablo gösterme, özeti söyle'
    gibi başka bir isteğin parçası olan cümleleri tüketmez.
    """
    normalized = _norm(text)
    return bool(normalized) and _TABLE_REQUEST.fullmatch(normalized) is not None


# "bu konuşmayı özetle": hedef dosya değil, oturumun kendi sohbet tarihidir. Cümlenin tamamı
# bu istek olmalı; bir dosyadan ya da başka bir isteğin parçasından söz eden cümle kapılmaz.
_CONVERSATION_NOUN = r"(?:konuşma|sohbet|yazışma|söylediklerimiz)'?\w*"
_CONVERSATION_LEAD = (r"(?:(?:bu|şu|bizim|aramızdaki|bugün|bugünkü|dün|dünkü|şimdiki|mevcut|son|tüm|bütün|"
                      r"az\s+önceki)\s+)*")
_CONVERSATION_VERB = (r"(?:özetle\w*|özetler\w*|özetini\s+(?:çıkar|söyle|ver)|özete\s+(?:çevir|dönüştür)|"
                      r"analizini\s+çıkar|analiz\s+et\w*|incele\w*)")
_CONVERSATION_TAIL = r"(?:\s+(?:mısın|misin|musun|musun|mu|lütfen|benim\s+için|kısaca))*\s*"
_CONVERSATION_SUMMARY_REQUEST = re.compile(
    rf"^{_CONVERSATION_LEAD}{_CONVERSATION_NOUN}\s+(?:(?:kısaca|madde\s+madde|bana|lütfen)\s+)*"
    rf"{_CONVERSATION_VERB}{_CONVERSATION_TAIL}$", re.I)


def conversation_summary_request(text: object) -> bool:
    """Tek exact konuşma-özeti tanıyıcısı; fast gate ve command kapısı aynı kaynağı paylaşır."""
    normalized = _norm(text)
    return bool(normalized) and _CONVERSATION_SUMMARY_REQUEST.fullmatch(normalized) is not None


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
        r"(?:kapat|kapan|çık|cik|sonlandır|sonlandir)",
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

    if conversation_summary_request(normalized):
        return _hit(owner, request_id, "fast", "fast.conversation.summary", "summarize", "EXACT_CONVERSATION_READ")

    status = goal_status_selection(text)
    if status is not None:
        return _hit(owner, request_id, "fast", "fast.goal.status", status, "EXACT_LOCAL_READ")

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