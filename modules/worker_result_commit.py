"""Persist one already-accepted WorkerResult as canonical GoalState evidence.

This adapter is deliberately narrow: it does not execute workers and it does not
change the legacy job state.  It appends evidence through Core State Reducer and
persists with GoalState CAS before the normal legacy save/sync continues.
"""
from __future__ import annotations

import copy

from modules import core_state_reducer, goal_state_store, worker_result


_REASON = 'WORKER_RESULT_ACCEPTED'


def _path(accepted: dict):
    from modules import goal_executor
    return goal_executor._root(accepted['owner']) / (accepted['job_id'] + '.goalstate.json')


def _evidence(accepted: dict) -> dict:
    row = worker_result.validate(accepted)
    return {
        'kind': 'worker_result',
        'owner': row['owner'],
        'job_id': row['job_id'],
        'step_id': row['step_id'],
        'command_id': row['command_id'],
        'attempt': row['attempt'],
        'expected_job_version': row['expected_job_version'],
        'capability_id': row['capability_id'],
        'capability_version': row['capability_version'],
        'input_digest': row['input_digest'],
        'status': row['status'],
        'evidence': copy.deepcopy(row['evidence']),
    }


def commit(accepted: dict) -> dict:
    """Append accepted WorkerResult evidence exactly once using reducer + CAS."""
    evidence = _evidence(accepted)
    path = _path(accepted)
    current = goal_state_store.load(path)
    if current['owner'] != accepted['owner'] or current['job_id'] != accepted['job_id']:
        raise ValueError('WorkerResult canonical GoalState kimliğiyle eşleşmiyor.')

    matches = [
        row for row in current['evidence']
        if isinstance(row, dict)
        and row.get('kind') == 'worker_result'
        and row.get('command_id') == evidence['command_id']
    ]
    if matches:
        if len(matches) != 1 or matches[0] != evidence:
            raise goal_state_store.PersistedStateConflict(
                'WorkerResult command_id farklı evidence ile daha önce kaydedilmiş.'
            )
        return current

    if current['version'] != accepted['expected_job_version']:
        raise goal_state_store.PersistedStateConflict(
            'WorkerResult stale GoalState sürümüne ait; evidence yazılmadı.'
        )

    next_state = core_state_reducer.apply(current, {
        'expected_version': current['version'],
        'op': 'append_evidence',
        'evidence': evidence,
        'reason_code': _REASON,
    })
    return goal_state_store.compare_and_swap(
        path, expected_version=current['version'], next_state=next_state
    )
