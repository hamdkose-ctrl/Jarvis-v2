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
    APP_TARGET_MISSING,
    AUDIO_CAPABILITY,
    CONTACTS_MANAGE_CAPABILITY,
    MESSAGE_BODY_MAX,
    MESSAGE_SEND_CAPABILITY,
    FILE_ANALYZE,
    FILE_COMPARE,
    FILE_CONVERSION_FORMAT_MISSING,
    FILE_CONVERT,
    FILE_LIST,
    FILE_MUTATE_CAPABILITY,
    FILE_LOCATE,
    FILE_OPEN,
    FILE_SUMMARIZE,
    FILE_TARGET_UNRESOLVED,
    FILE_TRANSLATE,
    FILE_TRANSLATION_TARGET_MISSING,
    FOLDER_ANALYSIS_CAPABILITY,
    FOLDER_ANALYSIS_OPERATION,
    LEVEL_CAPABILITY,
    LEVEL_UNSPECIFIED,
    MEDIA_CAPABILITY,
    NOTE_SEARCH_QUERY_MISSING,
    NOTE_TARGET_AMBIGUOUS,
    NOTE_TARGET_UNRESOLVED,
    NOTE_UPDATE_TEXT_MISSING,
    NOTES_WRITE_CAPABILITY,
    ORGANIZE_CAPABILITY,
    ORGANIZE_OPERATION,
    ORGANIZE_TARGET_AMBIGUOUS,
    PHOTO_CAPABILITY,
    PHOTO_TARGET_AMBIGUOUS,
    PHOTO_TARGET_UNRESOLVED,
    RESEARCH_MAX_QUERY,
    SCREEN_CAPABILITY,
    SCREEN_CAPTURE_CAPABILITY,
    SHUTDOWN_CANCEL_CAPABILITY,
    SHUTDOWN_REQUEST_CAPABILITY,
    TRANSLATE_SOURCE_MISSING,
    WAKE_ENABLE_CAPABILITY,
    WEATHER_CITY_RESET_CAPABILITY,
    WEATHER_CITY_SET_CAPABILITY,
    WINDOW_LIST_CAPABILITY,
    WINDOW_OP_CAPABILITY,
    WATCHER_CAPABILITY,
    WATCHER_ACTION_UNSUPPORTED,
    VISUAL_CAPABILITY,
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
# Şehir adı en fazla üç kelimedir ("Yeni Delhi"); her kelime aynı `_CITY` biçim hükmünden geçer.
_CITY_MAX_NAME_WORDS = 3


def _city_title(token: str) -> str:
    """Türkçe büyük harf hükmü: `token.title()` "İzmir"i "Izmir" yapardı (ölçülen taban kusuru)."""
    return token[:1].replace("i", "İ").replace("ı", "I").upper() + token[1:]


def _weather_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    location = arguments.get("location")
    if location is None:
        return {}
    if not isinstance(location, str) or _CITY.fullmatch(location) is None:
        return None
    # Same Turkish-aware capitalization the legacy city parser used.
    return {"location": _city_title(location)}


def _city_set_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """BRAIN-03 dilim 1: önerilen şehir adı Core'da YALNIZ biçim hükmünden geçer.

    Retire edilen yüzey kalıbı `(.+?)` ile her şeyi alıp `.title()` uyguluyordu; artık hem
    biçim hem Türkçe büyük/küçük harf hükmü tek `_CITY` sözleşmesinden geçer. Anlam kararı
    ("bu kelime şehir olabilir mi") Brain'indir: Core işlev sözcüğü listesi tutmaz, böylece
    iki katman aynı hükmü iki kez üretmez. Biçim kurallarına uymayan hiçbir öneri zaten
    Brain'den çıkmaz (koruma testi: `test_the_proposal_the_brain_makes_is_always_the_one_core_accepts`)."""
    location = arguments.get("location")
    if not isinstance(location, str):
        return None
    tokens = location.split(" ")
    if not 1 <= len(tokens) <= _CITY_MAX_NAME_WORDS \
            or any(_CITY.fullmatch(token) is None for token in tokens):
        return None
    return {"location": " ".join(_city_title(token) for token in tokens)}


def _city_reset_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    # Silme isteğinin hedefi yoktur; bir şehir adı taşımaya çalışan öneri doğrulanmış değildir.
    return None if "location" in arguments else {}


