"""Explicit precedence contract between legacy front gates and Brain-planned Core intents.

The gate order is the only owner of legacy front-door precedence. A validated
Core plan cannot be reinterpreted as a second command by raw controls, general
planner parsing, or the extra-command cascade. Explicit quoted-path UI commands,
a registered exact macro trigger and the Core-bound reminder creator's existing
note-add compatibility are bounded exceptions.

This protects accepted typed proposals. It does not retire unmapped legacy
semantic handlers; BRAIN-03 issue #545 remains open until their Core parity
and physical removal are proven.

This module decides nothing about permission or effect: it only calls the existing handlers.
"""
from __future__ import annotations

import re
from typing import Any, Callable

# Exact, explicit desktop-owner protocol. This is a bounded admin prefix, not a
# natural-language classifier; Brain domains may consult it only to avoid stealing
# a turn that belongs to the user's explicitly addressed PC task.
_EXPLICIT_DESKTOP_OWNER = re.compile(
    r"^pc\s+(?:görev(?:i)?(?=[:\s])|onayla\s|iz(?:in|ni|inleri|inler)\b)",
    re.I,
)


def explicit_desktop_owner_protocol(text: str) -> bool:
    return isinstance(text, str) and _EXPLICIT_DESKTOP_OWNER.match(text.strip()) is not None

# Explicit workflow prefix: like the PC task prefix, this exact protocol owns the full
# utterance before any domain-specific proposal can claim words inside its payload.
_EXPLICIT_WORKFLOW_OWNER = re.compile(r"^görev\s+akışı(?:\s|:|$)", re.I)


def explicit_workflow_owner_protocol(text: str) -> bool:
    return isinstance(text, str) and _EXPLICIT_WORKFLOW_OWNER.match(text.strip()) is not None


# Only machine-addressed UI syntax and a saved, exact trigger remain.
# Neither branch classifies natural language or scans domain handlers.
FRONT_GATES: tuple[str, ...] = ("file_command", "macro_run")


def claim(runtime: Any, command: str, plan: tuple[str, dict] | None = None) -> tuple[str, Any] | None:
    """Bounded explicit owner protocol, never a secondary semantic authority."""
    if plan is not None and plan[0] in {"photo_action", "user_manage", "macro_teach", "macro_manage"}:
        return None
    from modules import main_documents
    match = getattr(runtime, "_FILE_CMD", None)
    exact_file = main_documents.explicit_ui_file_command(command, match)
    if exact_file:
        handle = getattr(runtime, "_file_command", None)
        if callable(handle):
            output = handle(command)
            if output is not None:
                return "file_command", output

    data = getattr(getattr(runtime, "profile", None), "data", None)
    macros = data.get("macros") if isinstance(data, dict) else None
    keyer = getattr(runtime, "_macro_key", None)
    runner = getattr(runtime, "_macro_run", None)
    if isinstance(macros, dict) and callable(keyer) and callable(runner):
        lower = getattr(runtime, "_tr_lower", None)
        normalized = lower(command) if callable(lower) else command.casefold()
        # A stored normalized key is the entire trigger, never a bag of
        # significant words. Removing all punctuation with _macro_key would
        # otherwise turn "sabah rutini?" or a quoted mention into an effect.
        # Only whitespace folding and terminal command punctuation are allowed.
        literal = " ".join(normalized.strip(" .!").split())
        if literal and keyer(literal) == literal and literal in macros:
            output = runner(literal)
            if output is not None:
                return "macro_run", output
    return None
