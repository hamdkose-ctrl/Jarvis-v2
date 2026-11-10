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


def mark_worker_commit(root, ident, previous, version):
    """Remember only this thread's successful CAS, never a freshly loaded version."""
    commits = getattr(_LOCAL, 'worker_commits', {})
    key = str((Path(root) / ident).absolute())
    prior = commits.get(key)
    base = prior[0] if prior and prior[1] == previous else previous
    commits[key] = (base, version)
    _LOCAL.worker_commits = commits


def _verified_parallel_worker_advance(root, owner, ident, expected, commit):
    """Advance an owned projection token only over verified worker-only CAS.

    Never infer ownership from a newer version alone. The current thread must
    possess a mark left by its OWN successful WorkerResult commit. Every
    intervening version, including that commit, must be an accepted read-only
    result for the same canonical plan; a user edit, plan revision, lifecycle
    mutation or unrecognized evidence prevents version adoption.
    """
    if (not isinstance(owner, str) or not owner or type(expected) is not int
            or not isinstance(commit, tuple) or len(commit) != 2
            or type(commit[0]) is not int or type(commit[1]) is not int
            or not expected <= commit[0] < commit[1]):
        return None
    current = canonical(root, owner, ident)
    if (current is None or current.get('goal_plan') is None
            or current['version'] < commit[1]):
        return None
    delta = current['audit'][expected + 1:]
    if not delta or any(
        item['op'] != 'append_evidence'
        or item['reason_code'] != 'WORKER_RESULT_ACCEPTED'
        or item['state'] != current['state']
        for item in delta
    ):
        return None
    if len(current['evidence']) < len(delta):
        return None
    plan_version = current['goal_plan']['plan_version']
    if any(
        not isinstance(row, dict) or row.get('kind') != 'worker_result'
        or row.get('owner') != owner or row.get('job_id') != ident
        or row.get('plan_version') != plan_version
        for row in current['evidence'][-len(delta):]
    ):
        return None
    # The existing canonical DAG gate validates ALL current-plan worker rows:
    # owner, digest, manifest/version, command identity, attempt ordering and
    # accepted audit/evidence parity. This helper never grants dispatch.
    from modules import goal_plan_gate
    try:
        goal_plan_gate.ready_read_only_candidates(
            current, owner=owner, job_id=ident,
        )
    except goal_plan_gate.PlanFenceError:
        return None
    return current['version']


def own_worker_version(root, ident, expected, *, owner=None):
    """Consume only this thread's own Core-registered successful worker CAS."""
    key = str((Path(root) / ident).absolute())
    commits = getattr(_LOCAL, 'worker_commits', {})
    commit = commits.get(key)
    if commit is None:
        return expected
    if owner is not None:
        advanced = _verified_parallel_worker_advance(
            root, owner, ident, expected, commit,
        )
        if advanced is not None:
            commits.pop(key)
            return advanced
    # Preserve legacy/unplanned behavior; assert_fresh still rejects a newer
    # foreign canonical version or execution record. Never silently rebase it.
    if commit[0] == expected:
        commits.pop(key)
        return commit[1]
    return expected