# BRAIN-03 dilim 2: alıcı adı ve gövde tek biçim sözleşmesidir. Anlam kararı ("bu alıcı gerçek
# bir kişi mi") burada verilmez: kayıtlı kişi araması yürütücünün bounded defter sorgusudur
# (`messaging.find_contact`) ve uydurma numara üretmez.
_MESSAGE_RECIPIENT = re.compile(r"[a-zçğıöşü]{2,40}(?: [a-zçğıöşü]{1,25}){0,3}")
_CONTACT_OPERATIONS = frozenset({"add", "list"})


def _name_title(name: str) -> str:
    """Türkçe büyük harf hükmü tek yerden (`str.title()` "İzmir"i "Izmir" yapardı)."""
    return " ".join(_city_title(token) for token in name.split())


def _message_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """BRAIN-03 dilim 2: alıcı/gövde slotlarını yalnız biçim hükmünden geçirir."""
    if set(arguments) - {"original_text", "recipient", "body"}:
        return None
    recipient, body = arguments.get("recipient", ""), arguments.get("body", "")
    if not isinstance(recipient, str) or not isinstance(body, str):
        return None
    recipient, body = recipient.strip(), body.strip()
    if recipient:
        if _MESSAGE_RECIPIENT.fullmatch(recipient) is None:
            return None
        recipient = _name_title(recipient)
    if "\x00" in body or len(body) > MESSAGE_BODY_MAX:
        return None
    return {"recipient": recipient, "body": body}


def _contacts_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Rehber önerisi: işlem kapalı kümeden, numara mevcut normalleştiriciden geçer."""
    if set(arguments) - {"original_text", "operation", "name", "phone"}:
        return None
    operation = arguments.get("operation")
    if operation not in _CONTACT_OPERATIONS:
        return None
    if operation == "list":
        # Listeleme hedef taşımaz; ek alan taşıyan öneri doğrulanmış değildir.
        return {"operation": "list"} if set(arguments) <= {"original_text", "operation"} else None
    name, phone = arguments.get("name"), arguments.get("phone")
    if not isinstance(name, str) or _MESSAGE_RECIPIENT.fullmatch(name.strip()) is None:
        return None
    if not isinstance(phone, str):
        return None
    from modules import messaging
    normalized = messaging.normalize_phone(phone)
    if normalized is None:
        return None
    return {"operation": "add", "name": _name_title(name.strip()), "phone": normalized}


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


def _organize_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Core, önerilen düzenleme anahtarını kapalı kimlik kümesinde yeniden doğrular.

    Ham metin burada hedef seçmez: anahtar yalnız domain'in kapalı `ORGANIZE_FOLDERS` kümesindendir;
    yol etki sahibi yürütücünün kendi sınırında gerçek klasöre çözülür, çözülemezse işlem başlamaz.
    Silme yetkisi bu sözleşmede hiç yoktur; tek operation taşınmadır."""
    from modules import files
    if set(arguments) - {"operation", "folder", "original_text"}:
        return None
    if arguments.get("operation") != ORGANIZE_OPERATION:
        return None
    folder = arguments.get("folder")
    if not isinstance(folder, str) or folder not in files.ORGANIZE_FOLDERS:
        return None
    return {"operation": ORGANIZE_OPERATION, "folder": folder}


_FOLDER_ANALYSIS_NAME_MAX = 40
# Ad asla bir yol değildir: ayraç, üst-dizin ve denetim karakteri taşıyan bir öneri reddedilir.
_FOLDER_ANALYSIS_NAME_BAD = re.compile(r"[/\\:*?\"<>|\x00-\x1f\x7f]|\.\.|^$")


