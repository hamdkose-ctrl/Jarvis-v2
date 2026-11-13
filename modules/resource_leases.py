"""BRAIN-07: one Scheduler's in-process LeaseTable plus physical OS claims.

The existing Scheduler owns the per-process LeaseTable, including heartbeat,
generation and Core WorkerResult admission fencing. process_resource_claim
also provides cooperative OS-account physical claims for approved native
adapters; LeaseTable alone is NOT a cross-process lock or an effect approval.
Read-only canonical research/account workers are wired to production through
scheduler_resource_gate; effectful canonical workers remain unauthorized.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
import hashlib
import os
from pathlib import Path
import stat
import re
import secrets
import threading
import time
from typing import Callable


_RESOURCE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_ALLOWED_KINDS = frozenset((
    "file", "command", "window", "browser_session", "gmail_account", "provider",
    # Trusted local call sites only. These names are NOT an effect permission and
    # no model can acquire a device by supplying a free-form key.
    "stt", "tts", "llm", "output_device",
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
    if kind in ("file", "command"):
        if not _HEX64.fullmatch(target):
            raise ValueError("File/command lease requires a canonical 64-hex ID.")
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
        self._commands: dict[tuple[str, str, str, int, str], int] = {}
        self._active: dict[int, LeaseTicket] = {}

    def _expire(self, now: float) -> None:
        for serial, ticket in tuple(self._active.items()):
            if now >= ticket.deadline:
                self._discard(serial)

    def _discard(self, serial: int) -> None:
        ticket = self._active.pop(serial, None)
        if ticket is not None:
            command = (ticket.owner, ticket.job_id, ticket.step_id,
                       ticket.plan_version, ticket.command_id)
            if self._commands.get(command) == serial:
                self._commands.pop(command)
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
            command = (owner, job_id, step_id, plan_version, command_id)
            if command in self._commands:
                # A duplicate dispatch may accidentally derive different keys.
                # The same execution must never hold two live lease tickets.
                raise LeaseConflict("This command already has a live lease.")
            if any(key in self._holders for key in keys):
                raise LeaseConflict("One or more resources are already leased.")
            self._serial += 1
            ticket = LeaseTicket(
                self._epoch, self._serial, 0, owner, job_id, step_id,
                plan_version, command_id, keys, now + ttl,
            )
            self._active[ticket.serial] = ticket
            self._commands[command] = ticket.serial
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


@contextmanager
def process_resource_claim(owner_root: Path, key: str):
    """Nonblocking OS claim shared by separately running Windows/Unix workers.

    Scoped only to currently live read-only worker execution. The OS releases
    the byte-range/flock lock on process exit; the caller must STILL check the
    canonical GoalState, a live in-process ticket, and WorkerResult CAS.
    A crash does not prove a remote call was never issued.
    """
    canonical = _key(key)
    root = Path(owner_root)
    if root.is_symlink() or not root.is_dir():
        raise LeaseConflict("Resource owner directory is invalid.")
    # The lock file name cannot be controlled by a model-supplied path.
    name = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    path = root / (".resource-" + name + ".claim")
    if path.is_symlink():
        raise LeaseConflict("Resource claim cannot follow a symlink.")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise LeaseConflict("Cannot open the read-only resource claim.") from exc
    handle = os.fdopen(fd, "r+b", buffering=0)
    acquired = False
    try:
        details = os.fstat(handle.fileno())
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise LeaseConflict("Resource claim must be an ordinary private file.")
        try:
            if handle.seek(0, os.SEEK_END) == 0:
                # Windows denies writing a byte currently locked by
                # another process. Treat that as live contention, not a
                # raw PermissionError escaping file-effect admission.
                handle.write(b"0")
            handle.seek(0)
        except OSError as exc:
            raise LeaseConflict(
                "Resource claim initialization is busy or unavailable."
            ) from exc
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise LeaseConflict("Resource is already owned by another process.") from exc
        acquired = True
        yield
    finally:
        try:
            if acquired:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
