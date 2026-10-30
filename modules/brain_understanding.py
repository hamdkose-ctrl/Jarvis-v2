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
_BOSVER = ("boşver", "bosver")
_COMMAND_TOKENS = (
    "göster",
    "goster",
    "aç",
    "ac",
    "kapat",
    "oluştur",
    "olustur",
    "hazırla",
    "hazirla",
    "karşılaştır",
    "karsilastir",
    "ara",
    "bul",
    "indir",
    "yükle",
    "yukle",
    "sil",
    "gönder",
    "gonder",
    "hatırlat",
    "hatirlat",
    "uyar",
    "planla",
    "listele",
    "özetle",
    "ozetle",
)
_NOTE_DOMAIN_TOKENS = (
    "not",
    "notu",
    "notum",
    "notlar",
    "notları",
    "notlari",
    "notlarım",
    "notlarim",
    "notlarımı",
    "notlarimi",
)
_WEATHER_DOMAIN_TOKENS = ("hava", "havayı", "havayi", "havanın", "havanin")
_FILE_DOMAIN_TOKENS = (
    "dosya",
    "dosyayı",
    "dosyayi",
    "dosyalar",
    "dosyaları",
    "dosyalari",
    "word",
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
    "yarın",
    "yarin",
)
_RECENT_MARKERS = (
    "son gün",
    "son gun",
    "son hafta",
    "son bir hafta",
    "son ay",
    "son zaman",
    "yakın zamanda",
    "yakin zamanda",
    "en son haber",
    "son haber",
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
    "dün",
    "dun",
    "dünkü",
    "dunku",
)
_STATIC_MARKERS = (
    " nedir",
    " ne demek",
    " ne anlama gelir",
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


def _require_reference_candidates(
    candidates: tuple[ContextReference, ...],
    references: tuple[ContextReference, ...],
) -> None:
    for reference in references:
        if not any(reference is candidate for candidate in candidates):
            raise ValueError("references yalnız supplied candidate nesnelerinden gelmeli.")


def _contains_any(text: str, signals: Iterable[str]) -> bool:
    return any(signal in text for signal in signals)


def _bounded_token(text: str, token: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(token)}(?!\w)", text) is not None


def _contains_command_token(text: str, tokens: Iterable[str] = _COMMAND_TOKENS) -> bool:
    return any(_bounded_token(text, token) for token in tokens)


def _quoted_terms(text: str) -> tuple[str, ...]:
    return tuple(match.strip() for match in re.findall(r"[\"“]([^\"”]+)[\"”]", text) if match.strip())


def _is_literal_command_usage(text: str) -> bool:
    quoted = _quoted_terms(text)
    if not quoted or not any(term in _COMMAND_TOKENS for term in quoted):
        return False
    literal_markers = (
        "metinde",
        "kelimesi",
        "kelimesini",
        "sözcüğü",
        "sözcüğünü",
        "sozcugu",
        "sozcugunu",
        "komutu",
        "yazıyor",
        "yaziyor",
        " yaz",
    )
    return _contains_any(f" {text}", literal_markers)


def _is_meta_language(text: str) -> bool:
    if re.fullmatch(r"(?:ara|bul)\s+ne demek\??", text) is not None:
        return True
    if re.fullmatch(
        r"\S+\s+(?:kelimesi|sözcüğü|sozcugu|fiili|sayısı|sayisi)\s+"
        r"(?:ne demek|ne anlama gelir|nedir)\??",
        text,
    ) is not None:
        return True
    if re.fullmatch(
        r"\S+\s+(?:kelimesini|sözcüğünü|sozcugunu)\s+\S+\s+(?:çevir|cevir)\??",
        text,
    ) is not None:
        return True
    if re.fullmatch(r"\S+\s+model\s+(?:ne demek|nedir)\??", text) is not None:
        return True
    if " ifadesi " in f" {text} " and re.search(
        r"(?:ne demek|ne anlama gelir|nedir|kaç günü anlatır|kac gunu anlatir)\??$",
        text,
    ) is not None:
        return True
    if " olmayan " in f" {text} " and re.search(r"(?:ne demek|ne anlama gelir|nedir)\??$", text) is not None:
        return True
    if _is_literal_command_usage(text) and re.search(r"(?:ne demek|ne anlama gelir|nedir)\??$", text) is not None:
        return True
    return False


def _is_bosver_control(text: str) -> bool:
    if _is_meta_language(text):
        return False
    return any(re.match(rf"^{re.escape(signal)}(?:$|[\s,;.!])", text) is not None for signal in _BOSVER)


def _is_context_control(text: str) -> bool:
    return _is_bosver_control(text) or text in _TOPIC_CHANGE


def _is_topic_change(text: str) -> bool:
    return text in _TOPIC_CHANGE


def _replacement_parts(text: str) -> tuple[str, str] | None:
    if "?" in text:
        return None
    cleaned = text.strip().rstrip(".!").strip()
    had_negative_prefix = False
    prefix = re.match(r"^(?:hayır|hayir),?\s+", cleaned)
    if prefix is not None:
        had_negative_prefix = True
        cleaned = cleaned[prefix.end():].strip()
    parts = re.split(r"\s+(?:değil|degil)\s+", cleaned, maxsplit=1)
    if len(parts) != 2:
        return None
    rejected, replacement = (part.strip() for part in parts)
    if not rejected or not replacement:
        return None
    rejected_words = rejected.split()
    replacement_words = replacement.split()
    if had_negative_prefix:
        if 1 <= len(rejected_words) <= 3 and 1 <= len(replacement_words) <= 3:
            return rejected, replacement
        return None
    if len(rejected_words) == 1 and len(replacement_words) == 1:
        return rejected, replacement
    return None


def _is_correction(text: str) -> bool:
    if _is_bosver_control(text):
        return True
    return _replacement_parts(text) is not None


def _looks_like_capability(text: str) -> bool:
    if _is_meta_language(text) or _is_literal_command_usage(text):
        return False
    return _contains_command_token(text)


def _plural_reference_intent(text: str) -> bool:
    padded = f" {text} "
    return _contains_any(padded, _PLURAL_REFERENCE_MARKERS)


def _temporal_need(text: str) -> TemporalNeed:
    if _is_meta_language(text):
        return TemporalNeed.STATIC
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


def _contains_domain_token(text: str, tokens: Iterable[str]) -> bool:
    return any(_bounded_token(text, token) for token in tokens)


def _has_file_domain(text: str) -> bool:
    if _contains_domain_token(text, _FILE_DOMAIN_TOKENS):
        return True
    return re.search(r"\.(?:pdf|doc|docx)(?!\w)", text) is not None


def _is_weather_request(text: str) -> bool:
    if _is_meta_language(text) or _is_literal_command_usage(text):
        return False
    if not _contains_domain_token(text, _WEATHER_DOMAIN_TOKENS):
        return False
    if re.search(r"(?<!\w)hava\s+(?:yolu|kuvvetleri)(?!\w)", text) is not None:
        return False
    return re.search(r"(?<!\w)hava(?!\w).*\b(?:nasıl|nasil|nasıldı|nasildi)\b", text) is not None


def _capability_hint(text: str, temporal_need: TemporalNeed) -> str | None:
    if _is_meta_language(text) or _is_literal_command_usage(text):
        return None
    if _contains_domain_token(text, _NOTE_DOMAIN_TOKENS) and _looks_like_capability(text):
        return "notes.read"
    if _is_weather_request(text):
        return "weather.read.current" if temporal_need is TemporalNeed.CURRENT else "weather.read"
    if _has_file_domain(text) and _looks_like_capability(text):
        return "files.read"
    if any(_bounded_token(text, token) for token in ("hatırlat", "hatirlat", "uyar")):
        return "reminder.propose"
    if _looks_like_capability(text) and _contains_command_token(text, ("ara", "bul")):
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


def _looks_like_location_answer(text: str) -> bool:
    raw = text.strip()
    if not raw or any(mark in raw for mark in "?!,;:"):
        return False
    words = raw.split()
    if not 1 <= len(words) <= 2:
        return False
    for word in words:
        pieces = re.split(r"[-']", word)
        if not pieces:
            return False
        for piece in pieces:
            if not piece or not piece.isalpha() or not piece[0].isupper():
                return False
    return True


def _answer_to_pending(text: str, normalized: str, active_context: ActiveContext) -> bool:
    if not active_context.pending_references:
        return False
    if not normalized or _is_pr6_protocol_answer(normalized):
        return False
    if _is_context_control(normalized) or _is_correction(normalized) or _looks_like_capability(normalized):
        return False
    if _contains_any(normalized, _GENERIC_CHAT):
        return False
    if "?" in normalized:
        return False

    for pending in active_context.pending_references:
        if pending.kind != "pending_state":
            continue
        field = _pending_field(pending)
        if field == "pending_weather_location" and _looks_like_location_answer(text):
            return True
    return False


def _ambiguity_for_references(text: str, references: tuple[ContextReference, ...]) -> tuple[str, ...]:
    if len(references) <= 1 or _plural_reference_intent(text) or _is_correction(text):
        return ()
    return ("multiple target references",)


def _correction_arguments(original_text: str, normalized: str) -> dict[str, object]:
    arguments: dict[str, object] = {"original_text": original_text}
    parts = _replacement_parts(normalized)
    if parts is not None:
        rejected, replacement = parts
        arguments["rejected_text"] = rejected
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
    candidates = _reference_tuple("candidates", candidates, owner)
    references = _reference_tuple("references", references, owner)
    _require_reference_candidates(candidates, references)

    normalized = _norm(text)
    temporal_need = _temporal_need(normalized)
    correction = _is_correction(normalized)
    topic_change = _is_topic_change(normalized)
    context_control = _is_context_control(normalized)
    ambiguities = _ambiguity_for_references(normalized, references)
    weather_request = _is_weather_request(normalized)

    if topic_change:
        relation = ConversationRelation.TOPIC_CHANGE
    elif correction:
        relation = ConversationRelation.CORRECTION
    elif _answer_to_pending(text, normalized, active_context):
        relation = ConversationRelation.ANSWER_TO_PENDING
    elif _continues_active(active_context, references):
        relation = ConversationRelation.CONTINUE_ACTIVE
    else:
        relation = ConversationRelation.NEW_REQUEST

    if context_control:
        request_kind = RequestKind.CONTEXT_CONTROL
    elif ambiguities:
        request_kind = RequestKind.CLARIFY
    elif weather_request or _looks_like_capability(normalized):
        request_kind = RequestKind.CAPABILITY
    else:
        request_kind = RequestKind.CHAT

    if topic_change:
        context_actions = (ContextAction.DROP_TOPIC,)
    elif correction:
        if _is_bosver_control(normalized):
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