def _folder_analysis_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Core, önerilen klasör anahtarlarını kapalı kümede yeniden doğrular; yol burada doğmaz.

    Brain üç kapalı alan taşır: hangi izinli kök (`folder`), "klasör" sözünden önceki sözcük tek başına
    bilinen bir kök mü (`named`) ve o sözcük (`name`). Kökler yalnız `folder_analysis.FOLDER_KEYS`
    kümesindendir; ad sınırlı tek sözcüktür. Kimlik çözümü ve disk erişimi etki sahibinin kendi sınırındadır."""
    from modules import folder_analysis
    if set(arguments) - {"operation", "folder", "named", "name", "original_text"}:
        return None
    if arguments.get("operation") != FOLDER_ANALYSIS_OPERATION:
        return None
    result: dict[str, Any] = {"operation": FOLDER_ANALYSIS_OPERATION}
    for key in ("folder", "named"):
        value = arguments.get(key)
        if not isinstance(value, str) or (value and value not in folder_analysis.FOLDER_KEYS):
            return None
        result[key] = value
    name = arguments.get("name")
    if not isinstance(name, str) or len(name) > _FOLDER_ANALYSIS_NAME_MAX:
        return None
    if name and _FOLDER_ANALYSIS_NAME_BAD.search(name):
        return None
    result["name"] = name
    return result


_WATCHER_FOLDERS = frozenset({"jarvis", "downloads", "desktop", "documents", "pictures"})
_WATCHER_EXTENSIONS = frozenset({".pdf", ".docx", ".xlsx", ".xlsm", ".csv", ".pptx",
                                 ".png", ".jpg", ".jpeg", ".webp"})
_WATCHER_ACTIONS = frozenset({"notify", "summary", "workbench"})


def _watcher_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Core validates every watcher operation and closed folder/extension/action vocabulary."""
    if set(arguments) - {"original_text", "watcher"}:
        return None
    row = arguments.get("watcher")
    if not isinstance(row, Mapping):
        return None
    operation = row.get("operation")
    if not isinstance(operation, str):
        return None
    if operation in {"list", "run_pending"}:
        return {"watcher": {"operation": operation}} if set(row) == {"operation"} else None
    if operation == "stop":
        if set(row) - {"operation", "folder"}:
            return None
        folder = row.get("folder")
        if folder is not None and (not isinstance(folder, str) or folder not in _WATCHER_FOLDERS):
            return None
        return {"watcher": {"operation": "stop", **({"folder": folder} if folder else {})}}
    if operation != "add" or set(row) != {"operation", "folder", "extensions", "action", "instruction"}:
        return None
    folder, extensions, action, instruction = (
        row.get("folder"), row.get("extensions"), row.get("action"), row.get("instruction")
    )
    if (not isinstance(folder, str) or folder not in _WATCHER_FOLDERS
            or not isinstance(action, str) or action not in _WATCHER_ACTIONS):
        return None
    if (not isinstance(extensions, (list, tuple)) or len(extensions) > len(_WATCHER_EXTENSIONS)
            or any(not isinstance(ext, str) or ext not in _WATCHER_EXTENSIONS for ext in extensions)
            or len(set(extensions)) != len(extensions)):
        return None
    if not isinstance(instruction, str) or len(instruction) > 300 or "\x00" in instruction:
        return None
    if action in {"summary", "workbench"} and not instruction.strip():
        return None
    return {"watcher": {
        "operation": "add",
        "folder": folder,
        "extensions": sorted(extensions),
        "action": action,
        "instruction": instruction,
    }}


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



_FILE_MUTATION_FOLDERS = frozenset({"masaüstü", "masaustu", "indirilenler", "belgeler", "resimler"})


def _file_mutate_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    if set(arguments) - {"original_text", "mutation"}:
        return None
    row = arguments.get("mutation")
    if not isinstance(row, Mapping):
        return None
    operation = row.get("operation")
    if operation == "undo":
        return {"operation": "undo"} if set(row) == {"operation"} else None
    if operation == "move":
        if set(row) != {"operation", "path", "folder"}:
            return None
        path, folder = row.get("path"), row.get("folder")
        if not isinstance(path, str) or not 0 < len(path) <= 4096 or "\x00" in path:
            return None
        if not (os.path.isabs(path) or re.match(r"^[A-Za-z]:[\\/]", path)):
            return None
        if not isinstance(folder, str) or folder.casefold() not in _FILE_MUTATION_FOLDERS:
            return None
        return {"operation": "move", "path": path, "folder": folder}
    if operation == "rename":
        if set(row) != {"operation", "path", "name"}:
            return None
        path, name = row.get("path"), row.get("name")
        if not isinstance(path, str) or not 0 < len(path) <= 4096 or "\x00" in path:
            return None
        if not (os.path.isabs(path) or re.match(r"^[A-Za-z]:[\\/]", path)):
            return None
        if not isinstance(name, str) or not 0 < len(name.strip()) <= 120 or "\x00" in name:
            return None
        if re.search(r'[<>:"/\\\\|?*\x00-\x1f]', name) or name.endswith((" ", ".")):
            return None
        return {"operation": "rename", "path": path, "name": name.strip()}
    if operation == "create":
        if set(row) != {"operation", "folder", "name", "content"}:
            return None
        folder, name, content = row.get("folder"), row.get("name"), row.get("content")
        if not isinstance(folder, str) or folder.casefold() not in {"masaüstü", "masaustu", "indirilenler", "belgeler"}:
            return None
        if not isinstance(name, str) or not 0 < len(name.strip()) <= 120 or "\x00" in name:
            return None
        if re.search(r'[<>:"/\\\\|?*\x00-\x1f]', name) or name.endswith((" ", ".")):
            return None
        if not isinstance(content, str) or len(content) > 16000 or "\x00" in content:
            return None
        return {"operation": "create", "folder": folder, "name": name.strip(), "content": content}
    return None

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


