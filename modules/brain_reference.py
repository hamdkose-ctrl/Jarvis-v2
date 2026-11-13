"""Deterministic reference resolution over an already-built candidate set.

This module is observation-only. It returns existing ContextReference objects and
never discovers sources, selects capabilities, authorizes work, or runs effects.
"""
from __future__ import annotations

import ntpath
import re

from modules.brain_contracts import ActiveContext, ContextReference


_TEXT_FIELDS = ("name", "title", "text", "label")
_FILE_DEICTICS = ("bu dosya", "son dosya", "yüklediğim dosya", "yukledigim dosya")
_ANSWER_DEICTICS = ("son cevap", "son cevabı", "son cevabi", "son yanıt", "son yanit")
_GENERIC_DEICTICS = ("onu", "bunu", "az önceki", "az onceki")
_NOTE_MUTATION = re.compile(
    r"^(?P<target>.+?)\s+not\w*\s+(?:sil|kaldır|kaldir|iptal\s+et|düzelt|duzelt|değiştir|degistir|güncelle|guncelle)\w*"
    r"(?:\s*[:,].*)?$"
)
_NOTE_SUMMARY = re.compile(
    r"^(?P<target>.+?)\s+(?:(?:başlıklı|baslikli)\s+)?not\w*\s+(?:özetle|ozetle|özet|ozet)\w*$"
)
_NOTE_ORDINALS = {
    "ilk": 1, "birinci": 1, "ikinci": 2, "üçüncü": 3, "ucuncu": 3, "dördüncü": 4, "dorduncu": 4,
    "beşinci": 5, "besinci": 5, "altıncı": 6, "altinci": 6, "yedinci": 7,
    "sekizinci": 8, "dokuzuncu": 9, "onuncu": 10,
}
_NOTE_NOUN = r"not(?:u|um|umu|unu|un|umun)?(?!\w|\.\w)"
_NOTE_POSITION_RE = re.compile(
    r"(?<![\w#])(?:(?P<number>\d+)(?:\.\s*|\s+numaral[ıi]\s+)|(?P<word>"
    + "|".join(sorted((*_NOTE_ORDINALS, "son"), key=len, reverse=True))
    + r")\s+)" + _NOTE_NOUN
)
_NOTE_ACTIVE_DEICTICS = ("bu notu", "şu notu", "su notu", "o notu", "bu notum", "şu notum", "su notum")
_NOTE_TARGET_STOP = frozenset({
    "bu", "şu", "su", "o", "son", "tüm", "tum", "bütün", "butun", "hepsi", "hepsini",
    "not", "notu", "notunu", "notum", "notumu", "notlar", "notları", "notlari", "notlarım",
    "notlarim", "notlarımı", "notlarimi", "numaralı", "numarali",
}) | frozenset(_NOTE_ORDINALS)


def _required(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} boş olamaz.")
    return value


def _norm(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.casefold().replace("i\u0307", "i").strip().strip("\"'`").split())


def _contains_bounded(text: str, needle: str) -> bool:
    """Return True only when an exact signal is not embedded in a larger token."""
    if not needle:
        return False
    start = 0
    while True:
        idx = text.find(needle, start)
        if idx < 0:
            return False
        left = text[idx - 1] if idx else ""
        end = idx + len(needle)
        right = text[end] if end < len(text) else ""
        left_ok = not left or not (left.isalnum() or left in "_-")
        right_ok = not right or not (right.isalnum() or right in "_-")
        if left_ok and right_ok:
            return True
        start = idx + 1


def _contains_numeric_identity(text: str, ident: str) -> bool:
    escaped = re.escape(ident)
    patterns = (
        rf"(?<!\w)#\s*{escaped}(?!\d)",
        rf"(?<!\w)id\s*:?\s*{escaped}(?!\d)",
        rf"(?<!\d){escaped}\s+numaralı\b",
    )
    return any(re.search(pattern, text) is not None for pattern in patterns)


def _contains_explicit_id(text: str, ident: str) -> bool:
    if not ident:
        return False
    if ident.isdecimal():
        return _contains_numeric_identity(text, ident)
    return _contains_bounded(text, ident)


def _phrase(text: str, phrase: str) -> bool:
    escaped = re.escape(phrase)
    return re.search(rf"(?<!\w){escaped}(?!\w)", text) is not None


def _unique_identity(candidates: tuple[ContextReference, ...]) -> tuple[ContextReference, ...]:
    out: list[ContextReference] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        key = (candidate.kind, candidate.id)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return tuple(out)


def _file_signals(candidate: ContextReference) -> tuple[str, ...]:
    values: list[str] = []
    raw_path = candidate.provenance.get("path")
    path = raw_path if isinstance(raw_path, str) and raw_path.strip() else candidate.id
    normalized_path = _norm(path)
    if normalized_path:
        values.append(normalized_path)
    raw_name = candidate.provenance.get("name")
    name = raw_name if isinstance(raw_name, str) and raw_name.strip() else ntpath.basename(path)
    normalized_name = _norm(name)
    if normalized_name:
        values.append(normalized_name)
        stem = _norm(ntpath.splitext(name)[0])
        if stem:
            values.append(stem)
    return tuple(dict.fromkeys(values))


