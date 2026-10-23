"""Commit accepted RuntimeEvent evidence through the canonical GoalState reducer/CAS path.

RuntimeEvent freshness/dedup remains separate from GoalState policy.  This bridge
never changes global state by event kind; it only appends immutable accepted-event
evidence.  The persistent seen ledger advances only after a successful CAS.  If
seen persistence fails after CAS, a retry recognizes the existing evidence and
heals the ledger without a second version bump.
"""
from __future__ import annotations

import copy

from modules import core_state_reducer, goal_state_store, runtime_event


_REASON = 'RUNTIME_EVENT_ACCEPTED'


def _expected_version(value) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError('Runtime Event expected_job_version geçersiz.')
    return value


def _evidence(event: dict, subscription: dict) -> dict:
    return {
        'kind': 'runtime_event',
        'event_id': event['event_id'],
        'source_event_key': event['source_event_key'],
        'source_generation': event['source_generation'],
        'subject_version': event['subject_version'],
        'occurred_at': event['occurred_at'],
        'event_kind': event['kind'],
        'payload': copy.deepcopy(event['payload']),
        'resume_token': subscription['resume_token'],
    }


def _existing(state: dict, event_id: str):
    matches = [
        row for row in state['evidence']
        if isinstance(row, dict) and row.get('kind') == 'runtime_event' and row.get('event_id') == event_id
    ]
    if len(matches) > 1:
        raise ValueError('Aynı Runtime Event canonical evidence içinde birden fazla kez kayıtlı.')
    return matches[0] if matches else None


def commit(path, event: dict, subscription: dict, seen_event_ids: set, *, expected_job_version: int) -> dict:
    """Validate freshness, append event evidence by reducer/CAS, then persist dedup.

    `subject_version` belongs to the event subscription freshness contract and is
    deliberately not treated as the GoalState CAS version.  The caller supplies
    `expected_job_version` separately so the two version domains cannot be
    accidentally conflated.
    """
    expected_job_version = _expected_version(expected_job_version)
    if not isinstance(seen_event_ids, set):
        raise ValueError('Runtime Event dedup kaydı geçersiz.')

    # Validate schema + subscription freshness without consuming the real ledger.
    accepted = runtime_event.accept(event, subscription, set())
    evidence = _evidence(accepted, subscription)
    current = goal_state_store.load(path)

    existing = _existing(current, accepted['event_id'])
    if existing is not None:
        if existing != evidence:
            raise ValueError('Aynı Runtime Event kimliği farklı canonical evidence ile çakışıyor.')
        # A previous CAS may have succeeded just before seen persistence failed.
        # Heal the dedup ledger without touching GoalState or bumping its version.
        if accepted['event_id'] not in seen_event_ids:
            seen_event_ids.add(accepted['event_id'])
        return current

    if accepted['event_id'] in seen_event_ids:
        raise runtime_event.DuplicateEventError('Runtime Event daha önce işlendi.')
    if current['version'] != expected_job_version:
        raise core_state_reducer.StaleStateError(
            'GoalState sürümü değişti; Runtime Event proposal uygulanmadı.'
        )

    next_state = core_state_reducer.apply(current, {
        'expected_version': expected_job_version,
        'op': 'append_evidence',
        'evidence': evidence,
        'reason_code': _REASON,
    })
    persisted = goal_state_store.compare_and_swap(
        path,
        expected_version=expected_job_version,
        next_state=next_state,
    )

    # Advance restart-safe dedup only after canonical evidence is durable.
    seen_event_ids.add(accepted['event_id'])
    return persisted
