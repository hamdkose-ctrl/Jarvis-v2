"""BRAIN-07A: scheduler-owned, in-process ResourceLease fencing primitive.

The existing Scheduler may own ONE LeaseTable instance. This module does not
schedule work, store GoalState, grant permission or approve an effect. This
first slice intentionally has NO production dispatch wiring and is NOT a
durable cross-process lock. Restart recovery and result-commit fencing require
later BRAIN-07 slices before any effectful capability can use leases.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import re
import secrets
import threading
import time
from typing import Callable


_RESOURCE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_ALLOWED_KINDS = frozenset((
    "file", "window", "browser_session", "gmail_account", "provider",
))


class LeaseConflict(ValueError):
    """Resource is currently owned by a different in-flight operation."""


class LeaseFenceError(ValueError):
    """Expired, forged or already replaced owner cannot heartbeat or release."""


def resource_key(kind: str, target: str | None = None) -> str:
    """Accept canonical Core-derived resource IDs, never raw/model file paths."""
    if kind == "pc_desktop" and target is None:
        return kind
    if kind not in _ALLOWED_KINDS or not isinstance(target, str):
        raise ValueError("Unsupported or missing resource target.")
    if kind == "file":
        if not _HEX64.fullmatch(target):
            raise ValueError("File lease requires a canonical 64-hex artifact ID.")
    elif kind == "window":
        if (len(target) > 20 or not target.isascii() or not target.isdecimal()
                or int(target) <= 0 or str(int(target)) != target):
            raise ValueError("Window lease requires a positive canonical HWND.")
    elif not _RESOURCE_ID.fullmatch(target):
        raise ValueError("Resource target identity is non-canonical.")
    return f"{kind}:{target}"


def _key(value: str) -> str:
    if value == "pc_desktop":
        return value
    if not isinstance(value, str) or ":" not in value:
        raise ValueError("Resource key not canonical.")
    kind, ident = value.split(":", 1)
    if resource_key(kind, ident) != value:
        raise ValueError("Resource key not canonical.")
    return value


@dataclass(frozen=True)
class LeaseTicket:
    epoch: str
    serial: int
    renewal: int
    owner: str
    job_id: str
    step_id: str
    plan_version: int
    command_id: str
    keys: tuple[str, ...]
    deadline: float


class LeaseTable:
    """Atomic multi-key lease table for use INSIDE the existing Scheduler.

    Fencing is checked against an exact current ticket, not just a timestamp.
    Renewing returns a new ticket and invalidates the previous ticket snapshot.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._epoch = secrets.token_hex(16)
        self._serial = 0
        self._lock = threading.RLock()
        self._holders: dict[str, int] = {}
        self._active: dict[int, LeaseTicket] = {}

    def _expire(self, now: float) -> None:
        for serial, ticket in tuple(self._active.items()):
            if now >= ticket.deadline:
                self._discard(serial)

    def _discard(self, serial: int) -> None:
        ticket = self._active.pop(serial, None)
        if ticket is not None:
            for key in ticket.keys:
                if self._holders.get(key) == serial:
                    self._holders.pop(key)

    def acquire(
        self, *, owner: str, job_id: str, step_id: str,
        plan_version: int, command_id: str, keys: tuple[str, ...],
        ttl: float = 30.0,
    ) -> LeaseTicket:
        if (not all(isinstance(v, str) and v.strip() and len(v) <= 128
                    for v in (owner, job_id, step_id, command_id))
                or type(plan_version) is not int or plan_version < 1
                or type(ttl) not in (int, float) or not 1.0 <= ttl <= 300.0):
            raise ValueError("Lease owner, version, command or timeout invalid.")
        if not isinstance(keys, tuple) or not keys or len(keys) > 12:
            raise ValueError("Lease resource set must be nonempty and bounded.")
        for key in keys:
            _key(key)
        if tuple(sorted(set(keys))) != keys:
            raise ValueError("Lease keys must be sorted, unique, canonical.")
        with self._lock:
            now = self._clock()
            self._expire(now)
            if any(key in self._holders for key in keys):
                raise LeaseConflict("One or more resources are already leased.")
            self._serial += 1
            ticket = LeaseTicket(
                self._epoch, self._serial, 0, owner, job_id, step_id,
                plan_version, command_id, keys, now + ttl,
            )
            self._active[ticket.serial] = ticket
            for key in keys:
                self._holders[key] = ticket.serial
            return ticket

    def _require(self, ticket: LeaseTicket) -> LeaseTicket:
        if not isinstance(ticket, LeaseTicket) or ticket.epoch != self._epoch:
            raise LeaseFenceError("Lease belongs to a foreign or restarted owner.")
        current = self._active.get(ticket.serial)
        if current is None or current != ticket:
            raise LeaseFenceError("Lease already expired, released or replaced.")
        if self._clock() >= current.deadline:
            self._discard(current.serial)
            raise LeaseFenceError("Lease expired.")
        return current

    def validate(self, ticket: LeaseTicket) -> bool:
        with self._lock:
            try:
                self._require(ticket)
            except LeaseFenceError:
                return False
            return True

    def heartbeat(self, ticket: LeaseTicket, *, ttl: float = 30.0) -> LeaseTicket:
        if type(ttl) not in (float, int) or not 1.0 <= ttl <= 300.0:
            raise ValueError("Lease heartbeat timeout invalid.")
        with self._lock:
            current = self._require(ticket)
            refreshed = replace(current, renewal=current.renewal + 1, deadline=self._clock() + ttl)
            self._active[current.serial] = refreshed
            return refreshed

    def release(self, ticket: LeaseTicket) -> None:
        with self._lock:
            current = self._require(ticket)
            self._discard(current.serial)

    def occupied(self, key: str) -> bool:
        _key(key)
        with self._lock:
            self._expire(self._clock())
            return key in self._holders