_AUDIO_ACTIONS = frozenset({"mute", "unmute", "open", "volume_up", "lower"})
_MEDIA_ACTIONS = frozenset({"next", "prev", "play_pause"})
_WAKE_PAYLOAD = {
    "wake_word": "Jarvis",
    "wake_aliases": ["jarvis", "hey jarvis", "yarvis"],
    "wake_engine": "auto",
}


def _only_original_text(arguments: Mapping[str, Any]) -> bool:
    """Cihaz eyleminin tek girdisi cümlenin kendisidir; ham metinden başka alan üretilmez."""
    return not set(arguments) - {"original_text"}


def _audio_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    row = arguments.get("audio")
    if not isinstance(row, Mapping) or set(row) != {"action"}:
        return None
    action = row.get("action")
    if action not in _AUDIO_ACTIONS:
        return None
    return {"action": action}


def _media_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    row = arguments.get("media")
    if not isinstance(row, Mapping) or set(row) != {"action"}:
        return None
    action = row.get("action")
    if action not in _MEDIA_ACTIONS:
        return None
    return {"action": action}


def _visual_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Core accepts only one of the seven visual kinds selected by Understanding."""
    if set(arguments) - {"original_text", "kind"}:
        return None
    kind = arguments.get("kind")
    from modules.visual_types import TYPES
    return {"kind": kind} if kind in TYPES else None


def _capture_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    return {} if _only_original_text(arguments) else None


def _shutdown_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    return {} if _only_original_text(arguments) else None


def _wake_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Açıklama kapalı bir ayar yazması: kullanıcı metinden tek bir alan bile taşınmaz."""
    return ({"action": "settings_save", "params": {"data": dict(_WAKE_PAYLOAD)}}
            if _only_original_text(arguments) else None)


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
    # BRAIN-03 dilim 1: kayıtlı şehir tercihini yazma/silme kararı artık Brain önerisi,
    # değer Core'da doğrulanır ve etki tek intent sahibinde (`engine_intents`) yürür.
    WEATHER_CITY_SET_CAPABILITY: ("city_set", _city_set_args),
    WEATHER_CITY_RESET_CAPABILITY: ("city_reset", _city_reset_args),
    # BRAIN-03 dilim 2: mesaj gönderimi ve rehber yazma/listeleme de Brain önerisi, Core biçim
    # hükmü; gönderim onayı ve kişi çözümlemesi mevcut `pending_msg`/`find_contact` sahiplerinde.
    MESSAGE_SEND_CAPABILITY: ("message_send", _message_args),
    CONTACTS_MANAGE_CAPABILITY: ("contacts_manage", _contacts_args),
    # Natural-language file target/operation is Brain-proposed and Core-validated; exact UI file buttons remain a front gate.
    "files.read": ("file_action", _file_args),
    FILE_MUTATE_CAPABILITY: ("file_mutate", _file_mutate_args),
    # PR3C-3: klasör düzenleme önizlemesi. Niyet ve kapalı klasör anahtarı Brain'den gelir,
    # Core anahtarı gerçek kimlikte yeniden doğrular; taşımayı yapacak olan yürütücü değildir.
    ORGANIZE_CAPABILITY: ("file_organize", _organize_args),
    # PR3C-4: klasör analizi. Kök anahtarı ve adı geçen alt klasör sözcüğü Brain'den gelir; Core kapalı
    # kümede yeniden doğrular ve HİÇ yol görmez. Diskteki gerçek kimliği yalnız yürütücü çözer.
    FOLDER_ANALYSIS_CAPABILITY: ("folder_analyze", _folder_analysis_args),
    WATCHER_CAPABILITY: ("watcher_manage", _watcher_args),
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
    # PR3A: `engine_commands` içindeki ham-metin dallarının kaldırıldığı yetenekler. Öneri
    # Understanding'de tek kalıptan doğar, burada yeniden doğrulanır ve etki sahibi yürütücüsünde kalır.
    AUDIO_CAPABILITY: ("audio_action", _audio_args),
    MEDIA_CAPABILITY: ("media_action", _media_args),
    VISUAL_CAPABILITY: ("visual_create", _visual_args),
    SCREEN_CAPTURE_CAPABILITY: ("screen_capture", _capture_args),
    SHUTDOWN_REQUEST_CAPABILITY: ("shutdown_request", _shutdown_args),
    SHUTDOWN_CANCEL_CAPABILITY: ("shutdown_cancel", _shutdown_args),
    WAKE_ENABLE_CAPABILITY: ("app_action", _wake_args),
}


