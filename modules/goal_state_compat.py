"""Compatibility projection from legacy goal_executor jobs to canonical GoalState."""
from __future__ import annotations

from pathlib import Path

from modules import core_state_reducer, goal_state, goal_state_store

# RFC Karar 1 (kabul edildi): legacy goal_executor şemasında fast/durable ayrımı
# hiç yok; canonical projection bu yüzden kalıcı olarak 'agent' üretir ve
# job['execution_mode'] alanını okumaz.
PROJECTION_EXECUTION_MODE = 'agent'


_STATE_MAP = {
    'running': 'running',
    'approval': 'waiting',
    'question': 'waiting',
    'review': 'paused',
    'paused': 'paused',
    'interrupted': 'paused',
    'blocked': 'paused',
    'failed': 'failed',
    'done': 'done',
    'cancelled': 'cancelled',
}


class ReconcilePolicyError(ValueError):
    reason_code = 'RECONCILE_POLICY_ERROR'

    def __init__(self, message: str):
        super().__init__(message)
        self.reason_code = type(self).reason_code


class IdentityMismatchError(ReconcilePolicyError):
    reason_code = 'IDENTITY_MISMATCH'


class OperatorApprovalRequired(ReconcilePolicyError):
    reason_code = 'OPERATOR_APPROVAL_REQUIRED'


class BackfillAlreadyExists(ReconcilePolicyError):
    reason_code = 'CANONICAL_ALREADY_EXISTS'


def _target(job: dict) -> str:
    value = _STATE_MAP.get(job.get('state'))
    if value is None:
        raise ValueError('Legacy job state GoalState ile eşlenemiyor.')
    return value


def _blocker(job: dict):
    state = job.get('state')
    text = job.get('blocker') or job.get('question')
    if not text:
        return None
    code = 'LEGACY_APPROVAL' if state == 'approval' else 'LEGACY_QUESTION' if state == 'question' else 'LEGACY_BLOCKED'
    return {'code': code, 'text': str(text)[:1200]}


def _assert_identity(current: dict, job: dict) -> None:
    expected = (
        current['owner'],
        current['job_id'],
        current['goal'],
    )
    actual = (
        job.get('owner'),
        job.get('id'),
        str(job.get('request', '')).strip(),
    )
    if actual != expected:
        raise IdentityMismatchError('Legacy/canonical GoalState identity mismatch.')


def project(job: dict) -> dict:
    # RFC Karar 2 flip point: a canonical record created now (no prior canonical
    # file for this job) is a newly-created job and is canonical-authority from
    # birth. A job that already had a canonical record before this field
    # existed keeps no 'authority' key and stays legacy-authority via
    # goal_state.authority()'s default; this function never touches it.
    state = goal_state.new(
        owner=job['owner'], job_id=job['id'], goal=job['request'],
        execution_mode=PROJECTION_EXECUTION_MODE,
        authority='canonical',
    )
    target = _target(job)
    if target != 'pending':
        state = core_state_reducer.apply(state, {
            'expected_version': state['version'], 'op': 'set_state',
            'state': target, 'reason_code': 'LEGACY_PROJECTED',
        })
    blocker = _blocker(job)
    if blocker and state['state'] not in {'done', 'cancelled'}:
        state = core_state_reducer.apply(state, {
            'expected_version': state['version'], 'op': 'set_blocker',
            'blocker': blocker, 'reason_code': 'LEGACY_BLOCKER_SYNCED',
        })
    return state


