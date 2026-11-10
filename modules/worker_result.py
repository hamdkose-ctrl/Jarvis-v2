"""Fail-closed WorkerResult v1 contract and fencing.

This is a pure boundary validator: it never dispatches a worker or mutates
GoalState.  A later reducer integration may translate an accepted result into a
structured proposal.
"""
from __future__ import annotations

import copy
import json
import re

SCHEMA = 'worker_result.v1'
PLAN_SCHEMA = 'worker_result.plan.v1'
_FENCE = ('owner', 'job_id', 'step_id', 'command_id', 'attempt',
          'expected_job_version', 'capability_id', 'capability_version',
          'input_digest')
_FIELDS = frozenset(('schema', 'status', 'evidence', *_FENCE))
PLAN_FENCE = ('plan_version', 'node_digest')
_HEX_SHA256 = re.compile(r'[0-9a-f]{64}\Z')


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


def _check_plan(row):
    if type(row.get('plan_version')) is not int or row['plan_version'] < 1:
        raise ValueError('WorkerResult plan_version geçersiz.')
    digest = row.get('node_digest')
    if not isinstance(digest, str) or not _HEX_SHA256.fullmatch(digest):
        raise ValueError('WorkerResult node_digest geçersiz.')


def validate(result: dict) -> dict:
    if not isinstance(result, dict):
        raise ValueError('WorkerResult şeması geçersiz.')
    fields = set(result)
    schema = result.get('schema')
    if not ((schema == SCHEMA and fields == _FIELDS)
            or (schema == PLAN_SCHEMA and fields == _FIELDS.union(PLAN_FENCE))):
        raise ValueError('WorkerResult şeması geçersiz.')
    if result.get('status') not in {'succeeded', 'failed'}:
        raise ValueError('WorkerResult durumu geçersiz.')
    if not isinstance(result.get('evidence'), list):
        raise ValueError('WorkerResult evidence geçersiz.')
    _check_fence(result)
    if schema == PLAN_SCHEMA:
        _check_plan(result)
    _json(result)
    return copy.deepcopy(result)


def accept(result: dict, expected: dict) -> dict:
    """Return a defensive result only when every immutable execution fence matches."""
    row = validate(result)
    if not isinstance(expected, dict):
        raise ValueError('Beklenen WorkerResult fence şeması geçersiz.')
    is_planned = row['schema'] == PLAN_SCHEMA
    required = set(_FENCE).union(PLAN_FENCE if is_planned else ())
    if set(expected) != required:
        raise ValueError('Beklenen WorkerResult fence şeması geçersiz.')
    _check_fence(expected)
    if is_planned:
        _check_plan(expected)
    for key in (*_FENCE, *(PLAN_FENCE if is_planned else ())):
        if row[key] != expected[key]:
            raise FenceError(f'WorkerResult fence uyuşmuyor: {key}.')
    return row
