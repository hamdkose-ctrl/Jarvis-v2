"""Core side of the Brain contract: validated capability hint -> existing Core intent.

Brain only proposes (``capability_hint`` + semantic ``arguments``). This table is
Core's own allowlist: a hint that is not listed here is never executed from the
proposal, and every argument is re-validated here before it reaches
``engine_intents.dispatch``. Nothing in this module decides permission or effect
policy; the dispatched Core intents keep their existing guards.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Mapping

from modules.brain_understanding import LEVEL_CAPABILITY, LEVEL_UNSPECIFIED

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


# hint -> (existing Core intent, argument validator). Hints absent here stay on the
# existing handler path until their own migration.
CORE_INTENTS: dict[str, tuple[str, Callable[[Mapping[str, Any]], dict[str, Any] | None]]] = {
    LEVEL_CAPABILITY: ("level_set", _level_args),
    "weather.read": ("weather", _weather_args),
    "weather.read.current": ("weather", _weather_args),
}


def core_plan(hint: str | None, arguments: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Return (core_intent, validated_args) or None when the hint is not Core-mapped/invalid."""
    entry = CORE_INTENTS.get(hint or "")
    if entry is None:
        return None
    intent, validate = entry
    args = validate(arguments)
    return None if args is None else (intent, args)


def clarification_question(ambiguities: tuple[str, ...], arguments: Mapping[str, Any]) -> str | None:
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