def _note_target_words(text: str) -> tuple[str, ...]:
    """Named note target; list positions and active deictics resolve separately."""
    stripped = text.strip(" .!?")
    match = _NOTE_MUTATION.fullmatch(stripped) or _NOTE_SUMMARY.fullmatch(stripped)
    if match is None:
        return ()
    words = tuple(re.findall(r"[\wçğıöşü]+", match.group("target")))
    if not 1 <= len(words) <= 4:
        return ()
    if any(word.isdecimal() or word in _NOTE_TARGET_STOP for word in words):
        return ()
    return words


def _note_candidate_matches(candidate: ContextReference, target_words: tuple[str, ...]) -> bool:
    if candidate.kind != "note" or not target_words:
        return False
    haystack = " ".join(
        value for value in (_norm(candidate.provenance.get("title")), _norm(candidate.provenance.get("text"))) if value
    )
    words = re.findall(r"[\wçğıöşü]+", haystack)
    if not words:
        return False

    def hit(target: str) -> bool:
        for word in words:
            size = min(5, len(target), len(word))
            if size >= 3 and target[:size] == word[:size]:
                return True
        return False

    return all(hit(target) for target in target_words)


def _note_ordinal(text: str) -> int | None:
    """Observe a note list position, without choosing an operation/capability.

    None means absent, 0 ambiguous/invalid, -1 the actual last Profile row.
    """
    hits = list(_NOTE_POSITION_RE.finditer(text))
    if not hits:
        return None
    if len(hits) != 1:
        return 0
    hit = hits[0]
    if hit["number"] is not None:
        return int(hit["number"]) if len(hit["number"]) <= 9 else 0
    return -1 if hit["word"] == "son" else _NOTE_ORDINALS[hit["word"]]


def _note_at_position(candidate: ContextReference, ordinal: int) -> bool:
    if candidate.kind != "note" or candidate.source != "profile.items":
        return False
    position = candidate.provenance.get("list_position")
    count = candidate.provenance.get("list_count")
    if type(position) is not int or type(count) is not int or not 1 <= position <= count:
        return False
    return position == (count if ordinal == -1 else ordinal)


def _active_note_keys(context: ActiveContext) -> set[tuple[str, str]]:
    return {
        (ref.kind, ref.id)
        for group in (context.recent_references, context.active_artifacts,
                      context.pending_references, context.memory_references)
        for ref in group if ref.kind == "note"
    }


def _eligible(candidates: tuple[ContextReference, ...]) -> tuple[ContextReference, ...]:
    return tuple(candidate for candidate in candidates if candidate.kind not in {"source_status", "pending_state"})


def resolve_references(
    *,
    owner: str,
    request_id: str,
    text: str,
    active_context: ActiveContext,
    candidates: tuple[ContextReference, ...],
) -> tuple[ContextReference, ...]:
    """Return only existing candidates supported by bounded signals in current text."""
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
    if not isinstance(candidates, tuple):
        raise ValueError("candidates tuple olmalı.")
    for candidate in candidates:
        if not isinstance(candidate, ContextReference):
            raise ValueError("candidates yalnız ContextReference taşımalı.")
        if candidate.owner != owner:
            raise ValueError("Candidate başka owner'a ait.")

    normalized = _norm(text)
    if not normalized:
        return ()

    usable = _unique_identity(tuple(candidate for candidate in candidates if candidate.kind != "source_status"))
    if not usable:
        return ()

    ordinal = _note_ordinal(normalized)
    if ordinal is not None:
        # Displayed note numbers are list positions, not shared Profile IDs.
        # Missing/truncated inventory must not fall through to a coincident ID.
        return tuple(candidate for candidate in usable if _note_at_position(candidate, ordinal))

    explicit = tuple(candidate for candidate in usable if _contains_explicit_id(normalized, _norm(candidate.id)))
    if explicit:
        return explicit

    exact_fields: list[ContextReference] = []
    for candidate in usable:
        for key in _TEXT_FIELDS:
            signal = _norm(candidate.provenance.get(key))
            if signal and normalized == signal:
                exact_fields.append(candidate)
                break
    if exact_fields:
        return tuple(exact_fields)

    note_target = _note_target_words(normalized)
    if note_target:
        note_matches = tuple(candidate for candidate in usable if _note_candidate_matches(candidate, note_target))
        if note_matches:
            return note_matches

    file_matches = tuple(
        candidate
        for candidate in usable
        if candidate.kind == "file"
        and any(_contains_bounded(normalized, signal) for signal in _file_signals(candidate))
    )
    if file_matches:
        return file_matches

    if any(_phrase(normalized, phrase) for phrase in _FILE_DEICTICS):
        return tuple(candidate for candidate in usable if candidate.kind == "file")

    if any(_phrase(normalized, phrase) for phrase in _ANSWER_DEICTICS):
        return tuple(
            candidate
            for candidate in usable
            if candidate.kind == "conversation_turn" and _norm(candidate.provenance.get("role")) == "assistant"
        )

    if any(_phrase(normalized, phrase) for phrase in _NOTE_ACTIVE_DEICTICS):
        # "bu/o notu" only points at a note that is already in ActiveContext; never guess from profile inventory.
        keys = _active_note_keys(active_context)
        return tuple(candidate for candidate in usable if candidate.kind == "note" and (candidate.kind, candidate.id) in keys)

    if any(_phrase(normalized, phrase) for phrase in _GENERIC_DEICTICS):
        return _eligible(usable)

    return ()
