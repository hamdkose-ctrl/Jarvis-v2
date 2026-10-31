"""Explicit precedence contract between legacy front gates and Brain-planned Core intents.

Core never executes a Brain ``capability_hint`` ahead of a gate that the legacy pipeline
(``engine_commands.handle``) evaluates *before* the generic fast path. The gates below keep
exactly that relative order; ``engine_commands.handle`` evaluates the same names in the same
order (pinned by tests/test_brain_precedence.py). A gate that answers owns the request, so a
user macro, a saved custom command, a planner phrase, a Windows-settings page or a Jarvis
self-control command always beats weather/level Core dispatch.

This module decides nothing about permission or effect: it only calls the existing handlers.
"""
from __future__ import annotations

from typing import Any, Callable

# Order is the contract. Do not reorder without changing engine_commands.handle.
FRONT_GATES: tuple[str, ...] = (
    "windows_settings",
    "selfctl",
    "user_command",
    "planner_command",
    "macro_teach",
    "macro_manage",
    "macro_run",
    "extra_commands",
)


def _gates(runtime: Any, command: str, lowered: str) -> dict[str, Callable[[], Any]]:
    def selfctl():
        from modules import selfctl as module
        return module.handle(lowered, runtime.emit)

    return {
        "windows_settings": lambda: runtime.system_control.windows_settings(lowered),
        "selfctl": selfctl,
        "user_command": lambda: runtime._user_command(command, lowered),
        "planner_command": lambda: runtime._planner_command(command, lowered),
        "macro_teach": lambda: runtime._macro_teach(command, lowered),
        "macro_manage": lambda: runtime._macro_manage(lowered),
        "macro_run": lambda: runtime._macro_run(lowered),
        "extra_commands": lambda: runtime._extra_commands(command, lowered),
    }


def claim(runtime: Any, command: str) -> tuple[str, Any] | None:
    """Return (gate_name, reply) of the first legacy front gate that answers, else None."""
    lower = getattr(runtime, "_tr_lower", None)
    lowered = lower(command) if callable(lower) else command.casefold()
    table = _gates(runtime, command, lowered)
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
    "windows_settings": ("system_control",), "selfctl": ("emit",), "user_command": ("_user_command",),
    "planner_command": ("_planner_command",), "macro_teach": ("_macro_teach",),
    "macro_manage": ("_macro_manage",), "macro_run": ("_macro_run",), "extra_commands": ("_extra_commands",),
}


def _present(runtime: Any, name: str) -> bool:
    return all(hasattr(runtime, attr) for attr in _ATTRS[name])
