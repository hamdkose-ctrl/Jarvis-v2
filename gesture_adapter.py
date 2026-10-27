"""Deterministic gesture-to-intent input adapter.

This boundary accepts already-local/classified hand gestures. It never grants
identity, permission, approval, or effect authority. A caller may pass a
normalized intent onward only through Jarvis' existing decision/policy path.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

TRANSITION_IGNORE_SECONDS = 0.35
COOLDOWN_SECONDS = 1.50

# Reimplemented from the benchmark behavior, not copied source code.
# Values are deliberately conservative: a stable hold is required after the
# transition window before an input signal can be emitted.
CONTROLS = {
    "fist": ("mute_local", 1.80),
    "open_palm": ("stop", 0.90),
    "point_up": ("listen", 0.90),
    "point_right": ("menu_next", 0.90),
    "point_left": ("menu_prev", 0.90),
    "thumbs_up": ("select_suggestion", 1.00),
    "victory": ("ui_acknowledge", 0.90),
}


@dataclass
class _GestureState:
    gesture: str | None = None
    since: float | None = None
    last_seen: float | None = None
    last_emitted: float | None = None
    latched: bool = False


_LOCK = threading.RLock()
_STATES: dict[tuple[str, str], _GestureState] = {}


def _key(owner: str, device_id: str) -> tuple[str, str]:
    owner = str(owner).strip()
    device_id = str(device_id).strip()
    if not owner or not device_id or len(owner) > 200 or len(device_id) > 200:
        raise ValueError("Gesture sahibi ve cihaz kimliği gerekli.")
    return owner, device_id


def _clock(now: float | None) -> float:
    value = time.monotonic() if now is None else float(now)
    if not math.isfinite(value) or value < 0:
        raise ValueError("Gesture zamanı geçersiz.")
    return value


def sample(owner: str, device_id: str, gesture: str, *, now: float | None = None) -> dict | None:
    """Consume one normalized gesture sample and maybe emit an input signal.

    ``none`` means the hand/gesture was released and clears the latch. Unknown
    gesture labels fail closed. Time defaults to the server monotonic clock so
    a remote client cannot forge hold duration.
    """
    owner, device_id = _key(owner, device_id)
    gesture = str(gesture).strip().casefold()
    current = _clock(now)
    if gesture != "none" and gesture not in CONTROLS:
        raise ValueError("Gesture etiketi desteklenmiyor.")

    with _LOCK:
        state = _STATES.setdefault((owner, device_id), _GestureState())
        if state.last_seen is not None and current < state.last_seen:
            raise ValueError("Gesture zamanı geriye gidemez.")
        state.last_seen = current

        if gesture == "none":
            state.gesture = None
            state.since = None
            state.latched = False
            return None

        if state.gesture != gesture:
            state.gesture = gesture
            state.since = current
            state.latched = False
            return None

        if state.latched or state.since is None:
            return None

        intent, hold_seconds = CONTROLS[gesture]
        required = TRANSITION_IGNORE_SECONDS + hold_seconds
        elapsed = current - state.since
        if elapsed + 1e-9 < required:
            return None
        if state.last_emitted is not None and current - state.last_emitted + 1e-9 < COOLDOWN_SECONDS:
            return None

        state.last_emitted = current
        state.latched = True
        return {
            "owner": owner,
            "device_id": device_id,
            "gesture": gesture,
            "intent": intent,
            "source": "gesture_adapter",
            "held_seconds": round(elapsed, 3),
            "authority": "none",
            "permission_granted": False,
            "trusted_instruction": False,
            "retention": "ephemeral",
            "requires_policy": True,
        }


def _reset_for_tests() -> None:
    with _LOCK:
        _STATES.clear()
