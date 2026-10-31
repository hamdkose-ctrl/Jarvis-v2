"""Deterministic, non-authoritative Understanding proposal for canonical Brain v1.

This foundation consumes only caller-supplied canonical context, candidates,
resolved references, and the current user text. It does not read sources, mutate
state, run workers, grant authority, or wire itself into production routing.
"""
from __future__ import annotations

import re
from typing import Iterable

from modules.brain_actions import ends_with_action
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
    "dosyasını",
    "dosyasini",
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


# Sentences another existing handler answers (finance, weather, sports, prayer times) or that only mention a
# product/app/setting ("internet hızı", "Excel'de ... ara", "Google Drive'da ... bul"): not public research.
_RESEARCH_OTHER_OWNER = re.compile(
    r"(?<!\w)(?:altın\w*|altin\w*|dolar\w*|euro\w*|sterlin\w*|kur|kuru\w*|döviz\w*|doviz\w*|bitcoin\w*|btc|kripto\w*|"
    r"borsa\w*|hisse\w*|faiz\w*|fiyat\w*|enflasyon\w*|parite\w*|"
    r"hava(?:nın|nin|da|de|yı|yi)?|yağış\w*|yagis\w*|sıcaklık\w*|sicaklik\w*|"
    r"maç\w*|skor\w*|puan\s+durum\w*|namaz\w*|ezan\w*|imsak|iftar|sahur|"
    r"excel\w*|word\w*|powerpoint\w*|chrome\w*|edge\w*|firefox\w*|outlook\w*|drive\w*|onedrive\w*|"
    r"sütun\w*|sutun\w*|hücre\w*|hucre\w*|tablo\w*|geçmiş\w*|gecmis\w*|hız\w*|hiz\w*|kafe\w*|"
    r"bağlantı\w*|baglanti\w*|wifi|wi-fi|modem\w*)(?!\w)")


def _is_explicit_research_request(text: str) -> bool:
    """True only for an explicit public-web research ask; private/deictic targets stay with their owner."""
    if _is_meta_language(text) or _is_literal_command_usage(text):
        return False
    if _RESEARCH_PRIVATE_TARGET.search(text) is not None or _RESEARCH_OTHER_OWNER.search(text) is not None:
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


def _capability_hint(text: str, temporal_need: TemporalNeed) -> str | None:
    if _is_meta_language(text) or _is_literal_command_usage(text):
        return None
    if _contains_domain_token(text, _NOTE_DOMAIN_TOKENS) and _has_read_like_command(text):
        return "notes.read"
    if _is_weather_request(text):
        return "weather.read.current" if temporal_need is TemporalNeed.CURRENT else "weather.read"
    if _has_file_domain(text) and _has_read_like_command(text):
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


_NOTES_PLURAL = ("notlar", "notları", "notlari", "notlarım", "notlarim", "notlarımı", "notlarimi")
_NOTES_SINGULAR = ("not", "notu", "notum", "notumu")
_NOTES_SHOW_VERBS = ("göster", "goster")


_NOTES_FILLERS = frozenset({"lütfen", "lutfen", "bana", "bir", "bu", "şu", "su", "o", "tüm", "tum", "bütün", "butun",
                            "hepsini", "son", "şunu", "bunu", "mi", "mı", "mu", "mü", "misin", "mısın", "musun", "müsün", "jarvis"})


def _is_bare_notes_command(text: str) -> bool:
    """True only when the WHOLE sentence is a note noun + show verb (+ filler words).

    Anything else ('... ve hava nasıl', 'göster, not al: süt', 'sonra ...') is multi-intent or another
    request, and a notes proposal would swallow the remaining part: no proposal then."""
    words = re.findall(r"[\wçğıöşüÇĞİÖŞÜ]+", text.lower())
    known = set(_NOTES_PLURAL) | set(_NOTES_SINGULAR) | set(_NOTES_SHOW_VERBS) | _NOTES_FILLERS
    return bool(words) and all(word in known for word in words)


def _notes_arguments(text: str, references: tuple[ContextReference, ...]) -> dict[str, object]:
    """Read-only notes proposal: all notes (plural noun) or ONE resolved note reference by stable id.

    Only a bare single 'notes + göster' command is proposed (see _is_bare_notes_command)."""
    if not _contains_command_token(text, _NOTES_SHOW_VERBS) or not _is_bare_notes_command(text):
        return {}
    if _contains_domain_token(text, _NOTES_PLURAL):
        return {"notes": {"which": "all"}}
    notes = [ref for ref in references if ref.kind == "note"]
    if len(notes) == 1 and _contains_domain_token(text, _NOTES_SINGULAR):
        return {"notes": {"which": "one", "id": notes[0].id}}
    return {}


def _reminder_arguments(text: str) -> dict[str, object]:
    """title/when/repeat from the single reminder parser (modules.when underneath); creation sentences only."""
    from modules import reminder_parse
    if not reminder_parse.is_creation_request(text):
        return {}
    parsed = reminder_parse.parse(text)
    return {"reminder": {"title": parsed["title"], "when": parsed["when"], "repeat": parsed["repeat"]}}


FILE_SUMMARIZE = "summarize"
FILE_TARGET_UNRESOLVED = "file target unresolved"


def _asks_file_summary(text: str) -> bool:
    return (_has_file_domain(text) and _contains_command_token(text, ("özetle", "ozetle"))
            and not _is_meta_language(text) and not _is_literal_command_usage(text))


def _other_actions(text: str) -> bool:
    """A second action verb ('özetle ve çevir') makes the request multi-step: no single-operation proposal."""
    from modules.brain_actions import _ACTION, _fold
    return _ACTION.search(_fold(text)) is not None


def _file_arguments(text: str, references: tuple[ContextReference, ...]) -> dict[str, object]:
    """Semantic target + operation for files.read: only a single RESOLVED file reference is a target.

    The path comes from the Candidate Builder inventory via the Reference Resolver, never from the
    raw text. Only the summarize operation is proposed; other read-like verbs stay unmapped."""
    if not _contains_command_token(text, ("özetle", "ozetle")) or _other_actions(text):
        return {}
    files = [ref for ref in references if ref.kind == "file"]
    if len(files) != 1:
        return {}
    path = files[0].provenance.get("path")
    if not isinstance(path, str) or not path.strip():
        return {}
    return {"operation": FILE_SUMMARIZE, "path": path}


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
    ambiguities = _ambiguity_for_references(normalized, references)
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
    elif (not ambiguities and not context_control and _asks_file_summary(normalized)
          and not any(ref.kind == "file" for ref in references)):
        # A file summary with no resolved file must ask; Core never guesses a target from raw text.
        ambiguities = (FILE_TARGET_UNRESOLVED,)

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
    elif level is not None or weather_request or research_request or translation is not None or _looks_like_capability(normalized):
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
    if level is not None:
        arguments = {**arguments, "level": level[1]}
        if level[0] is not None:
            arguments["property"] = level[0]
            capability_hint = LEVEL_CAPABILITY
        else:
            capability_hint = None

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
    )