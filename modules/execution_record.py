"""ExecutionRecord: goal executor execution details beside canonical GoalState.

Canonical GoalState (``<id>.goalstate.json``) carries only lifecycle authority.
The executor's working payload (goals, steps, outputs, approval, feedback and
its own step/job progress) lives in ``<id>.execution.json``. The save hook
writes this record for every goal job; the legacy ``<id>.json`` journal is
still written in the same transaction only for legacy-authority (pre-flip or
backfilled) jobs. Readers prefer this record and fall back to the legacy
journal only for jobs saved before the record existed.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

SCHEMA = 'jarvis.execution_record.v1'
SUFFIX = '.execution.json'
MAX_BYTES = 16_000_000
REQUIRED = frozenset({'id', 'owner', 'request', 'state', 'goals', 'steps', 'outputs'})
# Windows atomic os.replace can briefly deny a concurrent reader's open.
# Retry only this OS sharing/access error, never invalid or untrusted bytes.
_WINDOWS = os.name == 'nt'
_READ_RETRY_DELAYS = (0.0, 0.01, 0.02, 0.04, 0.08)
_JOB_ID = re.compile(r'[a-f0-9]{16}')


def path_for(root, job_id: str) -> Path:
    if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
        raise ValueError('Hedef kimliği geçersiz.')
    return Path(root) / (job_id + SUFFIX)


def _check_job(job, owner: str, job_id: str, *, complete: bool = True) -> dict:
    if not isinstance(job, dict) or (complete and not REQUIRED.issubset(job)):
        raise ValueError('Hedef yürütme kaydı geçersiz.')
    if job.get('owner') != owner or job.get('id') != job_id:
        raise PermissionError('Hedef kaydı kullanıcıyla eşleşmiyor.')
    return job


def encode(job: dict) -> bytes:
    job_id = job.get('id') if isinstance(job, dict) else None
    owner = job.get('owner') if isinstance(job, dict) else None
    path_for('.', job_id)
    if not isinstance(owner, str) or not owner:
        raise ValueError('Hedef sahibi geçersiz.')
    _check_job(job, owner, job_id)
    return json.dumps({'schema': SCHEMA, 'job': job}, ensure_ascii=False).encode('utf-8')


def _read(path: Path):
    # On Windows a reader can briefly lose an open race with the existing
    # atomic ExecutionRecord replacement. Bound that transient window to
    # 150 ms; persistent permission denial still raises the original error.
    # Recheck type, symlink and size on every attempt. JSON/schema/owner
    # errors are never retried or treated as a successful snapshot.
    for delay in _READ_RETRY_DELAYS:
        if delay:
            time.sleep(delay)
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
                raise ValueError('Hedef yürütme kaydı geçersiz.')
            return json.loads(path.read_text(encoding='utf-8'))
        except PermissionError:
            if not _WINDOWS or delay == _READ_RETRY_DELAYS[-1]:
                raise
    raise AssertionError('ExecutionRecord read retry exhausted unexpectedly.')


def load(root, owner: str, job_id: str) -> dict:
    """Return the job's execution payload; legacy journal is the fallback."""
    record = path_for(root, job_id)
    if record.exists() or record.is_symlink():
        value = _read(record)
        if not isinstance(value, dict) or value.get('schema') != SCHEMA:
            raise ValueError('Hedef yürütme kaydı geçersiz.')
        return _check_job(value.get('job'), owner, job_id)
    legacy = Path(root) / (job_id + '.json')
    if not legacy.exists() and not legacy.is_symlink():
        raise FileNotFoundError(legacy)
    # Legacy journals were never schema-checked on read; keep that contract.
    return _check_job(_read(legacy), owner, job_id, complete=False)
