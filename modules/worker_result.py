"""Fail-closed WorkerResult v1 contract and fencing.

This is a pure boundary validator: it never dispatches a worker or mutates
GoalState.  A later reducer integration may translate an accepted result into a
structured proposal.
"""
from __future__ import annotations

import copy
import json

SCHEMA = 'worker_result.v1'
_FENCE = ('owner', 'job_id', 'step_id', 'command_id', 'attempt',
          'expected_job_version', 'capability_id', 'capability_version',
          'input_digest')
_FIELDS = frozenset(('schema', 'status', 'evidence', *_FENCE))


class FenceError(ValueError):
    """A result belongs to another/stale execution fence."""


def _json(value):
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError('WorkerResult JSON uyumlu olmalı.') from None


def _check_fence(row):
    for key in _FENCE:
        value = row.get(key)
        if key in ('attempt', 'expected_job_version'):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f'WorkerResult {key} geçersiz.')
        elif not isinstance(value, str) or not value:
            raise ValueError(f'WorkerResult {key} geçersiz.')


def validate(result: dict) -> dict:
    if not isinstance(result, dict) or set(result) != _FIELDS:
        raise ValueError('WorkerResult şeması geçersiz.')
    if result.get('schema') != SCHEMA or result.get('status') not in {'succeeded', 'failed'}:
        raise ValueError('WorkerResult sürümü veya durumu geçersiz.')
    if not isinstance(result.get('evidence'), list):
        raise ValueError('WorkerResult evidence geçersiz.')
    _check_fence(result); _json(result)
    return copy.deepcopy(result)


def accept(result: dict, expected: dict) -> dict:
    """Return a defensive result only when every immutable execution fence matches."""
    row = validate(result)
    if not isinstance(expected, dict) or set(expected) != set(_FENCE):
        raise ValueError('Beklenen WorkerResult fence şeması geçersiz.')
    _check_fence(expected)
    for key in _FENCE:
        if row[key] != expected[key]:
            raise FenceError(f'WorkerResult fence uyuşmuyor: {key}.')
    return row
