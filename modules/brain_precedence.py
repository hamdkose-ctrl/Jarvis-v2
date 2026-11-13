"""Bounded explicit-owner protocols, not a second natural-language router.

Only a validated machine-addressed file UI action and an exact stored macro
trigger may claim a turn. General planner, camera/share, note, and cross-domain
keyword cascades were retired by BRAIN-03; model proposals proceed to the same
Core validators and existing workers. No permission or effect is decided here.
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
_EXPLICIT_WORKFLOW_OWNER = re.compile(
    r"^görev\s+akışı\s+(?:rapor|mail|kod|video)\s*:\s*\S.*$",
    re.I | re.S,
)


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
