"""Physical interactive resources on the EXISTING Scheduler/Core LeaseTable.

These reservations are issued only by trusted engine/voice call sites. No
language model may supply a resource key, owner or execution permission. The
short-lived LeaseTable ticket is paired with the existing process-wide OS claim:
a stalled provider cannot silently make the physical device available when a
local lease TTL expires. The native VoiceCoordinator remains the only playback
owner; no second speech queue or scheduler is created.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
from pathlib import Path
import secrets

from modules import resource_leases

_KINDS = frozenset({"stt", "tts", "llm", "output_device"})
_BACKENDS = frozenset({"edge", "piper", "sapi"})


def trusted_key(kind: str, *, owner: str, backend: str | None = None) -> str:
    """Derive a stable device/model identity from trusted runtime metadata only."""
    if kind not in _KINDS or not isinstance(owner, str) or not owner.strip():
        raise ValueError("Interactive resource kind/owner invalid.")
    if kind == "tts":
        if backend not in _BACKENDS:
            raise ValueError("Unknown installed voice backend.")
        target = backend
    elif backend is not None:
        raise ValueError("Only TTS takes a selected voice backend.")
    elif kind == "llm":
        # Owner scoped, like model_wait._PENDING; never a model-supplied account.
        target = hashlib.sha256(owner.encode("utf-8")).hexdigest()[:32]
    elif kind == "stt":
        target = "microphone"
    else:
        target = "default"
    return resource_leases.resource_key(kind, target)


@contextmanager
def claim(kind: str, *, owner: str, operation_id: str | None = None,
          backend: str | None = None):
    """Hold the existing table ticket AND physical claim across the actual call.

    This cannot authorize a Core effect or guarantee that a remote provider
    stops at the deadline. When a claim is busy, fail closed rather than
    pretending the microphone/speaker/model was acquired.
    """
    key = trusted_key(kind, owner=owner, backend=backend)
    ident = operation_id or secrets.token_hex(16)
    if not isinstance(ident, str) or not ident.strip() or len(ident) > 128:
        raise ValueError("Interactive operation identity invalid.")
    root = Path.home() / ".jarvis" / "interactive-claims"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise resource_leases.LeaseConflict("Interactive claim root invalid.")
    # One already-installed lease table; this module MUST NOT instantiate one.
    from modules import goal_executor
    leases = goal_executor._RESOURCE_LEASES
    ticket = leases.acquire(
        owner=owner, job_id=ident, step_id="interactive-" + kind,
        plan_version=1, command_id=ident + "-" + kind,
        keys=(key,), ttl=300,
    )
    try:
        with resource_leases.process_resource_claim(root, key):
            yield
    finally:
        # The physical OS claim stays held until the operation exits, even
        # when a wake-word listener or stalled provider exceeds the in-process
        # 300 s ticket TTL. An expired ticket was already revoked by the table;
        # releasing it again must not turn a valid long microphone wait into
        # a spurious failure or revive the stale lease.
        if leases.validate(ticket):
            leases.release(ticket)
