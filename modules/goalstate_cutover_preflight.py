"""Read-only GoalState cutover preflight checker.

This module performs no migration. It never writes a file, never calls
CAS/create/compensate, never repairs a legacy record, never mutates a
GoalState snapshot and never calls a worker/model/provider or the network.
It only scans an owner directory on disk for legacy goal-job records and
their canonical GoalState sidecar, and returns a structured, deterministic
report answering "is a real cutover safe for this owner?".

See docs/architecture/GOALSTATE_CUTOVER_PREFLIGHT_V1.md for the contract.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from modules import goal_state, goal_state_compat

_LEGACY_FILE = re.compile(r'[a-f0-9]{16}\.json\Z')
_REQUIRED_LEGACY_FIELDS = frozenset({'id', 'owner', 'request', 'state', 'goals', 'steps', 'outputs'})

OK = 'OK'
INVALID_LEGACY_RECORD = 'INVALID_LEGACY_RECORD'
UNKNOWN_LEGACY_STATE = 'UNKNOWN_LEGACY_STATE'
MISSING_CANONICAL = 'MISSING_CANONICAL'
CANONICAL_CORRUPT = 'CANONICAL_CORRUPT'
IDENTITY_MISMATCH = 'IDENTITY_MISMATCH'
STATE_DIVERGENCE = 'STATE_DIVERGENCE'
TERMINAL_DIVERGENCE = 'TERMINAL_DIVERGENCE'

REASON_CODES = (
    OK,
    INVALID_LEGACY_RECORD,
    UNKNOWN_LEGACY_STATE,
    MISSING_CANONICAL,
    CANONICAL_CORRUPT,
    IDENTITY_MISMATCH,
    STATE_DIVERGENCE,
    TERMINAL_DIVERGENCE,
)

_TERMINAL = frozenset({'done', 'cancelled'})


class PreflightScanError(ValueError):
    """Safe, content-free error for an invalid root/path or unexpected I/O failure."""


def _row(job_id, reason_code, *, legacy_state=None, canonical_state=None):
    return {
        'job_id': job_id,
        'reason_code': reason_code,
        'legacy_state': legacy_state,
        'canonical_state': canonical_state,
    }


def _candidate_legacy_files(owner_dir: Path):
    try:
        entries = list(owner_dir.iterdir())
    except OSError:
        raise PreflightScanError('Preflight owner dizini okunamadı.') from None
    for entry in entries:
        try:
            if not entry.is_file():
                continue
        except OSError:
            continue
        if _LEGACY_FILE.fullmatch(entry.name):
            yield entry


def _parse_legacy(path: Path, owner_dir: Path):
    """Return a valid legacy job dict, or None if the record is not well-formed."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        value = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError, TypeError):
        return None
    if not isinstance(value, dict) or not _REQUIRED_LEGACY_FIELDS.issubset(value):
        return None
    job_id = value.get('id')
    expected_id = path.stem
    if job_id != expected_id:
        return None
    owner = value.get('owner')
    if not isinstance(owner, str) or not owner:
        return None
    if path.parent.name != owner or owner_dir.name != owner:
        return None
    if not isinstance(value.get('request'), str) or not value['request'].strip():
        return None
    return value


def _legacy_target_state(job: dict):
    return goal_state_compat._STATE_MAP.get(job.get('state'))


def _load_canonical(canonical_path: Path):
    """Return (state, None) on success, or (None, reason_code) on safe failure."""
    try:
        raw = canonical_path.read_bytes()
    except OSError:
        return None, CANONICAL_CORRUPT
    try:
        parsed = json.loads(raw.decode('utf-8'))
        state = goal_state.validate(parsed)
    except (UnicodeDecodeError, ValueError, TypeError):
        return None, CANONICAL_CORRUPT
    return state, None


def _classify(job: dict, owner_dir: Path, job_id: str) -> dict:
    target_state = _legacy_target_state(job)
    if target_state is None:
        # Unknown state text is untrusted legacy content; never echo it.
        return _row(job_id, UNKNOWN_LEGACY_STATE)

    canonical_path = owner_dir / (job_id + '.goalstate.json')
    if not canonical_path.exists():
        return _row(job_id, MISSING_CANONICAL, legacy_state=job['state'])

    canonical, corrupt_reason = _load_canonical(canonical_path)
    if corrupt_reason is not None:
        return _row(job_id, corrupt_reason, legacy_state=job['state'])

    if (
        canonical['owner'] != job['owner']
        or canonical['job_id'] != job['id']
        or canonical['goal'] != job['request'].strip()
        or canonical['execution_mode'] != 'agent'
    ):
        return _row(
            job_id,
            IDENTITY_MISMATCH,
            legacy_state=job['state'],
            canonical_state=canonical['state'],
        )

    canonical_state = canonical['state']
    if canonical_state == target_state:
        return _row(job_id, OK, legacy_state=job['state'], canonical_state=canonical_state)

    if canonical_state in _TERMINAL or target_state in _TERMINAL:
        return _row(
            job_id,
            TERMINAL_DIVERGENCE,
            legacy_state=job['state'],
            canonical_state=canonical_state,
        )

    return _row(
        job_id,
        STATE_DIVERGENCE,
        legacy_state=job['state'],
        canonical_state=canonical_state,
    )


def scan(owner_root) -> dict:
    """Read-only scan of one owner directory for legacy/canonical GoalState pairs.

    Rows are deterministic and sorted by job_id. The returned report deliberately
    omits owner paths, owner names, requests, blockers and raw snapshot content.
    """
    owner_dir = Path(owner_root)
    if not owner_dir.exists() or not owner_dir.is_dir():
        raise PreflightScanError('Preflight owner dizini geçersiz.')

    rows = []
    try:
        candidates = sorted(_candidate_legacy_files(owner_dir), key=lambda p: p.name)
    except PreflightScanError:
        raise
    except OSError:
        raise PreflightScanError('Preflight sırasında beklenmeyen I/O hatası.') from None

    for path in candidates:
        job_id = path.stem
        try:
            job = _parse_legacy(path, owner_dir)
        except OSError:
            job = None
        if job is None:
            rows.append(_row(job_id, INVALID_LEGACY_RECORD))
            continue
        try:
            rows.append(_classify(job, owner_dir, job_id))
        except OSError:
            rows.append(_row(job_id, INVALID_LEGACY_RECORD))

    rows.sort(key=lambda row: row['job_id'])
    counts = {code: 0 for code in REASON_CODES}
    for row in rows:
        counts[row['reason_code']] += 1

    return {
        'rows': rows,
        'counts': counts,
        'ok': all(row['reason_code'] == OK for row in rows),
    }
