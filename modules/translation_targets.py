"""Canonical translation target languages.

One registry is the truth source for text, file and photo translation parsing and for Core's
target validation; no surface or validator keeps its own language list.
"""
import re

SUPPORTED_TARGETS = (
    ("turkce", "Türkçe"),
    ("ingilizce", "İngilizce"),
    ("almanca", "Almanca"),
    ("fransizca", "Fransızca"),
    ("arapca", "Arapça"),
    ("rusca", "Rusça"),
    ("ispanyolca", "İspanyolca"),
    ("japonca", "Japonca"),
    ("cince", "Çince"),
    ("korece", "Korece"),
    ("italyanca", "İtalyanca"),
)
_NAMES = dict(SUPPORTED_TARGETS)
_DISPLAY = tuple(label for _, label in SUPPORTED_TARGETS)
_ALTERNATION = "|".join(sorted(_NAMES, key=len, reverse=True))
_TARGET = re.compile(r"\b(" + _ALTERNATION + r")(?:['’]?ye|['’]?ya)?\b(?!['’]?(?:den|dan))")
# An explicit destination must be a supported language; a bare verb keeps the caller's fallback.
# Only the destination case (name + -ya/-ye) is checked, so "hızlıca çevir" is not a language.
_DESTINATION = re.compile(
    r"\b([a-z]{2,}(?:ca|ce))(?:['’]?(?:ya|ye))\s+(?:olarak\s+)?(?:cevir|tercume|translate)\b"
)


def _normalize(command: str) -> str:
    return command.casefold().translate(str.maketrans('çğıöşü', 'cgiosu')).replace('i\u0307', 'i')


def display_names() -> tuple[str, ...]:
    """Canonical target values Understanding may emit and Core may accept."""
    return _DISPLAY


def command_names() -> tuple[str, ...]:
    """Native and fast-keyboard spellings that may appear as a command's language token."""
    native = tuple(label.replace("İ", "i").casefold() for label in _DISPLAY)
    return tuple(dict.fromkeys(native + tuple(_NAMES)))


def is_supported_target(value: object) -> bool:
    return isinstance(value, str) and value in _DISPLAY


def target_from_command(command: str) -> str:
    """Accept Turkish characters and fast keyboard spellings; exclude source -den/-dan."""
    matches = _TARGET.findall(_normalize(command))
    return _NAMES[matches[-1]] if matches else ''


def explicit_target_unresolved(command: str) -> bool:
    """True when an explicit "X-e çevir" destination is not a supported language."""
    return any(_NAMES.get(word) is None for word in _DESTINATION.findall(_normalize(command)))
