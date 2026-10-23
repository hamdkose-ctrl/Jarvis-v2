"""Canonical JSON-only GoalState v1 snapshot.

This module defines state shape only. It does not persist, dispatch or mutate
runtime jobs. Global mutations belong to core_state_reducer.
"""
from __future__ import annotations

import copy
import json
import re

SCHEMA = 'goal_state.v1'
STATES = frozenset({'pending', 'running', 'waiting', 'paused', 'failed', 'done', 'cancelled'})
EXECUTION_MODES = frozenset({'fast', 'agent', 'durable'})
_TERMINAL = frozenset({'done', 'cancelled'})
_OWNER = re.compile(r'[\w-]{1,100}\Z')
_JOB_ID = re.compile(r'[a-zA-Z0-9_.-]{1,100}\Z')


def _json_only(value, message='GoalState JSON uyumlu değil.'):
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError(message) from None


def new(*, owner: str, job_id: str, goal: str, execution_mode: str = 'agent') -> dict:
    """Create an immutable-identity, version-zero GoalState snapshot."""
    if not isinstance(owner, str) or not _OWNER.fullmatch(owner):
        raise ValueError('GoalState sahibi geçersiz.')
    if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
        raise ValueError('GoalState job kimliği geçersiz.')
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError('GoalState hedefi boş olamaz.')
    if execution_mode not in EXECUTION_MODES:
        raise ValueError('GoalState execution_mode geçersiz.')
    state = {
        'schema': SCHEMA,
        'owner': owner,
        'job_id': job_id,
        'goal': goal.strip(),
        'execution_mode': execution_mode,
        'version': 0,
        'state': 'pending',
        'evidence': [],
        'blocker': None,
        'audit': [{
            'version': 0,
            'op': 'create',
            'state': 'pending',
            'reason_code': 'CREATED',
        }],
    }
    _json_only(state)
    return state


def validate(state: dict) -> dict:
    """Validate and return a defensive copy of one GoalState v1 snapshot."""
    if not isinstance(state, dict):
        raise ValueError('GoalState sözlük olmalı.')
    required = {
        'schema', 'owner', 'job_id', 'goal', 'execution_mode', 'version', 'state',
        'evidence', 'blocker', 'audit',
    }
    if set(state) != required:
        raise ValueError('GoalState şeması geçersiz.')
    if state.get('schema') != SCHEMA:
        raise ValueError('GoalState sürümü desteklenmiyor.')
    if not isinstance(state.get('owner'), str) or not _OWNER.fullmatch(state['owner']):
        raise ValueError('GoalState sahibi geçersiz.')
    if not isinstance(state.get('job_id'), str) or not _JOB_ID.fullmatch(state['job_id']):
        raise ValueError('GoalState job kimliği geçersiz.')
    if not isinstance(state.get('goal'), str) or not state['goal'].strip():
        raise ValueError('GoalState hedefi geçersiz.')
    if state.get('execution_mode') not in EXECUTION_MODES:
        raise ValueError('GoalState execution_mode geçersiz.')
    version = state.get('version')
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        raise ValueError('GoalState version geçersiz.')
    if state.get('state') not in STATES:
        raise ValueError('GoalState state geçersiz.')
    if not isinstance(state.get('evidence'), list):
        raise ValueError('GoalState evidence liste olmalı.')
    if state.get('blocker') is not None and not isinstance(state['blocker'], dict):
        raise ValueError('GoalState blocker geçersiz.')
    audit = state.get('audit')
    if not isinstance(audit, list) or len(audit) != version + 1:
        raise ValueError('GoalState audit/version tutarsız.')
    for index, row in enumerate(audit):
        if not isinstance(row, dict) or set(row) != {'version', 'op', 'state', 'reason_code'}:
            raise ValueError(f'GoalState audit[{index}] şeması geçersiz.')
        if row.get('version') != index or row.get('state') not in STATES:
            raise ValueError(f'GoalState audit[{index}] sürümü/state geçersiz.')
        if not isinstance(row.get('op'), str) or not row['op']:
            raise ValueError(f'GoalState audit[{index}] op geçersiz.')
        if not isinstance(row.get('reason_code'), str) or not row['reason_code']:
            raise ValueError(f'GoalState audit[{index}] reason_code geçersiz.')
    if audit[-1]['state'] != state['state']:
        raise ValueError('GoalState son audit state ile eşleşmiyor.')
    _json_only(state)
    return copy.deepcopy(state)


def terminal(state: dict) -> bool:
    return validate(state)['state'] in _TERMINAL
