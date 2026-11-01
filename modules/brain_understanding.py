"""Deterministic, non-authoritative Understanding proposal for canonical Brain v1.

This foundation consumes only caller-supplied canonical context, candidates,
resolved references, and the current user text. It does not read sources, mutate
state, run workers, grant authority, or wire itself into production routing.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from modules.brain_actions import ends_with_action
from modules.brain_contracts import (
    ActiveContext,
    Confidence,
    ContextAction,
    ContextReference,
    ConversationRelation,
    EchoPreview,
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
_READ_LIKE_TOKENS = (
    "göster",
    "goster",
    "aç",
    "ac",
    "bul",
    "listele",
    "özetle",
    "ozetle",
    "karşılaştır",
    "karsilastir",
)
_NOTE_DOMAIN_TOKENS = (
    "not",
    "notu",
    "notunu",
    "notum",
    "notumu",
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
    "dosyasını",
    "dosyasini",
    "dosyalar",
    "dosyaları",
    "dosyalari",
    "dosyalarım",
    "dosyalarim",
    "dosyalarımı",
    "dosyalarimi",
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

# Advisory mode is a natural-language choice, so its lexicon belongs to understanding.
# The advisor modules keep only schema validation and rendering.
ADVISORY_DECISION = "decision"
ADVISORY_CRITIQUE = "critique"
ADVISORY_GUIDANCE = "guidance"
ADVISORY_ARGUMENT_KEY = "advisory"
ADVISORY_MODES = frozenset({ADVISORY_DECISION, ADVISORY_CRITIQUE, ADVISORY_GUIDANCE})
_ADVISORY_DECISION = re.compile(
    r"\b(?:hangisi\w*|hangisini|seçenek\w*|secenek\w*|tercih\s+et\w*|tercihim\w*|"
    r"karar\s+ver(?!di|dik|din)\w*|karar\w*\s+veremiyorum|karşılaştır\w*|karsilastir\w*|"
    r"artı\s*(?:ve\s*)?eksi\w*|arti\s*(?:ve\s*)?eksi\w*|avantaj\w*|dezavantaj\w*|pro.?con\w*)",
    re.I,
)
# "A mı B mi", "gideyim mi kalayım mı": two yes/no particles = a choice.
_ADVISORY_CHOICE = re.compile(r"\bm[ıiuü]\b.+\bm[ıiuü]\b", re.I)
_ADVISORY_CRITIQUE = re.compile(
    r"\b(?:eleştir\w*|elestir\w*|zayıf\s+(?:nokta|yan|yön)\w*|zayif\s+(?:nokta|yan|yon)\w*|"
    r"dürüstçe|durustce|dürüst\s+ol\w*|durust\s+ol\w*|açık\s+sözlü|acik\s+sozlu|"
    r"eksikler\w*|eksik\s+(?:yan|yön|yon|nokta)\w*|neresi\s+(?:kötü|kotu|eksik|zayıf|zayif)|"
    r"nerede\s+hata\s+yap\w*)",
    re.I,
)
_ADVISORY_GUIDANCE = re.compile(
    r"\b(?:adım\s+adım|adim\s+adim|rehber\w*|yol\s+göster\w*|yol\s+goster\w*|"
    r"nasıl\s+(?:yap|başla|basla|ilerle|hazırla|hazirla|kur|öğren|ogren)\w*|"
    r"nasil\s+(?:yap|basla|ilerle|hazirla|kur|ogren)\w*|"
    r"ne\s+yapmal[ıi]y[ıi]m|ne\s+yapmam\s+(?:lazım|lazim|gerek)\w*|"
    r"tavsiye\w*|önerin\s+ne|onerin\s+ne|ne\s+önerirsin|ne\s+onerirsin)",
    re.I,
)


def _advisory_request(text: str) -> str | None:
    if _ADVISORY_DECISION.search(text) or _ADVISORY_CHOICE.search(text):
        return ADVISORY_DECISION
    if _ADVISORY_CRITIQUE.search(text):
        return ADVISORY_CRITIQUE
    if _ADVISORY_GUIDANCE.search(text):
        return ADVISORY_GUIDANCE
    return None


def _required(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} boş olamaz.")
    return value


def _norm(value: object) -> str:
    if not isinstance(value, str):
        return ""
    # Turkish dotted/dotless I must be mapped before casefold ("İzmir" -> "izmir", not "i̇zmir").
    return " ".join(value.replace("İ", "i").replace("I", "ı").casefold().strip().split())


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
    if re.fullmatch(r"(?:ara|bul|araştır|arastir)\s+ne demek\??", text) is not None:
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


def _has_read_like_command(text: str) -> bool:
    return _contains_command_token(text, _READ_LIKE_TOKENS)


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
    return re.search(r"\.(?:pdf|doc|docx|txt|md|csv|xls|xlsx|ppt|pptx)(?!\w)", text) is not None


_WEATHER_LOCATION = re.compile(r"([a-zçğıöşü]{3,}?)(?:['’]?(?:da|de|ta|te|daki|deki|nın|nin))?\s+hava")


# Fillers the legacy city parser never saw ("şu anda hava nasıl"); WEATHER_STOP itself is frozen by its own test.
_WEATHER_EXTRA_STOP = frozenset({"anda"})


def _weather_location(text: str) -> str | None:
    """City word before 'hava' ('ankara'da hava nasıl'); None when absent or a filler word."""
    from modules.tr_speech_sets import WEATHER_STOP
    match = _WEATHER_LOCATION.search(text)
    if match is None or match.group(1) in WEATHER_STOP or match.group(1) in _WEATHER_EXTRA_STOP:
        return None
    return match.group(1)


def _is_weather_request(text: str) -> bool:
    if _is_meta_language(text) or _is_literal_command_usage(text):
        return False
    if not _contains_domain_token(text, _WEATHER_DOMAIN_TOKENS):
        return False
    if re.search(r"(?<!\w)hava\s+(?:yolu|kuvvetleri)(?!\w)", text) is not None:
        return False
    return re.search(r"(?<!\w)hava(?!\w).*\b(?:nasıl|nasil|nasıldı|nasildi)\b", text) is not None


RESEARCH_MAX_QUERY = 1000
_RESEARCH_WEB_CUE = re.compile(r"(?<!\w)(?:internet\w*|web\w*|google\w*|haber\w*|araştır\w*|arastir\w*)")
_RESEARCH_PRIVATE_TARGET = re.compile(
    r"(?<!\w)(?:bunu|şunu|sunu|onu|mail\w*|e-?posta\w*|dosya\w*|belge\w*|not\w*|takvim\w*|"
    r"sayfa\w*|site\w*|izleme|listem\w*|hesab\w*|gelen)(?!\w)"
)


def _is_explicit_research_request(text: str) -> bool:
    """True only for an explicit public-web research ask; private/deictic targets stay with their owner."""
    if _is_meta_language(text) or _is_literal_command_usage(text):
        return False
    if _RESEARCH_PRIVATE_TARGET.search(text) is not None:
        return False
    if _RESEARCH_WEB_CUE.search(text) is None:
        return False
    return _contains_command_token(text, ("ara", "bul", "araştır", "arastir"))


def _research_arguments(original: str, normalized: str) -> dict[str, object]:
    """Research proposal uses the user's exact request and never grants PUBLIC provenance."""
    query = original.strip()
    if not query or len(query) > RESEARCH_MAX_QUERY or "\x00" in query:
        return {}
    if not _is_explicit_research_request(normalized):
        return {}
    return {"research": {"query": query, "route": "PRIVATE"}}


_NOTES_PLURAL = ("notlar", "notları", "notlari", "notlarım", "notlarim", "notlarımı", "notlarimi")
_NOTES_SINGULAR = ("not", "notu", "notunu", "notum", "notumu")
_NOTES_READ_VERBS = ("göster", "goster", "oku", "say", "listele")
_NOTES_WRITE_RE = re.compile(
    r"^(?P<target>.+?)\s+not\w*\s+(?P<verb>sil|kaldır|kaldir|iptal\s+et|düzelt|duzelt|değiştir|degistir|güncelle|guncelle)\w*"
    r"(?:\s*[:,]\s*(?P<new>.*))?$"
)
_NOTES_WRITE_STOP = frozenset({
    "bu", "şu", "su", "o", "son", "tüm", "tum", "bütün", "butun", "hepsi", "hepsini",
    "numaralı", "numarali",
})
_NOTES_FILLERS = frozenset({"lütfen", "lutfen", "bana", "bir", "bu", "şu", "su", "o", "tüm", "tum", "bütün", "butun",
                            "hepsini", "son", "şunu", "bunu", "mi", "mı", "mu", "mü", "misin", "mısın", "musun", "müsün", "jarvis"})
NOTES_WRITE_CAPABILITY = "notes.write"
NOTE_TARGET_UNRESOLVED = "note target unresolved"
NOTE_UPDATE_TEXT_MISSING = "note update text missing"


def _note_write_request(text: str) -> tuple[str, str] | None:
    """Return (operation, named target) only for a bounded named note mutation."""
    match = _NOTES_WRITE_RE.fullmatch(text.strip(" .!?"))
    if match is None:
        return None
    target = match.group("target").strip()
    words = re.findall(r"[\wçğıöşü]+", target)
    if not 1 <= len(words) <= 4:
        return None
    if any(word.isdecimal() or word in _NOTES_WRITE_STOP for word in words):
        return None
    verb = match.group("verb")
    operation = "delete" if verb.startswith(("sil", "kaldır", "kaldir", "iptal")) else "update"
    return operation, target


def _note_update_text(original: str) -> str | None:
    if ":" not in original:
        return None
    value = original.split(":", 1)[1].strip()
    if not value or len(value) > 16000 or "\x00" in value:
        return None
    return value


def _is_bare_notes_command(text: str) -> bool:
    """True only when the WHOLE sentence is a note noun + read verb (+ filler words)."""
    words = re.findall(r"[\wçğıöşüÇĞİÖŞÜ]+", text.lower())
    known = set(_NOTES_PLURAL) | set(_NOTES_SINGULAR) | set(_NOTES_READ_VERBS) | _NOTES_FILLERS
    return bool(words) and all(word in known for word in words)


def _notes_arguments(text: str, references: tuple[ContextReference, ...]) -> dict[str, object]:
    """Read-only notes proposal: all notes or ONE resolved note reference by stable id."""
    if not _contains_command_token(text, _NOTES_READ_VERBS) or not _is_bare_notes_command(text):
        return {}
    if _contains_domain_token(text, _NOTES_PLURAL):
        return {"notes": {"which": "all"}}
    notes = [ref for ref in references if ref.kind == "note"]
    if len(notes) == 1 and _contains_domain_token(text, _NOTES_SINGULAR):
        return {"notes": {"which": "one", "id": notes[0].id}}
    return {}


def _notes_write_arguments(original: str, normalized: str,
                           references: tuple[ContextReference, ...]) -> dict[str, object]:
    request = _note_write_request(normalized)
    notes = [ref for ref in references if ref.kind == "note"]
    if request is None or len(notes) != 1:
        return {}
    operation, _target = request
    row: dict[str, object] = {"operation": operation, "id": notes[0].id}
    if operation == "update":
        value = _note_update_text(original)
        if value is None:
            return {}
        row["text"] = value
    return {"notes": row}


def _is_notes_read_request(text: str) -> bool:
    return _contains_domain_token(text, _NOTE_DOMAIN_TOKENS) and _contains_command_token(text, _NOTES_READ_VERBS)


def _capability_hint(text: str, temporal_need: TemporalNeed) -> str | None:
    if _is_meta_language(text) or _is_literal_command_usage(text):
        return None
    if _note_write_request(text) is not None:
        return "notes.write"
    if _is_notes_read_request(text):
        return "notes.read"
    if _is_weather_request(text):
        return "weather.read.current" if temporal_need is TemporalNeed.CURRENT else "weather.read"
    if _file_operation(text) is not None:
        return "files.read"
    if any(_bounded_token(text, token) for token in ("hatırlat", "hatirlat", "uyar")):
        return "reminder.propose"
    # New canonical path: explicit public-web research, including the Turkish verb "araştır".
    if _is_explicit_research_request(text):
        return "research.search"
    # Preserve the pre-B4d advisory hint for generic ara/bul phrases. Without validated
    # research arguments Core will not claim these; their existing legacy owner remains.
    if _looks_like_capability(text) and _contains_command_token(text, ("ara", "bul")):
        return "research.search"
    return None


TRANSLATE_CAPABILITY = "text.translate"
TRANSLATE_SOURCE_MISSING = "translate source missing"


def _translate_proposal(text: str, candidates: tuple[ContextReference, ...]):
    """(Request, arguments) for a text-translation command; the source comes from Candidate Builder turns.

    The single grammar and source rule live in modules.translation_request (shared with the legacy chain)."""
    from modules import translation_request
    request = translation_request.parse(text)
    if request is None or translation_request.non_text_target(text):
        return None, {}
    turns = sorted(
        ({"id": ref.id, "role": ref.provenance.get("role"), "text": ref.provenance.get("text"),
          "ts": ref.provenance.get("ts")} for ref in candidates if ref.kind == "conversation_turn"),
        key=lambda row: str(row["ts"] or ""),
    )
    source, origin, turn_id = translation_request.pick_source(request, text, turns)
    if not source:
        return request, {}
    row = {"target": request.target, "text": source, "origin": origin}
    if turn_id is not None:
        row["turn_id"] = str(turn_id)
    return request, {"translate": row}


def _reminder_arguments(text: str) -> dict[str, object]:
    """title/when/repeat from the single reminder parser (modules.when underneath); creation sentences only."""
    from modules import reminder_parse
    if not reminder_parse.is_creation_request(text):
        return {}
    parsed = reminder_parse.parse(text)
    return {"reminder": {"title": parsed["title"], "when": parsed["when"], "repeat": parsed["repeat"]}}


FILE_SUMMARIZE = "summarize"
FILE_ANALYZE = "analyze"
FILE_OPEN = "open"
FILE_LOCATE = "locate"
FILE_LIST = "list"
FILE_COMPARE = "compare"
FILE_TRANSLATE = "translate"
FILE_CONVERT = "convert"
FILE_TARGET_UNRESOLVED = "file target unresolved"
FILE_TRANSLATION_TARGET_MISSING = "file translation target missing"
FILE_CONVERSION_FORMAT_MISSING = "file conversion format missing"
# Operations Core fully owns with no sensible legacy raw-text fallback: Brain must ask rather than
# let Core guess. FILE_OPEN/FILE_LOCATE stay legacy-resolved by name search when Brain has no single
# resolved reference (pre-existing behavior); Brain only proposes them when a reference did resolve.
_FILE_TARGET_REQUIRED = frozenset({FILE_SUMMARIZE, FILE_ANALYZE, FILE_TRANSLATE, FILE_CONVERT})
_FILE_ASK_EXEMPT = frozenset({FILE_OPEN, FILE_LOCATE})
_FILE_LANGUAGE_PATTERNS = (
    (re.compile(r"(?<!\w)türkçe(?:ye|ya|e|a)?\s+(?:diline\s+)?çevir\w*(?!\w)"), "Türkçe"),
    (re.compile(r"(?<!\w)ingilizce(?:ye|ya|e|a)?\s+(?:diline\s+)?çevir\w*(?!\w)"), "İngilizce"),
    (re.compile(r"(?<!\w)almanca(?:ya|ye|a|e)?\s+(?:diline\s+)?çevir\w*(?!\w)"), "Almanca"),
    (re.compile(r"(?<!\w)fransızca(?:ya|ye|a|e)?\s+(?:diline\s+)?çevir\w*(?!\w)"), "Fransızca"),
    (re.compile(r"(?<!\w)arapça(?:ya|ye|a|e)?\s+(?:diline\s+)?çevir\w*(?!\w)"), "Arapça"),
    (re.compile(r"(?<!\w)rusça(?:ya|ye|a|e)?\s+(?:diline\s+)?çevir\w*(?!\w)"), "Rusça"),
    (re.compile(r"(?<!\w)ispanyolca(?:ya|ye|a|e)?\s+(?:diline\s+)?çevir\w*(?!\w)"), "İspanyolca"),
)
_FILE_FORMAT_RE = re.compile(
    r"(?<!\w)(pdf|excel|xlsx|word|docx)(?:['’]?(?:e|a|ye|ya))?(?:\s+formatına)?\s+dönüştür\w*(?!\w)"
)


def _file_language(text: str) -> str | None:
    for pattern, label in _FILE_LANGUAGE_PATTERNS:
        if pattern.search(text):
            return label
    return None


def _file_format(text: str) -> str | None:
    match = _FILE_FORMAT_RE.search(text)
    if match is None:
        return None
    return {"excel": "xlsx", "word": "docx"}.get(match.group(1), match.group(1))


def _file_operation(text: str) -> str | None:
    """One bounded natural-language file operation; multi-action requests stay with the step/legacy path."""
    if not _has_file_domain(text) or _is_meta_language(text) or _is_literal_command_usage(text):
        return None
    operations: list[str] = []
    if _contains_command_token(text, ("karşılaştır", "karsilastir")):
        operations.append(FILE_COMPARE)
    if re.search(r"(?<!\w)(?:dönüştür|donustur)\w*(?!\w)", text):
        operations.append(FILE_CONVERT)
    if re.search(r"(?<!\w)(?:çevir|cevir)\w*(?!\w)", text):
        operations.append(FILE_TRANSLATE)
    if re.search(r"(?<!\w)(?:analiz\s+et\w*|incele\w*)(?!\w)", text):
        operations.append(FILE_ANALYZE)
    if _contains_command_token(text, ("özetle", "ozetle")):
        operations.append(FILE_SUMMARIZE)
    if _contains_command_token(text, ("aç", "ac")):
        operations.append(FILE_OPEN)
    if _contains_command_token(text, ("bul",)):
        operations.append(FILE_LOCATE)
    if _contains_command_token(text, ("listele",)):
        operations.append(FILE_LIST)
    if _contains_command_token(text, ("göster", "goster")):
        plural = _contains_domain_token(text, ("dosyalar", "dosyaları", "dosyalari", "dosyalarım", "dosyalarim", "dosyalarımı", "dosyalarimi"))
        operations.append(FILE_LIST if plural else FILE_LOCATE)
    # Same operation may be expressed twice; different operations mean a compound request.
    unique = tuple(dict.fromkeys(operations))
    if len(unique) != 1:
        return None
    if unique[0] != FILE_COMPARE and re.search(
        r"(?<!\w)ve\s+(?:kaydet\w*|g\u00f6nder\w*|gonder\w*|payla\u015f\w*|paylas\w*|yazd\u0131r\w*|yazdir\w*|\u00e7\u0131kt\u0131\s+al\w*|cikti\s+al\w*)(?!\w)",
        text,
    ):
        return None
    return unique[0]


def _file_arguments(text: str, references: tuple[ContextReference, ...]) -> dict[str, object]:
    """Operation + target proposal. Paths come ONLY from resolved file references, never raw text."""
    operation = _file_operation(text)
    if operation is None:
        return {}
    if operation == FILE_LIST:
        return {"operation": FILE_LIST}
    files = [ref for ref in references if ref.kind == "file"]
    if operation == FILE_COMPARE:
        paths = []
        for ref in files:
            value = ref.provenance.get("path")
            if isinstance(value, str) and value.strip() and value not in paths:
                paths.append(value)
        return {"operation": FILE_COMPARE, "paths": tuple(paths)} if 2 <= len(paths) <= 10 else {}
    if len(files) != 1:
        return {}
    path = files[0].provenance.get("path")
    if not isinstance(path, str) or not path.strip():
        return {}
    row: dict[str, object] = {"operation": operation, "path": path}
    if operation == FILE_TRANSLATE:
        target = _file_language(text)
        if target is None:
            return {}
        row["target"] = target
    elif operation == FILE_CONVERT:
        fmt = _file_format(text)
        if fmt is None:
            return {}
        row["format"] = fmt
    return row


# Echo / semantic preview labels. Each one is derived from an already resolved
# capability + bounded argument; none of them re-reads the user sentence.
_FILE_PREVIEW_LABELS = {
    FILE_SUMMARIZE: "Dosyayı özetleme",
    FILE_ANALYZE: "Dosyayı inceleme",
    FILE_OPEN: "Dosyayı açma",
    FILE_LOCATE: "Dosyayı bulma",
    FILE_LIST: "Dosyaları listeleme",
    FILE_COMPARE: "Dosyaları karşılaştırma",
    FILE_TRANSLATE: "Dosyayı çevirme",
    FILE_CONVERT: "Dosyayı dönüştürme",
}
_PREVIEW_FORMAT_LABELS = {"xlsx": "Excel", "docx": "Word", "pdf": "PDF", "csv": "CSV"}
_PREVIEW_CAPABILITY_LABELS = {
    "notes.read": "Notları okuma",
    NOTES_WRITE_CAPABILITY: "Notu güncelleme",
    TRANSLATE_CAPABILITY: "Sohbetteki metni çevirme",
    "reminder.propose": "Hatırlatma önerisi",
}


def _base_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    return value.replace("\\", "/").rpartition("/")[2].strip()


def _preview_subject(arguments: Mapping[str, Any], references: tuple[ContextReference, ...]) -> str:
    paths = arguments.get("paths")
    if isinstance(paths, (tuple, list)):
        names = tuple(dict.fromkeys(_base_name(item) for item in paths))
        return ", ".join(name for name in names if name)
    name = _base_name(arguments.get("path"))
    if name:
        return name
    for ref in references:
        if ref.kind in {"file", "note"}:
            return _base_name(ref.provenance.get("path")) or ref.id.rpartition(":")[2]
    return ""


def _preview_text(capability_hint: str | None, arguments: Mapping[str, Any],
                  references: tuple[ContextReference, ...]) -> EchoPreview | None:
    if capability_hint == "files.read":
        operation = arguments.get("operation")
        label = _FILE_PREVIEW_LABELS.get(operation if isinstance(operation, str) else "")
        if label is None:
            return None
        if operation == FILE_TRANSLATE:
            label = f"Dosyayı {arguments.get('target', '')} diline çevirme"
        elif operation == FILE_CONVERT:
            fmt = str(arguments.get("format") or "")
            label = f"Dosyayı {_PREVIEW_FORMAT_LABELS.get(fmt, fmt)} biçimine çevirme"
        subject = _preview_subject(arguments, references)
        return EchoPreview(text=f"{label}: {subject}" if subject else label)
    if capability_hint == "research.search":
        research = arguments.get("research")
        query = research.get("query") if isinstance(research, Mapping) else None
        if not isinstance(query, str) or not query.strip():
            return None
        return EchoPreview(text=f"Web'de arama: {query.strip()[:80]}")
    if capability_hint in {"weather.read", "weather.read.current"}:
        label = "Güncel hava durumu" if capability_hint.endswith("current") else "Hava durumu"
        location = arguments.get("location")
        return EchoPreview(text=f"{label}: {location}" if isinstance(location, str) and location else label)
    if capability_hint == LEVEL_CAPABILITY:
        prop = arguments.get("property")
        name = {"volume": "Ses", "brightness": "Parlaklık"}.get(prop if isinstance(prop, str) else "", "Seviye")
        level = arguments.get("level")
        return EchoPreview(text=f"{name} ayarı: %{level}" if isinstance(level, int) and not isinstance(level, bool)
                           else f"{name} ayarı")
    if capability_hint in _PREVIEW_CAPABILITY_LABELS:
        return EchoPreview(text=_PREVIEW_CAPABILITY_LABELS[capability_hint])
    return None


_LEVEL_WORDS = {
    "ses": "volume", "sesi": "volume", "sesin": "volume", "sesini": "volume",
    "ses seviyesi": "volume", "ses seviyesini": "volume",
    "parlaklık": "brightness", "parlaklığı": "brightness", "parlaklığını": "brightness",
    "parlaklik": "brightness", "parlakligi": "brightness", "parlakligini": "brightness",
    "ekran parlaklığı": "brightness", "ekran parlaklığını": "brightness",
    "ekran parlaklıgı": "brightness", "ekran parlakligi": "brightness",
}
_LEVEL_VERBS = r"(?:yap|olsun|ayarla|yapar mısın|yapsana)"
_LEVEL_EXPLICIT = re.compile(
    r"(" + "|".join(sorted((re.escape(word) for word in _LEVEL_WORDS), key=len, reverse=True)) + r")"
    r"\s+(?:yüzde\s*)?(\d{1,3})(?:\s*yüzde)?(?:\s+" + _LEVEL_VERBS + r")?"
)
_LEVEL_BARE = re.compile(r"(?:yüzde\s*(\d{1,3})(?:\s+" + _LEVEL_VERBS + r")?|(\d{1,3})\s+" + _LEVEL_VERBS + r")")
LEVEL_CAPABILITY = "pc.level.set"
ACTION_REQUEST_CODE = "ENDS_WITH_ACTION"
LEVEL_UNSPECIFIED = "level target unspecified"


def _level_request(normalized: str, active_context: ActiveContext) -> tuple[str | None, int] | None:
    """Return (property|None, level) for a level-setting utterance, else None.

    The property is explicit in the text, or comes from the fresh ``last_property``
    reference the ActiveContext carries (owner-bound, TTL-checked by its provider).
    A bare number without either stays property=None so Core can ask.
    """
    text = normalized.strip(" .!?")
    explicit = _LEVEL_EXPLICIT.fullmatch(text)
    if explicit is not None:
        return _LEVEL_WORDS[explicit.group(1)], min(int(explicit.group(2)), 100)
    bare = _LEVEL_BARE.fullmatch(text)
    if bare is None:
        return None
    level = min(int(bare.group(1) or bare.group(2)), 100)
    for ref in active_context.recent_references:
        if ref.source == "session_state" and ref.id == "last_property":
            value = ref.provenance.get("value")
            if value in {"volume", "brightness"}:
                return value, level
    return None, level


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
    note_write = None if (context_control or topic_change or correction) else _note_write_request(normalized)
    notes_read_request = False if (context_control or topic_change or correction) else _is_notes_read_request(normalized)
    file_operation = None if (context_control or topic_change or correction) else _file_operation(normalized)
    ambiguities = _ambiguity_for_references(normalized, references)
    if note_write is not None:
        note_refs = [ref for ref in references if ref.kind == "note"]
        if not note_refs:
            ambiguities = (NOTE_TARGET_UNRESOLVED,)
        elif len(note_refs) > 1:
            ambiguities = ("multiple target references",)
        elif note_write[0] == "update" and _note_update_text(text) is None:
            ambiguities = (NOTE_UPDATE_TEXT_MISSING,)
    weather_request = _is_weather_request(normalized)
    research_request = _is_explicit_research_request(normalized)
    level = None if (context_control or topic_change or correction) else _level_request(normalized, active_context)
    translation, translate_args = (None, {})
    if level is None and not (context_control or topic_change or correction):
        translation, translate_args = _translate_proposal(text, candidates)
        if translation is not None:
            # The translation source rule owns "which text"; reference ambiguity does not apply to it.
            ambiguities = () if translate_args else (TRANSLATE_SOURCE_MISSING,)
    if level is not None and level[0] is None:
        ambiguities = (LEVEL_UNSPECIFIED,)
    elif not ambiguities and not context_control and file_operation is not None:
        file_refs = [ref for ref in references if ref.kind == "file"]
        if file_operation in _FILE_TARGET_REQUIRED and len(file_refs) != 1:
            ambiguities = (FILE_TARGET_UNRESOLVED,)
        elif file_operation in _FILE_ASK_EXEMPT and len(file_refs) > 1:
            ambiguities = (FILE_TARGET_UNRESOLVED,)
        elif file_operation == FILE_COMPARE and not 2 <= len(file_refs) <= 10:
            ambiguities = (FILE_TARGET_UNRESOLVED,)
        elif file_operation == FILE_TRANSLATE and _file_language(normalized) is None:
            ambiguities = (FILE_TRANSLATION_TARGET_MISSING,)
        elif file_operation == FILE_CONVERT and _file_format(normalized) is None:
            ambiguities = (FILE_CONVERSION_FORMAT_MISSING,)

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
    elif (level is not None or notes_read_request or note_write is not None or weather_request or research_request
          or translation is not None or file_operation is not None or _looks_like_capability(normalized)):
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
    if LEVEL_UNSPECIFIED in ambiguities:
        reason_codes.append("LEVEL_TARGET_UNSPECIFIED")
    elif FILE_TARGET_UNRESOLVED in ambiguities:
        reason_codes.append("FILE_TARGET_UNRESOLVED")
    elif FILE_TRANSLATION_TARGET_MISSING in ambiguities:
        reason_codes.append("FILE_TRANSLATION_TARGET_MISSING")
    elif FILE_CONVERSION_FORMAT_MISSING in ambiguities:
        reason_codes.append("FILE_CONVERSION_FORMAT_MISSING")
    elif NOTE_TARGET_UNRESOLVED in ambiguities:
        reason_codes.append("NOTE_TARGET_UNRESOLVED")
    elif NOTE_UPDATE_TEXT_MISSING in ambiguities:
        reason_codes.append("NOTE_UPDATE_TEXT_MISSING")
    elif ambiguities:
        reason_codes.append("MULTIPLE_TARGET_REFERENCES")
    if level is not None and level[0] is not None:
        reason_codes.append("LEVEL_REQUEST")
    if ends_with_action(text):
        reason_codes.append(ACTION_REQUEST_CODE)

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
    capability_hint = _capability_hint(normalized, temporal_need)
    if translation is not None:
        capability_hint = TRANSLATE_CAPABILITY
        arguments = {**arguments, **translate_args}
    if capability_hint in {"weather.read", "weather.read.current"}:
        location = _weather_location(normalized)
        if location is not None:
            arguments = {**arguments, "location": location}
    if capability_hint == "reminder.propose":
        arguments = {**arguments, **_reminder_arguments(text)}
    if capability_hint == "files.read":
        arguments = {**arguments, **_file_arguments(normalized, references)}
    if capability_hint == "research.search":
        arguments = {**arguments, **_research_arguments(text, normalized)}
    if capability_hint == "notes.read":
        arguments = {**arguments, **_notes_arguments(normalized, references)}
    if capability_hint == NOTES_WRITE_CAPABILITY:
        arguments = {**arguments, **_notes_write_arguments(text, normalized, references)}
    if level is not None:
        arguments = {**arguments, "level": level[1]}
        if level[0] is not None:
            arguments["property"] = level[0]
            capability_hint = LEVEL_CAPABILITY
        else:
            capability_hint = None

    # Advisory chat shaping is a semantic choice, so it is resolved once here and the
    # advisor layer only formats. A Core-mapped request keeps its own owner.
    advisory = None if (context_control or topic_change or correction or capability_hint) else _advisory_request(normalized)
    if advisory is not None:
        arguments = {**arguments, ADVISORY_ARGUMENT_KEY: advisory}
    preview = None
    if request_kind is RequestKind.CAPABILITY and not ambiguities:
        preview = _preview_text(capability_hint, arguments, references)

    return UnderstandingResult(
        owner=owner,
        request_id=request_id,
        request_kind=request_kind,
        capability_hint=capability_hint,
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
        preview=preview,
    )