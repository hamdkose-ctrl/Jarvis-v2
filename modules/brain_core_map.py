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
from modules.brain_understanding import FILE_SUMMARIZE, FILE_TARGET_UNRESOLVED, LEVEL_CAPABILITY, LEVEL_UNSPECIFIED

_LEVEL_PROPERTIES = frozenset({"volume", "brightness"})


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


def _file_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Core re-validates the Brain-resolved file: exact summarize op, absolute existing file, allowed root."""
    path = arguments.get("path")
    if arguments.get("operation") != FILE_SUMMARIZE or not isinstance(path, str) or not path.strip():
        return None
    if "\x00" in path or not os.path.isabs(path):
        return None
    try:
        from pathlib import Path
        from modules import nxapi
        target = Path(path)
        if not target.is_file() or not nxapi.allowed(target):
            return None
    except Exception:
        _record_failure("modules/brain_core_map.py:file_args")
        return None
    return {"path": path}


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


# hint -> (existing Core intent, argument validator). Hints absent here stay on the
# existing handler path until their own migration.
CORE_INTENTS: dict[str, tuple[str, Callable[[Mapping[str, Any]], dict[str, Any] | None]]] = {
    LEVEL_CAPABILITY: ("level_set", _level_args),
    "weather.read": ("weather", _weather_args),
    "weather.read.current": ("weather", _weather_args),
    # Only the summarize operation on a Brain-resolved file; other files.read operations stay
    # on the legacy owner (PARTIAL_CORE_HINTS) because they carry no validated operation.
    "files.read": ("doc_summary", _file_args),
    # Reminder creation; edit/snooze/calendar stay in the planner (see brain_precedence).
    "reminder.propose": ("reminder", _reminder_args),
}


# Capability hints Understanding may emit that are NOT dispatched from the proposal. Each one has a
# named legacy owner that parses the raw text itself; the hint stays advisory until that owner gets a
# validated Core intent. A hint with neither a Core intent nor an owner here is a drift error (tested).
LEGACY_OWNED_HINTS: dict[str, str] = {
    "notes.read": "engine_tools._extra_commands (kb/tasks.handle)",
    "research.search": "task intent (goal_executor) via _legacy_route_projection",
}


# Hints that are Core-mapped for some operations; the rest of the hint is still owned by this legacy path.
PARTIAL_CORE_HINTS: dict[str, str] = {
    "files.read": "engine_commands._file_command + legacy handler (göster/aç/bul/listele/karşılaştır)",
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
    if FILE_TARGET_UNRESOLVED in ambiguities:
        return "Hangi dosyayı özetleyeyim? Dosya adını yaz ya da dosyayı sohbete ekle."
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
