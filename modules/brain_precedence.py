"""Explicit precedence contract between legacy front gates and Brain-planned Core intents.

Core never executes a Brain ``capability_hint`` ahead of a gate that the legacy pipeline
(``engine_commands.handle``) evaluates *before* the generic fast path. The gates below keep
exactly that relative order; ``engine_commands.handle`` evaluates the same names in the same
order (pinned by tests/test_brain_precedence.py). A gate that answers owns the request, so a
user macro, a saved custom command, a planner phrase, a Windows-settings page or a Jarvis
self-control command always beats weather/level Core dispatch.

Canonical data requests are the narrow exception when Brain has already produced a validated
Core plan for the same surface. In that case legacy UI/read gates must not shadow the data
operation; explicit page/section navigation and unmigrated planner operations stay unchanged.

This module decides nothing about permission or effect: it only calls the existing handlers.
"""
from __future__ import annotations

from typing import Any, Callable

# Order is the contract. Do not reorder without changing engine_commands.handle.
FRONT_GATES: tuple[str, ...] = (
    "file_command",
    "windows_settings",
    "selfctl",
    "user_command",
    "planner_command",
    "macro_teach",
    "macro_manage",
    "macro_run",
    "extra_commands",
)


def _gates(runtime: Any, command: str, lowered: str, plan: tuple[str, dict] | None = None) -> dict[str, Callable[[], Any]]:
    def selfctl():
        # A canonical notes_read plan means the user asked for note DATA, not the Notlar UI page.
        # Keep the legacy selfctl grammar unchanged for Live/old callers until PR9; only the
        # canonical Brain/Core handoff gets this semantic distinction.
        if plan is not None and plan[0] in {"notes_read", "notes_write"}:
            return None
        from modules import selfctl as module
        return module.handle(lowered, runtime.emit)

    def planner_gate():
        # Canonical notes_read already has a validated Core plan. Do not let the planner's old
        # read/list branch reinterpret the same utterance. Mutation/search/reminder/calendar
        # branches are unchanged and remain domain-owned until their own migration decision.
        if plan is not None and plan[0] in {"notes_read", "notes_write", "file_action"}:
            return None
        # A reminder plan is executed BY the planner at its own creation slot with the Core-validated
        # arguments (main_planner.core_reminder): earlier planner branches (pending answers, notes,
        # edit/snooze) answer first and later branches (calendar, agenda) are never reached.
        if plan is None or plan[0] != "reminder":
            return runtime._planner_command(command, lowered)
        from modules import main_planner
        with main_planner.core_reminder(plan[1]):
            return runtime._planner_command(command, lowered)

    def extra_commands():
        # The exact quoted-path UI file_command above remains authoritative. For a canonical natural-language
        # file_action, the later files.handle chain must not get a second chance at the same target.
        # A validated notes plan likewise owns its request: unrelated later chains (e.g. the mail/agenda
        # handler reacting to a word like "toplantı") must not answer it instead.
        if plan is not None and plan[0] in {"file_action", "notes_read", "notes_write"}:
            return None
        return runtime._extra_commands(command, lowered)

    return {
        "file_command": lambda: runtime._file_command(command),
        "windows_settings": lambda: runtime.system_control.windows_settings(lowered),
        "selfctl": selfctl,
        "user_command": lambda: runtime._user_command(command, lowered),
        "planner_command": planner_gate,
        "macro_teach": lambda: runtime._macro_teach(command, lowered),
        "macro_manage": lambda: runtime._macro_manage(lowered),
        "macro_run": lambda: runtime._macro_run(lowered),
        "extra_commands": extra_commands,
    }


def claim(runtime: Any, command: str, plan: tuple[str, dict] | None = None) -> tuple[str, Any] | None:
    """Return (gate_name, reply) of the first legacy front gate that answers, else None."""
    lower = getattr(runtime, "_tr_lower", None)
    lowered = lower(command) if callable(lower) else command.casefold()
    table = _gates(runtime, command, lowered, plan)
    for name in FRONT_GATES:
        try:
            reply = table[name]()
        except AttributeError:
            if _present(runtime, name):
                raise
            continue  # minimal runtime (acceptance harness stub) without that legacy gate
        if reply is not None:
            return name, reply
    return None


_ATTRS = {
    "file_command": ("_file_command",), "windows_settings": ("system_control",), "selfctl": ("emit",), "user_command": ("_user_command",),
    "planner_command": ("_planner_command",), "macro_teach": ("_macro_teach",),
    "macro_manage": ("_macro_manage",), "macro_run": ("_macro_run",), "extra_commands": ("_extra_commands",),
}


def _present(runtime: Any, name: str) -> bool:
    return all(hasattr(runtime, attr) for attr in _ATTRS[name])
