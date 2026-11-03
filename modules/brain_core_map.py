"""Core side of the Brain contract: validated capability hint -> existing Core intent.

Brain only proposes (``capability_hint`` + semantic ``arguments``). This table is
Core's own allowlist: a hint that is not listed here is never executed from the
proposal, and every argument is re-validated here before it reaches
``engine_intents.dispatch``. Nothing in this module decides permission or effect
policy; the dispatched Core intents keep their existing guards.
"""
from __future__ import annotations

import os
import re
from typing import Any, Callable, Mapping

from modules.diagnostics import record_failure as _record_failure
from modules import translation_targets
from modules.brain_understanding import (
    APP_CLOSE_CAPABILITY,
    APP_OPEN_CAPABILITY,
    FILE_ANALYZE,
    FILE_COMPARE,
    FILE_CONVERSION_FORMAT_MISSING,
    FILE_CONVERT,
    FILE_LIST,
    FILE_LOCATE,
    FILE_OPEN,
    FILE_SUMMARIZE,
    FILE_TARGET_UNRESOLVED,
    FILE_TRANSLATE,
    FILE_TRANSLATION_TARGET_MISSING,
    LEVEL_CAPABILITY,
    LEVEL_UNSPECIFIED,
    NOTE_SEARCH_QUERY_MISSING,
    NOTE_TARGET_AMBIGUOUS,
    NOTE_TARGET_UNRESOLVED,
    NOTE_UPDATE_TEXT_MISSING,
    NOTES_WRITE_CAPABILITY,
    PHOTO_CAPABILITY,
    PHOTO_TARGET_AMBIGUOUS,
    PHOTO_TARGET_UNRESOLVED,
    RESEARCH_MAX_QUERY,
    SCREEN_CAPABILITY,
    TRANSLATE_SOURCE_MISSING,
    WINDOW_LIST_CAPABILITY,
    WINDOW_OP_CAPABILITY,
)

_LEVEL_PROPERTIES = frozenset({"volume", "brightness"})

_PHOTO_OPERATIONS = frozenset({"analyze", "translate", "note"})
_PHOTO_ARGUMENTS = frozenset({"operation", "photo", "question", "target", "note_text", "original_text"})
_PHOTO_QUESTION_MAX = 1000
_PHOTO_NOTE_MAX = 16000
_PHOTO_PATH_MAX = 4096


def _photo_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Core allowlist for a photo operation. Surface/user text supplies no executable field here."""
    if set(arguments) - _PHOTO_ARGUMENTS:
        return None
    operation = arguments.get("operation")
    photo = arguments.get("photo")
    if operation not in _PHOTO_OPERATIONS:
        return None
    if not isinstance(photo, str) or not photo or "\x00" in photo or len(photo) > _PHOTO_PATH_MAX:
        return None
    if not (os.path.isabs(photo) or re.match(r"^[A-Za-z]:[\\/]", photo)):
        return None
    if operation == "analyze":
        question = arguments.get("question", "")
        if not isinstance(question, str) or len(question) > _PHOTO_QUESTION_MAX:
            return None
        if arguments.get("target") or arguments.get("note_text"):
            return None
        return {"operation": operation, "photo": photo, "question": question}
    if operation == "translate":
        target = arguments.get("target")
        if not translation_targets.is_supported_target(target):
            return None
        if arguments.get("question") or arguments.get("note_text"):
            return None
        return {"operation": operation, "photo": photo, "target": target}
    note_text = arguments.get("note_text")
    if not isinstance(note_text, str) or not note_text.strip() or len(note_text) > _PHOTO_NOTE_MAX:
        return None
    if arguments.get("question") or arguments.get("target"):
        return None
    return {"operation": operation, "photo": photo, "note_text": note_text}


def _level_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    prop = arguments.get("property")
    level = arguments.get("level")
    if prop not in _LEVEL_PROPERTIES or isinstance(level, bool) or not isinstance(level, int):
        return None
    return {"property": prop, "level": max(0, min(100, level))}


_CITY = re.compile(r"[a-zçğıöşü]{3,30}")


def _weather_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    location = arguments.get("location")
    if location is None:
        return {}
    if not isinstance(location, str) or _CITY.fullmatch(location) is None:
        return None
    # Same Turkish-aware capitalization the legacy city parser used.
    return {"location": location[:1].replace("i", "İ").replace("ı", "I").upper() + location[1:]}


def _validated_file_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip() or "\x00" in value or not os.path.isabs(value):
        return None
    try:
        from pathlib import Path
        from modules import nxapi
        target = Path(value)
        if not target.is_file() or nxapi.allowed(target) is None:
            return None
    except Exception:
        _record_failure("modules/brain_core_map.py:file_args")
        return None
    return value


_FILE_OPS = frozenset({FILE_SUMMARIZE, FILE_ANALYZE, FILE_OPEN, FILE_LOCATE, FILE_LIST, FILE_COMPARE, FILE_TRANSLATE, FILE_CONVERT})
_FILE_FORMATS = frozenset({"xlsx", "docx", "pdf"})


def _file_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Core validates exact operation + resolved path(s); no raw-text target selection is allowed here."""
    operation = arguments.get("operation")
    if operation not in _FILE_OPS:
        return None
    if operation == FILE_LIST:
        return {"operation": FILE_LIST}
    if operation == FILE_COMPARE:
        paths = arguments.get("paths")
        if not isinstance(paths, (list, tuple)) or not 2 <= len(paths) <= 10:
            return None
        validated = tuple(_validated_file_path(value) for value in paths)
        if any(value is None for value in validated) or len(set(validated)) != len(validated):
            return None
        return {"operation": FILE_COMPARE, "paths": validated}
    path = _validated_file_path(arguments.get("path"))
    if path is None:
        return None
    result: dict[str, Any] = {"operation": operation, "path": path}
    if operation == FILE_TRANSLATE:
        target = arguments.get("target")
        if not translation_targets.is_supported_target(target):
            return None
        result["target"] = target
    elif operation == FILE_CONVERT:
        fmt = arguments.get("format")
        if fmt not in _FILE_FORMATS:
            return None
        result["format"] = fmt
    elif operation in {FILE_SUMMARIZE, FILE_ANALYZE} and "format" in arguments:
        # Tek cümlelik açık dosya çıktısı: Brain biçimi önerir, Core izinli biçimi doğrular.
        fmt = arguments.get("format")
        if fmt not in _FILE_FORMATS:
            return None
        result["format"] = fmt
    return result