# Fast Gate'in bütünüyle sahip olduğu okuma/kontrol turları: cümlenin kendisi yeniden
# yorumlanmaz, yalnız seçilen protokol tek bir Core niyetine bağlanır.
FAST_INTENTS: dict[str, tuple[str, dict[str, Any]]] = {
    "fast.time.read": ("fast_time", {}),
    "fast.date.read": ("fast_date", {}),
    "fast.system.status": ("fast_system_status", {}),
    "fast.speech.stop": ("fast_speech_stop", {}),
    "fast.mic.toggle": ("app_action", {"action": "set_flag", "params": {"name": "mic", "value": True}}),
}

# session.pending_level.select: seviye zaten Core'un sorduğu soruda saklı; cevap yalnız özelliği seçer.
LEVEL_SELECT_PROTOCOL = "session.pending_level.select"


def fast_plan(protocol: str | None, selection: Any) -> tuple[str, dict[str, Any]] | None:
    entry = FAST_INTENTS.get(protocol or "")
    if entry is None:
        return None
    intent, args = entry
    if protocol == "fast.mic.toggle":
        if selection not in {"mic_on", "mic_off"}:
            return None
        args = {"action": "set_flag", "params": {"name": "mic", "value": selection == "mic_on"}}
    return intent, dict(args)


def state_plan(protocol: str | None, selection: Any, level: Any) -> tuple[str, dict[str, Any]] | None:
    if protocol != LEVEL_SELECT_PROTOCOL or selection not in _LEVEL_PROPERTIES:
        return None
    if isinstance(level, bool) or not isinstance(level, int):
        return None
    return "level_set", {"property": selection, "level": max(0, min(100, level))}


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
    if WATCHER_ACTION_UNSUPPORTED in ambiguities:
        return "İzleme kuralında ne yapacağımı netleştir: haber ver, özetle veya tablo yap."
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
    if ORGANIZE_TARGET_AMBIGUOUS in ambiguities:
        return "Hangi klasörü düzenlememi istediğini netleştir: Masaüstü, İndirilenler veya Belgeler."
    if TRANSLATE_SOURCE_MISSING in ambiguities:
        return "Bu sohbette çevrilecek metni bulamadım. Metni buraya yapıştırabilirsin."
    if LEVEL_UNSPECIFIED in ambiguities:
        level = arguments.get("level")
        if isinstance(level, int) and not isinstance(level, bool):
            return f"Yüzde {max(0, min(100, level))}, ses mi parlaklık mı?"
    if APP_TARGET_MISSING in ambiguities:
        return _app_target_question(arguments)
    return None


_APP_TARGET_QUESTIONS = {APP_OPEN_CAPABILITY: "Neyi açmamı istiyorsun?",
                         APP_CLOSE_CAPABILITY: "Neyi kapatmamı istiyorsun?"}


def _app_target_kind(arguments: Mapping[str, Any]) -> str | None:
    kind = arguments.get("app_target_kind")
    return kind if kind in _APP_TARGET_QUESTIONS else None


def _app_target_question(arguments: Mapping[str, Any]) -> str | None:
    kind = _app_target_kind(arguments)
    return None if kind is None else _APP_TARGET_QUESTIONS[kind]


def clarification_effect(runtime: Any, ambiguities: tuple[str, ...], arguments: Mapping[str, Any]) -> None:
    """Core-owned state change that makes the asked question answerable next turn."""
    if LEVEL_UNSPECIFIED in ambiguities:
        level = arguments.get("level")
        if isinstance(level, int) and not isinstance(level, bool):
            runtime._session().pending_level = max(0, min(100, level))
        return
    if APP_TARGET_MISSING in ambiguities:
        kind = _app_target_kind(arguments)
        question = _app_target_question(arguments)
        if kind is None or question is None:
            return
        # Yalnız bounded proposal yazılır: hedefsiz fiilin cevabi mevcut app aç/kapat sahibine döner.
        from modules import app_actions
        app_actions.ask_clarification(runtime._session(), str(arguments.get("original_text") or ""),
                                      question, runtime.profile, {"kind": kind})