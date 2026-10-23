"""Immutable runtime-event freshness and dedup boundary.

Runtime events are not WorkerResults and cannot mutate GoalState. Reducer
integration remains separate; this module admits one fresh event for a matching
subscription. PersistentSeen makes dedup restart-safe without changing accept().
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import release_guard

SCHEMA = 'runtime_event.v1'
_FIELDS = frozenset({'schema', 'event_id', 'source_event_key', 'source_generation',
                     'subject_version', 'occurred_at', 'kind', 'payload'})
_SEEN_SCHEMA = 'runtime_event_seen.v1'


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


def _load_seen(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError('Runtime Event dedup kalıcı kaydı bozuk.') from None
    if not isinstance(payload, dict) or set(payload) != {'schema', 'event_ids'} or payload.get('schema') != _SEEN_SCHEMA:
        raise ValueError('Runtime Event dedup kalıcı kayıt şeması geçersiz.')
    values = payload['event_ids']
    if not isinstance(values, list) or any(not _valid_text(value) for value in values) or len(values) != len(set(values)):
        raise ValueError('Runtime Event dedup kalıcı kayıt içeriği geçersiz.')
    return set(values)


def _persist_seen(path: Path, values: set[str]) -> None:
    if not isinstance(values, set) or any(not _valid_text(value) for value in values):
        raise ValueError('Runtime Event dedup kalıcı kayıt içeriği geçersiz.')
    payload = {'schema': _SEEN_SCHEMA, 'event_ids': sorted(values)}
    path.parent.mkdir(parents=True, exist_ok=True)
    release_guard.atomic(path, json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8'))


class PersistentSeen(set):
    """Set-compatible dedup ledger whose add() is atomic and restart-safe."""
    def __init__(self, path):
        self.path = Path(path)
        super().__init__(_load_seen(self.path))

    def add(self, value):
        if not _valid_text(value):
            raise ValueError('Runtime Event dedup kimliği geçersiz.')
        if value in self:
            return
        next_values = set(self)
        next_values.add(value)
        _persist_seen(self.path, next_values)
        super().add(value)


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
