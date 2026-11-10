"""Short job-file critical sections and optimistic execution snapshots.

Uses the existing storage lock primitive on a separate control lock, never on
the canonical CAS lock itself. No lock is held for model/tool execution.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import threading

from modules import execution_record, goal_state_store

_LOCK = threading.Lock()
_LOCKS = {}
_LOCAL = threading.local()
_TRANSIENT = frozenset({'_execution_snapshot', '_canonical_version', '_goal_version_fence'})


def persistent(job):
    return {key: value for key, value in job.items() if key not in _TRANSIENT}


def fingerprint(job):
    return hashlib.sha256(json.dumps(persistent(job), sort_keys=True,
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


@contextmanager
def locked(root, ident):
    root = Path(root)
    execution_record.path_for(root, ident)  # existing closed identity validation
    key = str((root / (ident + '.control')).absolute())
    with _LOCK:
        mutex = _LOCKS.setdefault(key, threading.RLock())
    with mutex:
        held = getattr(_LOCAL, 'held', set())
        if key in held:
            yield
            return
        with goal_state_store._exclusive(Path(key)):
            _LOCAL.held = held | {key}
            try:
                yield
            finally:
                _LOCAL.held = held


def canonical(root, owner, ident):
    path = Path(root) / (ident + '.goalstate.json')
    if not path.exists():
        return None
    state = goal_state_store.load(path)
    if state['owner'] != owner or state['job_id'] != ident:
        raise PermissionError('Canonical hedef kimliği eşleşmiyor.')
    return state


def capture(root, job):
    """Attach only in-memory version tokens to a freshly loaded execution job."""
    state = canonical(root, job['owner'], job['id'])
    job['_execution_snapshot'] = fingerprint(job)
    job['_canonical_version'] = state['version'] if state else None
    return state


def assert_fresh(root, job):
    try:
        current = execution_record.load(root, job['owner'], job['id'])
    except FileNotFoundError:
        current = None
    if '_execution_snapshot' in job:
        if current is None or fingerprint(current) != job['_execution_snapshot']:
            raise ValueError('Hedef yürütme kaydı değişti; eski değişiklik uygulanmadı.')
    state = canonical(root, job['owner'], job['id'])
    if '_canonical_version' in job and (state['version'] if state else None) != job['_canonical_version']:
        raise ValueError('Hedef sürümü değişti; eski değişiklik uygulanmadı.')
    return state


def mark_saved(root, ident, version):
    versions = getattr(_LOCAL, 'versions', {})
    versions[str((Path(root) / ident).absolute())] = version
    _LOCAL.versions = versions


def saved_version(root, ident):
    return getattr(_LOCAL, 'versions', {}).get(str((Path(root) / ident).absolute()))
