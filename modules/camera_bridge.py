"""Fail-closed camera device bridge.

This module models the server-side observation boundary for remote camera
clients. It does not create WebRTC peers itself; browser/device transport code
feeds authenticated frames into this boundary. Frames are kept in memory only.
"""
from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field

MAX_FRAME_BYTES = 2 * 1024 * 1024
MAX_VIEWERS = 3
_ALLOWED_TRANSPORTS = {"webrtc", "jpeg"}


@dataclass
class _DeviceState:
    local_enabled: bool = False
    stopped_locally: bool = True
    viewers: set[str] = field(default_factory=set)
    frame: bytes | None = None
    transport: str | None = None
    width: int | None = None
    height: int | None = None
    received_at: float | None = None
    sha256: str | None = None


_LOCK = threading.RLock()
_STATES: dict[tuple[str, str], _DeviceState] = {}


def _key(owner: str, device_id: str) -> tuple[str, str]:
    owner = str(owner).strip()
    device_id = str(device_id).strip()
    if not owner or not device_id or len(owner) > 200 or len(device_id) > 200:
        raise ValueError("Kamera sahibi ve cihaz kimliği gerekli.")
    return owner, device_id


def _state(owner: str, device_id: str) -> _DeviceState:
    key = _key(owner, device_id)
    return _STATES.setdefault(key, _DeviceState())


def local_enable(owner: str, device_id: str) -> dict:
    """Local device action: explicitly enable this camera source."""
    with _LOCK:
        state = _state(owner, device_id)
        state.local_enabled = True
        state.stopped_locally = False
        return status(owner, device_id)


def local_disable(owner: str, device_id: str) -> dict:
    """Local device action wins: remote callers cannot reopen this source."""
    with _LOCK:
        state = _state(owner, device_id)
        state.local_enabled = False
        state.stopped_locally = True
        state.viewers.clear()
        state.frame = None
        state.transport = None
        state.width = None
        state.height = None
        state.received_at = None
        state.sha256 = None
        return status(owner, device_id)


def viewer_join(owner: str, device_id: str, viewer_id: str) -> int:
    viewer_id = str(viewer_id).strip()
    if not viewer_id or len(viewer_id) > 200:
        raise ValueError("İzleyici kimliği gerekli.")
    with _LOCK:
        state = _state(owner, device_id)
        if not state.local_enabled or state.stopped_locally:
            raise PermissionError("Kamera yerel cihazdan açılmadan uzak izleyici bağlanamaz.")
        if viewer_id not in state.viewers and len(state.viewers) >= MAX_VIEWERS:
            raise RuntimeError("Kamera için en fazla 3 eşzamanlı izleyici desteklenir.")
        state.viewers.add(viewer_id)
        return len(state.viewers)


def viewer_leave(owner: str, device_id: str, viewer_id: str) -> int:
    with _LOCK:
        state = _state(owner, device_id)
        state.viewers.discard(str(viewer_id).strip())
        return len(state.viewers)


def submit_frame(
    owner: str,
    device_id: str,
    frame: bytes,
    *,
    transport: str,
    width: int,
    height: int,
    now: float | None = None,
) -> dict:
    """Accept one authenticated camera frame as ephemeral observation evidence."""
    if transport not in _ALLOWED_TRANSPORTS:
        raise ValueError("Kamera transportu yalnız webrtc veya jpeg olabilir.")
    if not isinstance(frame, (bytes, bytearray)) or not frame:
        raise ValueError("Kamera karesi boş olamaz.")
    if len(frame) > MAX_FRAME_BYTES:
        raise ValueError("Kamera karesi boyut sınırını aşıyor.")
    if type(width) is not int or type(height) is not int or not 1 <= width <= 4096 or not 1 <= height <= 4096:
        raise ValueError("Kamera kare boyutu geçersiz.")
    with _LOCK:
        state = _state(owner, device_id)
        if not state.local_enabled or state.stopped_locally:
            raise PermissionError("Kamera yerel cihazdan kapalı; uzaktan açılamaz.")
        raw = bytes(frame)
        received_at = time.time() if now is None else float(now)
        state.frame = raw
        state.transport = transport
        state.width = width
        state.height = height
        state.received_at = received_at
        state.sha256 = hashlib.sha256(raw).hexdigest()
        return _observation(owner, device_id, state)


def _observation(owner: str, device_id: str, state: _DeviceState) -> dict:
    return {
        "owner": str(owner).strip(),
        "device_id": str(device_id).strip(),
        "source": "camera_bridge",
        "transport": state.transport,
        "width": state.width,
        "height": state.height,
        "received_at": state.received_at,
        "sha256": state.sha256,
        "authority": "none",
        "permission_granted": False,
        "trusted_instruction": False,
        "retention": "ephemeral",
    }


def latest(owner: str, device_id: str, *, max_age: float = 5.0, now: float | None = None) -> dict | None:
    if max_age <= 0:
        raise ValueError("Kamera tazelik sınırı pozitif olmalı.")
    with _LOCK:
        state = _state(owner, device_id)
        if not state.local_enabled or state.stopped_locally or state.frame is None or state.received_at is None:
            return None
        current = time.time() if now is None else float(now)
        if current - state.received_at > max_age:
            return None
        return _observation(owner, device_id, state)


def frame_bytes(owner: str, device_id: str, *, max_age: float = 5.0, now: float | None = None) -> bytes | None:
    with _LOCK:
        observation = latest(owner, device_id, max_age=max_age, now=now)
        if observation is None:
            return None
        return bytes(_state(owner, device_id).frame or b"") or None


def status(owner: str, device_id: str) -> dict:
    with _LOCK:
        state = _state(owner, device_id)
        return {
            "owner": str(owner).strip(),
            "device_id": str(device_id).strip(),
            "local_enabled": state.local_enabled,
            "stopped_locally": state.stopped_locally,
            "viewers": len(state.viewers),
            "has_frame": state.frame is not None,
            "authority": "none",
            "permission_granted": False,
        }


def _reset_for_tests() -> None:
    with _LOCK:
        _STATES.clear()