def reconcile(current: dict, job: dict) -> dict:
    """Compare one canonical snapshot with one legacy snapshot without choosing cutover timing.

    This function codifies RFC decisions 3 and 4 only.  It does not decide which
    side is write authority or when authority changes.
    """
    current = goal_state.validate(current)
    _assert_identity(current, job)
    target = _target(job)

    if goal_state.terminal(current):
        if current['state'] != target:
            return {
                'state': current,
                'changed': False,
                'decision': 'CANONICAL_TERMINAL_WINS',
                'reason_code': 'TERMINAL_DIVERGENCE',
            }
        return {
            'state': current,
            'changed': False,
            'decision': 'ALIGNED',
            'reason_code': 'ALIGNED',
        }

    state = current
    if state['state'] != target:
        proposal = {
            'expected_version': state['version'], 'op': 'set_state',
            'state': target, 'reason_code': 'LEGACY_STATE_SYNCED',
        }
        try:
            state = core_state_reducer.apply(state, proposal)
        except core_state_reducer.InvalidTransitionError:
            if state['state'] == 'running' or target == 'running':
                raise
            state = core_state_reducer.apply(state, {
                'expected_version': state['version'], 'op': 'set_state',
                'state': 'running', 'reason_code': 'LEGACY_RESUMED',
            })
            state = core_state_reducer.apply(state, {
                'expected_version': state['version'], 'op': 'set_state',
                'state': target, 'reason_code': 'LEGACY_STATE_SYNCED',
            })
    blocker = _blocker(job)
    if blocker is not None and state['blocker'] != blocker and not goal_state.terminal(state):
        state = core_state_reducer.apply(state, {
            'expected_version': state['version'], 'op': 'set_blocker',
            'blocker': blocker, 'reason_code': 'LEGACY_BLOCKER_SYNCED',
        })
    elif blocker is None and state['blocker'] is not None and not goal_state.terminal(state):
        state = core_state_reducer.apply(state, {
            'expected_version': state['version'], 'op': 'clear_blocker',
            'reason_code': 'LEGACY_BLOCKER_CLEARED',
        })

    changed = state['version'] != current['version']
    return {
        'state': state,
        'changed': changed,
        'decision': 'LEGACY_COMPAT_APPLIED' if changed else 'ALIGNED',
        'reason_code': state['audit'][-1]['reason_code'] if changed else 'ALIGNED',
    }


def advance(current: dict, job: dict) -> dict:
    current = goal_state.validate(current)
    target = _target(job)

    if goal_state.terminal(current):
        return current

    state = current
    if state['state'] != target:
        proposal = {
            'expected_version': state['version'], 'op': 'set_state',
            'state': target, 'reason_code': 'LEGACY_STATE_SYNCED',
        }
        try:
            state = core_state_reducer.apply(state, proposal)
        except core_state_reducer.InvalidTransitionError:
            if state['state'] == 'running' or target == 'running':
                raise
            state = core_state_reducer.apply(state, {
                'expected_version': state['version'], 'op': 'set_state',
                'state': 'running', 'reason_code': 'LEGACY_RESUMED',
            })
            state = core_state_reducer.apply(state, {
                'expected_version': state['version'], 'op': 'set_state',
                'state': target, 'reason_code': 'LEGACY_STATE_SYNCED',
            })
    blocker = _blocker(job)
    if blocker is not None and state['blocker'] != blocker and not goal_state.terminal(state):
        state = core_state_reducer.apply(state, {
            'expected_version': state['version'], 'op': 'set_blocker',
            'blocker': blocker, 'reason_code': 'LEGACY_BLOCKER_SYNCED',
        })
    elif blocker is None and state['blocker'] is not None and not goal_state.terminal(state):
        state = core_state_reducer.apply(state, {
            'expected_version': state['version'], 'op': 'clear_blocker',
            'reason_code': 'LEGACY_BLOCKER_CLEARED',
        })
    return state


def legacy_terminal_signal(job: dict, state: dict) -> dict | None:
    """Return the legacy job rewritten to canonical's terminal state, or None.

    RFC Karar 4a: canonical terminal always wins, and the legacy side must
    learn it.  When canonical is already done/cancelled but the legacy journal
    still shows another state, the legacy record is written with the canonical
    terminal state so goal_executor.latest()/is_open() treat the job as closed.

    A terminal state that canonical only copied from legacy (LEGACY_* reason)
    is not a canonical decision; legacy keeps owning that record, including
    its own "hedef devam" reopen path.
    """
    state = goal_state.validate(state)
    if not goal_state.terminal(state) or job.get('state') == state['state']:
        return None
    if state['audit'][-1]['reason_code'].startswith('LEGACY_'):
        return None
    signalled = dict(job)
    signalled['state'] = state['state']
    signalled.pop('blocker', None)
    signalled.pop('question', None)
    return signalled


def operator_backfill_missing_canonical_once(
    job: dict,
    path,
    *,
    operator_approved: bool = False,
) -> dict:
    """Explicit, one-shot operator API for RFC decision 3a.

    Compatibility sync never calls this function automatically.  The caller must
    explicitly approve the action and the canonical path must still be absent.
    """
    if not operator_approved:
        raise OperatorApprovalRequired('Canonical GoalState backfill requires operator approval.')
    path = Path(path)
    if path.exists():
        raise BackfillAlreadyExists('Canonical GoalState already exists; backfill refused.')
    return goal_state_store.create(path, project(job))


def sync(job: dict, path) -> dict:
    path = Path(path)
    if not path.exists():
        state = project(job)
        return goal_state_store.create(path, state)
    current = goal_state_store.load(path)
    next_state = advance(current, job)
    if next_state['version'] == current['version']:
        return current
    return goal_state_store.compare_and_swap(
        path, expected_version=current['version'], next_state=next_state
    )
