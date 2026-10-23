"""Compatibility projection from legacy goal_executor jobs to canonical GoalState."""
from __future__ import annotations

from pathlib import Path

from modules import core_state_reducer, goal_state, goal_state_store, worker_result


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


def _worker_evidence(job: dict):
    rows = []
    outputs = job.get('outputs', {})
    if not isinstance(outputs, dict):
        return rows
    for output in outputs.values():
        if not isinstance(output, dict) or '_worker_result' not in output:
            continue
        envelope = worker_result.validate(output['_worker_result'])
        rows.append({
            'kind': 'worker_result',
            'command_id': envelope['command_id'],
            'step_id': envelope['step_id'],
            'attempt': envelope['attempt'],
            'status': envelope['status'],
            'capability_id': envelope['capability_id'],
            'capability_version': envelope['capability_version'],
            'input_digest': envelope['input_digest'],
            'expected_job_version': envelope['expected_job_version'],
        })
    return rows


def _append_worker_evidence(state: dict, job: dict) -> dict:
    existing = {(row.get('kind'), row.get('command_id')) for row in state['evidence'] if isinstance(row, dict)}
    for evidence in _worker_evidence(job):
        key = (evidence['kind'], evidence['command_id'])
        if key in existing:
            continue
        state = core_state_reducer.apply(state, {
            'expected_version': state['version'],
            'op': 'append_evidence',
            'evidence': evidence,
            'reason_code': 'WORKER_RESULT_ACCEPTED',
        })
        existing.add(key)
    return state


def project(job: dict) -> dict:
    state = goal_state.new(
        owner=job['owner'], job_id=job['id'], goal=job['request'], execution_mode='agent'
    )
    state = _append_worker_evidence(state, job)
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
    state = _append_worker_evidence(current, job)
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
