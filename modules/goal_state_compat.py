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


def project(job: dict) -> dict:
    state = goal_state.new(
        owner=job['owner'], job_id=job['id'], goal=job['request'],
        execution_mode=PROJECTION_EXECUTION_MODE,
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
