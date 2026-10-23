"""Immutable runtime-event freshness and dedup boundary.

Runtime events are not WorkerResults and cannot mutate GoalState.  Reducer
integration is deliberately deferred; this module only admits one fresh event
for a matching subscription into a caller-owned dedup ledger.
"""
from __future__ import annotations

import copy
import json

SCHEMA = 'runtime_event.v1'
_FIELDS = frozenset({'schema', 'event_id', 'source_event_key', 'source_generation',
                     'subject_version', 'occurred_at', 'kind', 'payload'})


class StaleEventError(ValueError): pass
class DuplicateEventError(ValueError): pass


def _valid_text(value):
    return isinstance(value, str) and bool(value)


def validate(event: dict) -> dict:
    if not isinstance(event, dict) or set(event) != _FIELDS or event.get('schema') != SCHEMA:
        raise ValueError('Runtime Event şeması geçersiz.')
    if not all(_valid_text(event.get(key)) for key in ('event_id', 'source_event_key', 'kind')):
        raise ValueError('Runtime Event kimliği geçersiz.')
    if not all(isinstance(event.get(key), int) and not isinstance(event[key], bool) and event[key] >= 0
               for key in ('source_generation', 'subject_version')):
        raise ValueError('Runtime Event sürümü geçersiz.')
    if not isinstance(event.get('occurred_at'), (int, float)) or isinstance(event['occurred_at'], bool):
        raise ValueError('Runtime Event zamanı geçersiz.')
    try: json.dumps(event, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError): raise ValueError('Runtime Event JSON uyumlu olmalı.') from None
    return copy.deepcopy(event)


def accept(event: dict, subscription: dict, seen_event_ids: set) -> dict:
    """Accept one fresh immutable event once; no state/proposal operation occurs."""
    row = validate(event)
    required = {'source_event_key', 'source_generation', 'subject_version', 'resume_token', 'fresh_after'}
    if not isinstance(subscription, dict) or set(subscription) != required or not _valid_text(subscription['resume_token']):
        raise ValueError('Runtime Event aboneliği geçersiz.')
    if not isinstance(seen_event_ids, set): raise ValueError('Runtime Event dedup kaydı geçersiz.')
    if row['event_id'] in seen_event_ids: raise DuplicateEventError('Runtime Event daha önce işlendi.')
    if (row['source_event_key'] != subscription['source_event_key'] or
        row['source_generation'] != subscription['source_generation'] or
        row['subject_version'] != subscription['subject_version'] or
        row['occurred_at'] < subscription['fresh_after']):
        raise StaleEventError('Runtime Event bayat veya yabancı.')
    seen_event_ids.add(row['event_id'])
    return row
