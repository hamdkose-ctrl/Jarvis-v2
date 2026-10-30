"""Deterministic, non-authoritative Understanding proposal for canonical Brain v1.

This foundation consumes only caller-supplied canonical context, candidates,
resolved references, and the current user text. It does not read sources, mutate
state, run workers, grant authority, or wire itself into production routing.
"""
from __future__ import annotations

import re
from typing import Iterable

from modules.brain_contracts import (
    ActiveContext,
    Confidence,
    ContextAction,
    ContextReference,
    ConversationRelation,
    RequestKind,
    TemporalNeed,
    UnderstandingResult,
)


_CONTEXT_CONTROL = (
    "boşver",
    "bosver",
    "başka konu",
    "baska konu",
    "konuyu değiştir",
    "konuyu degistir",
)
_TOPIC_CHANGE = ("başka konu", "baska konu", "konuyu değiştir", "konuyu degistir")
_COMMAND_MARKERS = (
    " göster",
    " goster",
    " aç",
    " ac",
    " kapat",
    " oluştur",
    " olustur",
    " hazırla",
    " hazirla",
    " karşılaştır",
    " karsilastir",
    " ara",
    " bul",
    " indir",
    " yükle",
    " yukle",
    " sil",
    " gönder",
    " gonder",
    " hatırlat",
    " hatirlat",
    " uyar",
    " planla",
    " listele",
    " özetle",
    " ozetle",
)
_PLURAL_REFERENCE_MARKERS = (
    " iki ",
    "ikisini",
    "bunları",
    "bunlari",
    "dosyaları",
    "dosyalari",
    "hepsini",
    "karşılaştır",
    "karsilastir",
)
_CURRENT_MARKERS = (
    "şu an",
    "su an",
    "şu anda",
    "su anda",
    "şimdi",
    "simdi",
    "bugün",
    "bugun",
    "güncel",
    "guncel",
    "mevcut durum",
)
_RECENT_MARKERS = (
    "son gün",
    "son gun",
    "son hafta",
    "son ay",
    "son zaman",
    "yakın zamanda",
    "yakin zamanda",
    "en son haber",
)
_HISTORICAL_MARKERS = (
    "geçmiş",
    "gecmis",
    "eskiden",
    "tarihinde",
    "yılında",
    "yilinda",
    "tarihçe",
    "tarihce",
)
_STATIC_MARKERS = (
    " nedir",
    " ne demek",
    " nasıl çalışır",
    " nasil calisir",
    " kimdir",
    " açıkla",
    " acikla",
    " anlat",
)
_PENDING_PROTOCOL_TOKENS = frozenset({"evet", "hayır", "hayir", "yes", "no"})
_GENERIC_CHAT = ("merhaba", "selam", "nasılsın", "nasilsin", "teşekkür", "tesekkur")


def _required(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} boş olamaz.")
    return value


def _norm(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.casefold().strip().split())