def _reminder_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Core re-validates the Brain-proposed reminder fields; no fields -> not planned (planner keeps it)."""
    from modules import reminder_parse
    row = arguments.get("reminder")
    if not isinstance(row, Mapping) or set(row) - {"title", "when", "repeat"}:
        return None
    title, when, repeat = row.get("title"), row.get("when"), row.get("repeat")
    if not reminder_parse.valid_args(title, when, repeat):
        return None
    return {"title": title, "when": when, "repeat": repeat}


_NOTE_WINDOWS = frozenset({"today", "yesterday", "this_week", "last_week", "this_month", "last_month"})
_NOTE_QUERY_MAX = 120
_NOTE_QUERY_TERMS_MAX = 3


def _note_query(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    query = value.strip()
    if not 0 < len(query) <= _NOTE_QUERY_MAX or "\x00" in query:
        return None
    if any(ord(char) < 32 for char in query) or len(query.split()) > _NOTE_QUERY_TERMS_MAX:
        return None
    return query


def _notes_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Core re-validates the read-only notes proposal; the id is checked against the profile at execution."""
    row = arguments.get("notes")
    if not isinstance(row, Mapping):
        return None
    which, ident = row.get("which"), row.get("id")
    if which == "all":
        return {"which": "all"} if set(row) == {"which"} else None
    if which == "one":
        if set(row) != {"which", "id"}:
            return None
        if isinstance(ident, str) and 0 < len(ident.strip()) <= 64:
            return {"which": "one", "id": ident.strip()}
        return None
    if which == "search":
        if set(row) - {"which", "query", "window"}:
            return None
        window = row.get("window")
        if window is not None and window not in _NOTE_WINDOWS:
            return None
        query = row.get("query")
        if query is None:
            return {"which": "search", "window": window} if window is not None else None
        query = _note_query(query)
        if query is None:
            return None
        result: dict[str, Any] = {"which": "search", "query": query}
        if window is not None:
            result["window"] = window
        return result
    if which == "summary":
        if set(row) - {"which", "id"}:
            return None
        if ident is None:
            return {"which": "summary"}
        if isinstance(ident, str) and 0 < len(ident.strip()) <= 64:
            return {"which": "summary", "id": ident.strip()}
    return None


def _notes_write_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Core validates a named note effect; target identity still needs the Brain-reference fence at handoff."""
    row = arguments.get("notes")
    if not isinstance(row, Mapping) or set(row) - {"operation", "id", "text"}:
        return None
    operation, ident = row.get("operation"), row.get("id")
    if operation not in {"delete", "update"} or not isinstance(ident, str) or not 0 < len(ident.strip()) <= 64:
        return None
    result: dict[str, Any] = {"operation": operation, "id": ident.strip()}
    text = row.get("text")
    if operation == "delete":
        return result if text is None else None
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not 0 < len(text) <= 16000 or "\x00" in text:
        return None
    result["text"] = text
    return result


def _research_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Core validates the proposal; execution still consumes the original user command."""
    row = arguments.get("research")
    if not isinstance(row, Mapping) or set(row) - {"query", "route"}:
        return None
    query = row.get("query")
    if row.get("route") != "PRIVATE" or not isinstance(query, str):
        return None
    query = query.strip()
    if not 0 < len(query) <= RESEARCH_MAX_QUERY or "\x00" in query:
        return None
    return {"query": query, "route": "PRIVATE"}


