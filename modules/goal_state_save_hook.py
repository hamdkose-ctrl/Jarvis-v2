"""Narrow compatibility hook for legacy goal_executor atomic saves.

The legacy executor still owns its JSON journal during migration. This hook
recognizes only legacy goal-job records and synchronizes canonical GoalState
before the legacy atomic write. The same payload is written to the job's
ExecutionRecord (``modules/execution_record.py``) before the legacy journal, so
readers can move off the legacy file. A job whose canonical GoalState is
canonical-authority (RFC Karar 2: born after the flip) no longer gets a legacy
journal write; only legacy-authority jobs (pre-flip or backfilled) keep it.
When canonical is already terminal, the ExecutionRecord and, for a
legacy-authority job, the legacy record are written with that terminal state so
the legacy side learns it. Canonical writes and unrelated JSON writes are left
untouched.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import release_guard
from modules.diagnostics import record_failure as _record_failure

_JOB_FILE = re.compile(r'([a-f0-9]{16})\.json\Z')
_REQUIRED = frozenset({'id', 'owner', 'request', 'state', 'goals', 'steps', 'outputs'})
_ORIGINAL_ATOMIC = release_guard.atomic
_INSTALLED = False


def _legacy_job(path: Path, data) -> dict | None:
    match = _JOB_FILE.fullmatch(path.name)
    if not match or not isinstance(data, (bytes, bytearray)):
        return None
    try:
        value = json.loads(bytes(data).decode('utf-8'))
    except (UnicodeDecodeError, ValueError, TypeError):
        return None
    if not isinstance(value, dict) or not _REQUIRED.issubset(value):
        return None
    if value.get('id') != match.group(1):
        return None
    if not isinstance(value.get('owner'), str) or not value['owner']:
        return None
    # Goal executor journals are namespaced by owner.  A merely legacy-shaped
    # JSON payload in another owner's directory is not an authority to project
    # or advance canonical GoalState.
    if path.parent.name != value['owner']:
        return None
    return value


def _atomic(path, data):
    path = Path(path)
    job = _legacy_job(path, data)
    if job is None:
        return _ORIGINAL_ATOMIC(path, data)

    from modules import goal_job_control
    with goal_job_control.locked(path.parent, job['id']):
        return _atomic_job(path, data, job)


def _atomic_job(path, data, job):
    from modules import execution_record, goal_state, goal_state_compat, goal_job_control

    canonical = path.with_name(job['id'] + '.goalstate.json')
    record = execution_record.path_for(path.parent, job['id'])
    before = canonical.read_bytes() if canonical.exists() else None
    record_before = record.read_bytes() if record.exists() else None
    expected = job.pop('_goal_version_fence', None)
    if expected is not None:
        data = json.dumps(job, ensure_ascii=False).encode('utf-8')
    try:
        synced = (goal_state_compat.sync(job, canonical, expected_version=expected)
                  if expected is not None else goal_state_compat.sync(job, canonical))
    except Exception:
        _record_failure('modules/goal_state_save_hook.py:_atomic:canonical_sync')
        raise
    signalled = goal_state_compat.legacy_terminal_signal(job, synced)
    if signalled is not None:
        job = signalled
        data = json.dumps(signalled, ensure_ascii=False).encode('utf-8')
    try:
        _ORIGINAL_ATOMIC(record, execution_record.encode(job))
    except Exception as record_error:
        _record_failure('modules/goal_state_save_hook.py:_atomic:execution_record_write')
        _rollback(canonical, synced, before)
        raise record_error
    if goal_state.authority(synced) == 'canonical':
        # Canonical-authority job: ExecutionRecord is the only journal.
        goal_job_control.mark_saved(path.parent, job['id'], synced['version'])
        return None
    try:
        result = _ORIGINAL_ATOMIC(path, data)
        goal_job_control.mark_saved(path.parent, job['id'], synced['version'])
        return result
    except Exception as legacy_error:
        _record_failure('modules/goal_state_save_hook.py:_atomic:legacy_write')
        _rollback(canonical, synced, before, record=record, record_before=record_before)
        raise legacy_error


def _rollback(canonical, synced, before, *, record=None, record_before=None):
    from modules import goal_state_store

    try:
        if record is not None:
            if record_before is None:
                record.unlink(missing_ok=True)
            else:
                _ORIGINAL_ATOMIC(record, record_before)
        goal_state_store.compensate(
            canonical, expected_state=synced, previous_bytes=before,
        )
    except Exception as compensation_error:
        _record_failure('modules/goal_state_save_hook.py:_atomic:compensate')
        raise RuntimeError(
            'Legacy goal kaydı yazılamadı ve canonical GoalState geri alınamadı.'
        ) from compensation_error


def install():
    global _INSTALLED
    if _INSTALLED:
        return
    release_guard.atomic = _atomic
    _INSTALLED = True