def _reference_tuple(name: str, value: object, owner: str) -> tuple[ContextReference, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{name} tuple olmalı.")
    rows = tuple(value)
    for row in rows:
        if not isinstance(row, ContextReference):
            raise ValueError(f"{name} yalnız ContextReference taşımalı.")
        if row.owner != owner:
            raise ValueError(f"{name} başka owner referansı taşıyamaz.")
    return rows


def _contains_any(text: str, signals: Iterable[str]) -> bool:
    return any(signal in text for signal in signals)


def _is_context_control(text: str) -> bool:
    return any(text == signal or text.startswith(signal + " ") for signal in _CONTEXT_CONTROL)


def _is_topic_change(text: str) -> bool:
    return any(signal in text for signal in _TOPIC_CHANGE)


def _is_correction(text: str) -> bool:
    if text in {"boşver", "bosver"}:
        return True
    return " değil " in f" {text} " or " degil " in f" {text} "


def _looks_like_capability(text: str) -> bool:
    padded = f" {text} "
    return _contains_any(padded, _COMMAND_MARKERS)


def _plural_reference_intent(text: str) -> bool:
    padded = f" {text} "
    return _contains_any(padded, _PLURAL_REFERENCE_MARKERS)


def _temporal_need(text: str) -> TemporalNeed:
    if _contains_any(text, _CURRENT_MARKERS):
        return TemporalNeed.CURRENT
    if _contains_any(text, _RECENT_MARKERS):
        return TemporalNeed.RECENT
    if _contains_any(text, _HISTORICAL_MARKERS) or re.search(r"\b(?:1\d{3}|20\d{2}|2100)\b", text):
        return TemporalNeed.HISTORICAL
    padded = f" {text}"
    if _contains_any(padded, _STATIC_MARKERS):
        return TemporalNeed.STATIC
    return TemporalNeed.UNSURE


def _capability_hint(text: str, temporal_need: TemporalNeed) -> str | None:
    if ("not" in text or "notlar" in text) and _looks_like_capability(text):
        return "notes.read"
    if "hava" in text:
        return "weather.read.current" if temporal_need is TemporalNeed.CURRENT else "weather.read"
    if any(token in text for token in ("dosya", ".pdf", ".doc", "word")) and _looks_like_capability(text):
        return "files.read"
    if any(token in text for token in ("hatırlat", "hatirlat", "uyar")):
        return "reminder.propose"
    if any(token in text for token in (" ara", " bul")) and _looks_like_capability(text):
        return "research.search"
    return None


def _active_identity_set(active_context: ActiveContext) -> set[tuple[str, str]]:
    refs = (
        active_context.active_goal_references
        + active_context.active_task_references
        + active_context.active_artifacts
    )
    return {(row.kind, row.id) for row in refs}


def _continues_active(active_context: ActiveContext, references: tuple[ContextReference, ...]) -> bool:
    active = _active_identity_set(active_context)
    return any((row.kind, row.id) in active for row in references)


def _pending_field(reference: ContextReference) -> str:
    raw = reference.provenance.get("field")
    if isinstance(raw, str) and raw.strip():
        return _norm(raw)
    return _norm(reference.id)


def _is_pr6_protocol_answer(text: str) -> bool:
    if text in _PENDING_PROTOCOL_TOKENS:
        return True
    return bool(re.fullmatch(r"\d+", text))


def _answer_to_pending(text: str, active_context: ActiveContext) -> bool:
    if not active_context.pending_references:
        return False
    if not text or _is_pr6_protocol_answer(text):
        return False
    if _is_context_control(text) or _is_correction(text) or _looks_like_capability(text):
        return False
    if _contains_any(text, _GENERIC_CHAT):
        return False
    if "?" in text:
        return False

    words = text.split()
    for pending in active_context.pending_references:
        if pending.kind != "pending_state":
            continue
        field = _pending_field(pending)
        if "weather_location" in field and 1 <= len(words) <= 4:
            return True
        question = pending.provenance.get("question")
        if isinstance(question, str) and question.strip() and 1 <= len(words) <= 12:
            return True
    return False


def _ambiguity_for_references(text: str, references: tuple[ContextReference, ...]) -> tuple[str, ...]:
    if len(references) <= 1 or _plural_reference_intent(text) or _is_correction(text):
        return ()
    return ("multiple target references",)


def _correction_arguments(original_text: str, normalized: str) -> dict[str, object]:
    arguments: dict[str, object] = {"original_text": original_text}
    marker = " değil " if " değil " in f" {normalized} " else " degil "
    padded = f" {normalized} "
    if marker in padded:
        left, right = padded.split(marker, 1)
        rejected = left.strip()
        replacement = right.strip()
        if rejected:
            arguments["rejected_text"] = rejected
        if replacement:
            arguments["replacement_text"] = replacement
    return arguments


def understand(
    *,
    owner: str,
    request_id: str,
    text: str,
    active_context: ActiveContext,
    candidates: tuple[ContextReference, ...],
    references: tuple[ContextReference, ...],
) -> UnderstandingResult:
    """Return an immutable semantic proposal without taking Core authority."""
    owner = _required("owner", owner)
    request_id = _required("request_id", request_id)
    if not isinstance(text, str):
        raise ValueError("text string olmalı.")
    if not isinstance(active_context, ActiveContext):
        raise ValueError("active_context ActiveContext olmalı.")
    if active_context.owner != owner:
        raise ValueError("ActiveContext owner eşleşmiyor.")
    if active_context.request_id != request_id:
        raise ValueError("ActiveContext request_id eşleşmiyor.")
    _reference_tuple("candidates", candidates, owner)
    references = _reference_tuple("references", references, owner)

    normalized = _norm(text)
    temporal_need = _temporal_need(normalized)
    correction = _is_correction(normalized)
    topic_change = _is_topic_change(normalized)
    context_control = _is_context_control(normalized)
    ambiguities = _ambiguity_for_references(normalized, references)

    if topic_change:
        relation = ConversationRelation.TOPIC_CHANGE
    elif correction:
        relation = ConversationRelation.CORRECTION
    elif _answer_to_pending(normalized, active_context):
        relation = ConversationRelation.ANSWER_TO_PENDING
    elif _continues_active(active_context, references):
        relation = ConversationRelation.CONTINUE_ACTIVE
    else:
        relation = ConversationRelation.NEW_REQUEST

    if context_control:
        request_kind = RequestKind.CONTEXT_CONTROL
    elif ambiguities:
        request_kind = RequestKind.CLARIFY
    elif _looks_like_capability(normalized):
        request_kind = RequestKind.CAPABILITY
    else:
        request_kind = RequestKind.CHAT

    if topic_change:
        context_actions = (ContextAction.DROP_TOPIC,)
    elif correction:
        if normalized in {"boşver", "bosver"}:
            context_actions = (ContextAction.DROP_TOPIC,)
        else:
            context_actions = (ContextAction.REPLACE_REFERENCE,)
    else:
        context_actions = (ContextAction.KEEP,)

    reason_codes: list[str] = []
    if relation is ConversationRelation.ANSWER_TO_PENDING:
        reason_codes.append("SEMANTIC_PENDING_ANSWER")
    elif relation is ConversationRelation.CONTINUE_ACTIVE:
        reason_codes.append("ACTIVE_REFERENCE_CONTINUATION")
    elif relation is ConversationRelation.CORRECTION:
        reason_codes.append("USER_CORRECTION")
    elif relation is ConversationRelation.TOPIC_CHANGE:
        reason_codes.append("USER_TOPIC_CHANGE")
    else:
        reason_codes.append("NEW_REQUEST_DEFAULT")
    if ambiguities:
        reason_codes.append("MULTIPLE_TARGET_REFERENCES")

    confidence = Confidence.MEDIUM
    if relation in {
        ConversationRelation.ANSWER_TO_PENDING,
        ConversationRelation.CONTINUE_ACTIVE,
        ConversationRelation.CORRECTION,
        ConversationRelation.TOPIC_CHANGE,
    }:
        confidence = Confidence.HIGH
    if ambiguities:
        confidence = Confidence.LOW

    arguments = (
        _correction_arguments(text, normalized)
        if correction
        else {"original_text": text}
    )

    return UnderstandingResult(
        owner=owner,
        request_id=request_id,
        request_kind=request_kind,
        capability_hint=_capability_hint(normalized, temporal_need),
        arguments=arguments,
        references=references,
        conversation_relation=relation,
        temporal_need=temporal_need,
        context_actions=context_actions,
        confidence=confidence,
        ambiguities=ambiguities,
        assumptions=(),
        reason_codes=tuple(reason_codes),
        needs_input=bool(ambiguities),
    )