_SCREEN_QUESTION_MAX = 1000
_WINDOW_ACTIONS = frozenset({"focus", "minimize", "maximize", "restore"})
_APP_NAME_MAX = 40


def _app_open_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Core re-validates the answer to the bare-verb clarification; the launcher keeps its guards."""
    if set(arguments) - {"original_text", "app"}:
        return None
    name = arguments.get("app")
    if not isinstance(name, str):
        return None
    name = name.strip()
    if not 0 < len(name) <= _APP_NAME_MAX or "\x00" in name:
        return None
    return {"name": name}


def _app_close_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Same bounded name re-validation; close still goes through the existing confirmation gate."""
    return _app_open_args(arguments)


def _screen_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Ekran okuma önerisi: soru boş olabilir (genel analiz) ama en fazla tek satır uzunluğunda."""
    if set(arguments) - {"original_text", "question"}:
        return None
    question = arguments.get("question")
    if not isinstance(question, str) or "\x00" in question or len(question) > _SCREEN_QUESTION_MAX:
        return None
    return {"question": question.strip()}


def _window_list_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    row = arguments.get("window")
    if not isinstance(row, Mapping) or set(row) != {"action"} or row.get("action") != "list":
        return None
    return {"action": "pc_windows", "params": {}}


def _window_op_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    row = arguments.get("window")
    if not isinstance(row, Mapping) or set(row) != {"action", "target"}:
        return None
    action, target = row.get("action"), row.get("target")
    if action not in _WINDOW_ACTIONS or not isinstance(target, str):
        return None
    target = target.strip()
    if not 0 < len(target) <= 120 or "\x00" in target:
        return None
    return {"action": "pc_window", "params": {"target": target, "action": action}}


_TRANSLATE_ORIGINS = frozenset({"inline", "assistant", "user"})
MAX_TRANSLATE_CHARS = 20000


def _translate_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Core re-validates the proposed translation; provenance of the text is checked at handoff."""
    row = arguments.get("translate")
    if not isinstance(row, Mapping) or set(row) - {"target", "text", "origin", "turn_id"}:
        return None
    target, text, origin = row.get("target"), row.get("text"), row.get("origin")
    if not isinstance(target, str) or not 0 < len(target.strip()) <= 120:
        return None
    if not isinstance(text, str) or not 0 < len(text.strip()) <= MAX_TRANSLATE_CHARS or "\x00" in text:
        return None
    if origin not in _TRANSLATE_ORIGINS:
        return None
    turn_id = row.get("turn_id")
    if (origin == "inline") != (turn_id is None) or (turn_id is not None and not isinstance(turn_id, str)):
        return None
    result = {"target": target.strip(), "text": text.strip(), "origin": origin}
    if turn_id is not None:
        result["turn_id"] = turn_id
    return result


# hint -> (existing Core intent, argument validator). Hints absent here stay on the
# existing handler path until their own migration.
CORE_INTENTS: dict[str, tuple[str, Callable[[Mapping[str, Any]], dict[str, Any] | None]]] = {
    LEVEL_CAPABILITY: ("level_set", _level_args),
    "weather.read": ("weather", _weather_args),
    "weather.read.current": ("weather", _weather_args),
    # Natural-language file target/operation is Brain-proposed and Core-validated; exact UI file buttons remain a front gate.
    "files.read": ("file_action", _file_args),
    # Reminder creation; edit/snooze/calendar stay in the planner (see brain_precedence).
    "reminder.propose": ("reminder", _reminder_args),
    "notes.read": ("notes_read", _notes_args),
    NOTES_WRITE_CAPABILITY: ("notes_write", _notes_write_args),
    # Explicit public-web research request. Existing Core task/GoalExecutor remains the execution owner;
    # it consumes the raw command, so a Brain-proposed rewritten query can never become executable text.
    "research.search": ("task", _research_args),
    # Text translation; the source text is a Brain-selected turn / inline text (see brain_entry.core_plan).
    "text.translate": ("translate", _translate_args),
    # Ekranı okuma ve pencere kontrolü: eski router'ın deterministik kuralları artık Brain önerisi,
    # Core burada niyeti ve argümanı doğrular; yürütücü (screen/app_action) değişmedi.
    SCREEN_CAPABILITY: ("screen_analyze", _screen_args),
    WINDOW_LIST_CAPABILITY: ("app_action", _window_list_args),
    WINDOW_OP_CAPABILITY: ("app_action", _window_op_args),
    # "Neyi açmamı istiyorsun?" yanıtı: typed clarify proposal'ının hedefi, mevcut app-open sahibine
    # doğrulanmış bir ad olarak gider; serbest metin yeniden yorumlanmaz.
    APP_OPEN_CAPABILITY: ("app_open", _app_open_args),
    # "Neyi kapatmamı istiyorsun?" yanıtı yalnız hedefi çözer; onay/izin/etki mevcut close hattında kalır.
    APP_CLOSE_CAPABILITY: ("app_close", _app_close_args),
    # Fotoğraf işlemi yalnız Understanding'in typed önerisinden gelir; domain executor seçim yapmaz.
    PHOTO_CAPABILITY: ("photo_action", _photo_args),
}


