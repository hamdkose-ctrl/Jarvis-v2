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


# Order is the contract. This table is its only owner.
FRONT_GATES: tuple[str, ...] = (
    "file_command",
    "user_controls",
    "planner_command",
    "macro_run",
    "extra_commands",
)

# The range ``engine_commands.handle`` delegates instead of re-listing: shortcuts, then the
# domain cascade. PR3B §11/§25 B: the surface may not carry a second copy of this order.
TAIL_GATES: tuple[str, ...] = ("macro_run", "extra_commands")


def _gates(runtime: Any, command: str, lowered: str, plan: tuple[str, dict] | None = None) -> dict[str, Callable[[], Any]]:
    def planner_gate():
        # An accepted Core plan is not a new raw note/calendar instruction.
        # Only the established reminder creator has a bounded compatibility
        # exception for explicit note-add and pending-answer ownership.
        if plan is not None:
            if plan[0] != "reminder":
                return None
            from modules import main_planner
            with main_planner.core_reminder(plan[1]):
                return runtime._planner_command(command, lowered)
        return runtime._planner_command(command, lowered)

    def extra_commands():
        # The general raw cascade cannot reclassify a validated Core payload
        # into a second domain action for the same user turn.
        return None if plan is not None else runtime._extra_commands(command, lowered)

    def macro_gate():
        if plan is not None:
            # A user-saved exact trigger remains authoritative. The legacy
            # fuzzy suffix aliases are NOT evidence to override a typed plan.
            profile = getattr(runtime, "profile", None)
            data = getattr(profile, "data", None)
            macros = data.get("macros") if isinstance(data, dict) else None
            keyer = getattr(runtime, "_macro_key", None)
            if not isinstance(macros, dict) or not callable(keyer):
                return None
            if keyer(lowered) not in macros:
                return None
        return runtime._macro_run(lowered)

    def file_gate():
        # The explicit quoted-path UI protocol still outranks a Core plan.
        # A normal typed plan must not fall into workbench.followup, which
        # searches raw text and may re-create the last document as a side effect.
        if plan is not None:
            explicit = getattr(runtime, "_FILE_CMD", None)
            if explicit is None or explicit.match(command.strip()) is None:
                return None
        return runtime._file_command(command)

    return {
        "file_command": file_gate,
        # All accepted Core plans can carry user data. Only truly
        # unplanned turns may invoke this raw share/camera/voice recognizer.
        "user_controls": lambda: (None if plan is not None else runtime._user_controls(command, lowered)),
        "planner_command": planner_gate,
        "macro_run": macro_gate,
        "extra_commands": extra_commands,
    }


def claim(runtime: Any, command: str, plan: tuple[str, dict] | None = None) -> tuple[str, Any] | None:
    """Return (gate_name, reply) of the first legacy front gate that answers, else None."""
    if plan is not None and plan[0] in {"photo_action", "user_manage", "macro_teach", "macro_manage"}:
        # A validated photo plan targets a canonical artifact, not a raw-text phrase: legacy
        # mutation gates must not reinterpret the same utterance.
        return None
    lowered = _lowered(runtime, command)
    return _claim_range(runtime, command, lowered, FRONT_GATES, plan)


def claim_tail(runtime: Any, command: str, lowered: str | None = None) -> tuple[str, Any] | None:
    """``engine_commands.handle``'ın devrettiği kuyruk aralığı: kısayollar, sonra domain cascade'i.

    Yüzey kendi handler tuple'ını artık taşımıyor (§25 B); sıra ve argüman biçimi yalnız bu
    tablodan gelir. Erken efekt gate'leri (dosya/ayyarlar/sayfa/planner) burada ikinci kez
    çalışmaz: bu aralık onları yüzeyin kendisine bırakır, yoksa aynı taşıma/yayın iki kez olur.
    Cascade'in kendisi (BRAIN-MIG-052) kanonical capability parity kazanan kollara bölünene kadar
    domain-owned kalır; PR3C satırı budur, bu fonksiyon değil."""
    if lowered is None:
        lowered = _lowered(runtime, command)
    return _claim_range(runtime, command, lowered, TAIL_GATES)


def _lowered(runtime: Any, command: str) -> str:
    lower = getattr(runtime, "_tr_lower", None)
    return lower(command) if callable(lower) else command.casefold()


def _claim_range(runtime: Any, command: str, lowered: str, names: tuple[str, ...],
                 plan: tuple[str, dict] | None = None) -> tuple[str, Any] | None:
    table = _gates(runtime, command, lowered, plan)
    for name in names:
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
    "file_command": ("_file_command",),
    "user_controls": ("_user_controls",), "planner_command": ("_planner_command",), "macro_run": ("_macro_run",), "extra_commands": ("_extra_commands",),
}


def _present(runtime: Any, name: str) -> bool:
    return all(hasattr(runtime, attr) for attr in _ATTRS[name])
