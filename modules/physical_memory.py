"""Physical Object Memory: observation -> candidate -> confirmed durable object memory.

Model/camera observations are untrusted evidence. They can propose candidates but can
never grant authority, permission, or durable-memory status without explicit user
confirmation. Manual corrections win over later model scans.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import re

from modules.personalization import _LOCK as _PROFILE_LOCK

_OBJECTS = "physical_objects"
_CANDIDATES = "physical_object_candidates"
_MAX_OBJECTS = 300
_MAX_CANDIDATES = 60
_ID = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value, field: str, *, max_len: int = 500, required: bool = False) -> str:
    text = " ".join(str(value or "").split()).strip()
    if required and not text:
        raise ValueError(f"{field} gerekli.")
    if len(text) > max_len:
        raise ValueError(f"{field} çok uzun.")
    return text


def _object_id(value) -> str:
    text = _text(value, "object_id", max_len=120, required=True)
    if not _ID.fullmatch(text):
        raise ValueError("object_id geçersiz.")
    return text


def _confidence(value) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence geçersiz.") from exc
    if score < 0 or score > 1:
        raise ValueError("confidence 0 ile 1 arasında olmalı.")
    return round(score, 4)


def _rows(profile, key: str) -> list[dict]:
    rows = profile.data.get(key)
    if not isinstance(rows, list):
        rows = []
        profile.data[key] = rows
    return rows


def _find(rows: list[dict], object_id: str):
    return next((row for row in rows if isinstance(row, dict) and row.get("object_id") == object_id), None)


def _base_candidate(*, object_id, label, location, source_device, confidence, source, evidence_ref,
                    observed_at, evidence_text="") -> dict:
    when = _text(observed_at or _now(), "observed_at", max_len=80, required=True)
    score = _confidence(confidence)
    return {
        "object_id": _object_id(object_id),
        "label": _text(label, "label", max_len=240, required=True),
        "location": _text(location, "location", max_len=240),
        "source_device": _text(source_device, "source_device", max_len=120, required=True),
        "observed_at": when,
        "last_seen_at": when,
        "confidence": score,
        "source": _text(source, "source", max_len=80, required=True),
        "evidence_ref": _text(evidence_ref, "evidence_ref", max_len=300, required=True),
        "evidence_text": _text(evidence_text, "evidence_text", max_len=1000),
        "evidence_trust": "untrusted",
        "trusted_instruction": False,
        "permission_granted": False,
        "user_confirmed": False,
        "manually_corrected": False,
        "review_state": "needs_user_confirmation",
        "status": "candidate",
    }


def observe(profile, *, object_id: str, label: str, location: str = "", source_device: str,
            confidence: float, source: str, evidence_ref: str, observed_at: str = "",
            evidence_text: str = "") -> dict:
    """Record untrusted observation as candidate; never create durable memory by itself."""
    candidate = _base_candidate(object_id=object_id, label=label, location=location,
                                source_device=source_device, confidence=confidence, source=source,
                                evidence_ref=evidence_ref, observed_at=observed_at,
                                evidence_text=evidence_text)
    oid = candidate["object_id"]
    with _PROFILE_LOCK:
        objects = _rows(profile, _OBJECTS)
        existing = _find(objects, oid)
        if existing is not None:
            # Preserve identity and any user-corrected semantic fields. A later scan may
            # refresh provenance/last-seen, but never silently overwrite manual truth.
            existing["last_seen_at"] = candidate["observed_at"]
            existing["source_device"] = candidate["source_device"]
            existing["confidence"] = candidate["confidence"]
            existing["source"] = candidate["source"]
            existing["evidence_ref"] = candidate["evidence_ref"]
            existing["evidence_text"] = candidate["evidence_text"]
            existing["evidence_trust"] = "untrusted"
            existing["trusted_instruction"] = False
            existing["permission_granted"] = False
            existing["status"] = "confirmed"
            if not existing.get("manually_corrected"):
                existing["label"] = candidate["label"]
                existing["location"] = candidate["location"]
                existing["observed_at"] = candidate["observed_at"]
            profile.save()
            return deepcopy(existing)

        candidates = _rows(profile, _CANDIDATES)
        previous = _find(candidates, oid)
        if previous is not None:
            previous.update(candidate)
            row = previous
        else:
            candidates.append(candidate)
            if len(candidates) > _MAX_CANDIDATES:
                del candidates[:-_MAX_CANDIDATES]
            row = candidate
        profile.save()
        return deepcopy(row)


def confirm(profile, object_id: str) -> dict:
    """Explicit user confirmation promotes one candidate to durable object memory."""
    oid = _object_id(object_id)
    with _PROFILE_LOCK:
        candidates = _rows(profile, _CANDIDATES)
        candidate = _find(candidates, oid)
        if candidate is None:
            existing = _find(_rows(profile, _OBJECTS), oid)
            if existing is None:
                raise KeyError(oid)
            return deepcopy(existing)
        row = deepcopy(candidate)
        row.update({
            "user_confirmed": True,
            "review_state": "confirmed",
            "status": "confirmed",
            "trusted_instruction": False,
            "permission_granted": False,
        })
        objects = _rows(profile, _OBJECTS)
        old = _find(objects, oid)
        if old is None:
            objects.append(row)
        else:
            old.update(row)
            row = old
        candidates[:] = [x for x in candidates if not (isinstance(x, dict) and x.get("object_id") == oid)]
        if len(objects) > _MAX_OBJECTS:
            del objects[:-_MAX_OBJECTS]
        profile.save()
        return deepcopy(row)


def correct(profile, object_id: str, *, label: str | None = None, location: str | None = None) -> dict:
    """User correction is durable and cannot be overwritten by later model observations."""
    oid = _object_id(object_id)
    with _PROFILE_LOCK:
        row = _find(_rows(profile, _OBJECTS), oid)
        if row is None or not row.get("user_confirmed"):
            raise KeyError(oid)
        if label is not None:
            row["label"] = _text(label, "label", max_len=240, required=True)
        if location is not None:
            row["location"] = _text(location, "location", max_len=240)
        row["manually_corrected"] = True
        row["manual_corrected_at"] = _now()
        row["status"] = "confirmed"
        profile.save()
        return deepcopy(row)


def mark_not_seen(profile, *, source_device: str, seen_object_ids: list[str], observed_at: str = "") -> int:
    """Mark previously known objects as location-unknown; absence never deletes memory."""
    device = _text(source_device, "source_device", max_len=120, required=True)
    seen = {_object_id(x) for x in seen_object_ids}
    when = _text(observed_at or _now(), "observed_at", max_len=80, required=True)
    changed = 0
    with _PROFILE_LOCK:
        for row in _rows(profile, _OBJECTS):
            if not isinstance(row, dict) or row.get("source_device") != device or row.get("object_id") in seen:
                continue
            row["status"] = "location_unknown"
            row["not_seen_at"] = when
            changed += 1
        if changed:
            profile.save()
    return changed


def get(profile, object_id: str) -> dict | None:
    oid = _object_id(object_id)
    row = _find(_rows(profile, _OBJECTS), oid)
    return deepcopy(row) if row is not None else None


def confirmed(profile) -> list[dict]:
    return [deepcopy(x) for x in _rows(profile, _OBJECTS) if isinstance(x, dict) and x.get("user_confirmed")]


def context_items(profile) -> list[str]:
    """Return confirmed object-memory text only; caller still applies relevance gate."""
    out = []
    for row in confirmed(profile):
        label = _text(row.get("label"), "label", max_len=240)
        if not label:
            continue
        location = _text(row.get("location"), "location", max_len=240)
        status = row.get("status") or "confirmed"
        suffix = f"; son bilinen konum: {location}" if location else ""
        if status == "location_unknown":
            suffix += "; güncel konum doğrulanmadı"
        out.append(f"Fiziksel nesne: {label}{suffix}")
    return out