# Capability hints Understanding may emit that are NOT dispatched from the proposal. Each one has a
# named legacy owner that parses the raw text itself; the hint stays advisory until that owner gets a
# validated Core intent. A hint with neither a Core intent nor an owner here is a drift error (tested).
LEGACY_OWNED_HINTS: dict[str, str] = {}


# Hints that are Core-mapped for some operations; the rest of the hint is still owned by this legacy path.
PARTIAL_CORE_HINTS: dict[str, str] = {
    "research.search": "ara/bul cümleleri açık web araştırma ipucu taşımıyorsa (mail/dosya/sayfa/not/deiktik): eski handler + goal_executor",
}


def hint_owner(hint: str) -> str | None:
    if hint in CORE_INTENTS:
        return "core:" + CORE_INTENTS[hint][0]
    return LEGACY_OWNED_HINTS.get(hint)


def core_plan(hint: str | None, arguments: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Return (core_intent, validated_args) or None when the hint is not Core-mapped/invalid."""
    entry = CORE_INTENTS.get(hint or "")
    if entry is None:
        return None
    intent, validate = entry
    args = validate(arguments)
    return None if args is None else (intent, args)


def clarification_question(ambiguities: tuple[str, ...], arguments: Mapping[str, Any]) -> str | None:
    if "MULTIPLE_PENDING_ANSWER_OWNERS" in ambiguities:
        return "Birden fazla açık soru bu cevaba uyuyor; hangisini kastettiğini netleştir."
    if PHOTO_TARGET_AMBIGUOUS in ambiguities:
        return "Birden fazla fotoğraf var; hangisiyle işlem yapmamı istediğini netleştir."
    if PHOTO_TARGET_UNRESOLVED in ambiguities:
        return ("Fotoğrafı hangi dile çevireyim? Desteklenen diller: "
                + ", ".join(translation_targets.display_names()) + ".")
    if FILE_TARGET_UNRESOLVED in ambiguities:
        return "Hangi dosyayı veya dosyaları kastettiğini netleştir; dosya adını yaz ya da dosyayı sohbete ekle."
    if FILE_TRANSLATION_TARGET_MISSING in ambiguities:
        return "Dosyayı hangi dile çevireyim? Örneğin İngilizce veya Türkçe de."
    if FILE_CONVERSION_FORMAT_MISSING in ambiguities:
        return "Dosyayı hangi formata dönüştüreyim? Excel, Word veya PDF de."
    if NOTE_TARGET_UNRESOLVED in ambiguities:
        return "Hangi notu kastettiğini netleştir; notun adından bir kelime söyle."
    if NOTE_TARGET_AMBIGUOUS in ambiguities:
        return "Hangisini kastettiğini netleştir: birden fazla not eşleşti; notun adından bir kelime ya da numara söyle."
    if NOTE_UPDATE_TEXT_MISSING in ambiguities:
        return "Notun yeni metnini de söyle; örneğin 'market notunu düzelt: yeni metin'."
    if NOTE_SEARCH_QUERY_MISSING in ambiguities:
        return "Hangi kelimeyi notlarında aramamı istersin?"
    if TRANSLATE_SOURCE_MISSING in ambiguities:
        return "Bu sohbette çevrilecek metni bulamadım. Metni buraya yapıştırabilirsin."
    if LEVEL_UNSPECIFIED in ambiguities:
        level = arguments.get("level")
        if isinstance(level, int) and not isinstance(level, bool):
            return f"Yüzde {max(0, min(100, level))}, ses mi parlaklık mı?"
    return None


def clarification_effect(runtime: Any, ambiguities: tuple[str, ...], arguments: Mapping[str, Any]) -> None:
    """Core-owned state change that makes the asked question answerable next turn."""
    if LEVEL_UNSPECIFIED in ambiguities:
        level = arguments.get("level")
        if isinstance(level, int) and not isinstance(level, bool):
            runtime._session().pending_level = max(0, min(100, level))