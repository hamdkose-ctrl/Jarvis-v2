"""Durable RuntimeEvent subscriptions: source watch -> immutable event -> GoalState evidence.

A subscription binds one canonical GoalState job to one production event source
(today: one `source_watch` rule). It is persisted beside the job's GoalState so
it survives restarts; nothing is held only in memory.

Flow (docs/roadmap-runtime-event-subscription-notu.md):

    subscribe(owner, job_id, rule_id)        Core/job creates the durable binding
    source_watch.poll                        unchanged; stores source_events rows
    pump(owner)                              turns new rows into RuntimeEvent v1,
                                             freshness + dedup + resume_token,
                                             runtime_event_commit (Reducer + CAS)

An event only appends evidence. It never sets `done`/`running` or any other
global state; completion stays a separate Core decision. A subscription closes
when its job becomes terminal/missing or its source rule is removed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import time
import uuid
from pathlib import Path

import release_guard
from modules import core_state_reducer, goal_state, goal_state_store, runtime_event, runtime_event_commit
from modules.diagnostics import record_failure as _record_failure

SCHEMA = 'runtime_event_subscriptions.v1'
REGISTRY = 'runtime_event_subscriptions.json'
SEEN = 'runtime_event_seen.json'
SOURCE = 'source_watch'
EVENT_KIND = 'source_watch.item_changed'
MAX_ACTIVE = 50

_LOCK = threading.RLock()
_OWNER = re.compile(r'[\w-]{1,100}\Z')
_ROW = frozenset({'subscription_id', 'job_id', 'source', 'source_id', 'source_event_key',
                  'source_generation', 'subject_version', 'resume_token', 'fresh_after',
                  'state', 'close_reason'})


def _root(owner) -> Path:
    from modules import goal_executor
    return goal_executor._root(owner)


def _existing_root(owner):
    """Owner goal folder without creating it; pump must not create per-owner dirs."""
    if not isinstance(owner, str) or not _OWNER.fullmatch(owner):
        raise ValueError('Runtime Event abonelik sahibi geçersiz.')
    from modules import goal_executor
    root = goal_executor.STORE / owner
    return root if (root / REGISTRY).exists() else None


def _state_path(root: Path, job_id: str) -> Path:
    return root / (job_id + '.goalstate.json')


def _valid_row(row) -> bool:
    return (isinstance(row, dict) and set(row) == _ROW and row['source'] == SOURCE
            and all(isinstance(row[k], str) and row[k] for k in
                    ('subscription_id', 'job_id', 'source_id', 'source_event_key', 'resume_token'))
            and all(type(row[k]) is int and row[k] >= 0 for k in ('source_generation', 'subject_version'))
            and isinstance(row['fresh_after'], (int, float)) and not isinstance(row['fresh_after'], bool)
            and row['state'] in ('active', 'closed')
            and (row['close_reason'] is None) == (row['state'] == 'active'))


def _load(root: Path) -> list:
    path = root / REGISTRY
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError('Runtime Event abonelik kaydı bozuk.') from None
    if not isinstance(payload, dict) or set(payload) != {'schema', 'subscriptions'} or payload['schema'] != SCHEMA:
        raise ValueError('Runtime Event abonelik kayıt şeması geçersiz.')
    rows = payload['subscriptions']
    if not isinstance(rows, list) or not all(_valid_row(row) for row in rows):
        raise ValueError('Runtime Event abonelik kayıt içeriği geçersiz.')
    if len({row['subscription_id'] for row in rows}) != len(rows):
        raise ValueError('Runtime Event abonelik kimliği yinelenmiş.')
    return rows


def _save(root: Path, rows: list) -> None:
    payload = {'schema': SCHEMA, 'subscriptions': rows}
    release_guard.atomic(root / REGISTRY, json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8'))


def _rule_exists(owner, rule_id) -> bool:
    from modules import source_watch
    return any(row['id'] == rule_id for row in source_watch.rows(owner))


def contract(row: dict) -> dict:
    """The exact subscription shape runtime_event.accept() validates against."""
    return {key: row[key] for key in
            ('source_event_key', 'source_generation', 'subject_version', 'resume_token', 'fresh_after')}


def subscribe(owner, job_id, rule_id, *, now=None) -> dict:
    """Bind one live canonical GoalState job to one source_watch rule (idempotent)."""
    if not isinstance(rule_id, str) or not rule_id:
        raise ValueError('Kaynak takibi kimliği geçersiz.')
    root = _root(owner)
    state = goal_state_store.load(_state_path(root, job_id))
    if state['owner'] != owner or state['job_id'] != job_id:
        raise ValueError('Canonical GoalState abonelik kimliğiyle eşleşmiyor.')
    if goal_state.terminal(state):
        raise core_state_reducer.TerminalStateError('Bitmiş hedefe Runtime Event aboneliği açılamaz.')
    if not _rule_exists(owner, rule_id):
        raise ValueError('Bu kullanıcıya ait kaynak takibi yok.')
    key = SOURCE + ':' + rule_id
    with _LOCK:
        rows = _load(root)
        same = [row for row in rows if row['job_id'] == job_id and row['source_event_key'] == key]
        current = next((row for row in same if row['state'] == 'active'), None)
        if current is not None:
            return copy.deepcopy(current)
        if sum(row['state'] == 'active' for row in rows) >= MAX_ACTIVE:
            raise ValueError('Etkin Runtime Event abonelik sınırı doldu.')
        row = {
            'subscription_id': uuid.uuid4().hex,
            'job_id': job_id,
            'source': SOURCE,
            'source_id': rule_id,
            'source_event_key': key,
            # A re-subscription of the same job/source gets a new generation, so
            # an event stamped for an older binding can never pass freshness.
            'source_generation': 1 + max((r['source_generation'] for r in same), default=-1),
            # GoalState version at bind time; freshness domain only, never the CAS version.
            'subject_version': state['version'],
            'resume_token': uuid.uuid4().hex,
            'fresh_after': float(time.time() if now is None else now),
            'state': 'active',
            'close_reason': None,
        }
        rows.append(row)
        _save(root, rows)
        return copy.deepcopy(row)


def bind_job(owner, job_id, rule_id):
    """Best-effort bind from a running goal tool; None when the job has no live GoalState."""
    if not isinstance(job_id, str) or not job_id:
        return None
    try:
        return subscribe(owner, job_id, rule_id)
    except (FileNotFoundError, core_state_reducer.TerminalStateError):
        return None
    except Exception:
        _record_failure('modules/runtime_event_subscription.py:bind_job')
        return None


def close(owner, subscription_id, reason) -> bool:
    if not isinstance(reason, str) or not reason:
        raise ValueError('Abonelik kapanış nedeni zorunlu.')
    root = _root(owner)
    with _LOCK:
        rows = _load(root)
        for row in rows:
            if row['subscription_id'] == subscription_id and row['state'] == 'active':
                row['state'] = 'closed'
                row['close_reason'] = reason
                _save(root, rows)
                return True
    return False


def subscriptions(owner) -> list:
    root = _existing_root(owner)
    return copy.deepcopy(_load(root)) if root else []


def event_for(row: dict, source_event: dict) -> dict:
    """Immutable RuntimeEvent v1 for one stored source_watch row and one subscription.

    event_id is deterministic, so a restart or re-scan replays the same id and
    the persistent seen ledger dedups it.
    """
    digest = hashlib.sha256((row['subscription_id'] + ':' + source_event['id']).encode('utf-8')).hexdigest()
    body = source_event['payload']
    payload = {
        'source_event_id': source_event['id'],
        'rule_id': row['source_id'],
        'title': body.get('title', ''),
        'url': body.get('url', ''),
        'published': body.get('published', ''),
        'quote': body.get('quote', ''),
        'content_sha256': body.get('content_sha256', ''),
        'official_domain': bool(body.get('official_domain')),
        'interpretation': body.get('interpretation', 'source_quote_only'),
    }
    return runtime_event.validate({
        'schema': runtime_event.SCHEMA,
        'event_id': 'rte-' + digest[:32],
        'source_event_key': row['source_event_key'],
        'source_generation': row['source_generation'],
        'subject_version': row['subject_version'],
        'occurred_at': float(source_event['created']),
        'kind': EVENT_KIND,
        'payload': payload,
    })


def _commit(path, event, row, seen):
    """One commit with a single reload on CAS race; never bypasses Reducer/CAS."""
    for attempt in (0, 1):
        version = goal_state_store.load(path)['version']
        try:
            return runtime_event_commit.commit(path, event, contract(row), seen, expected_job_version=version)
        except (core_state_reducer.StaleStateError, goal_state_store.PersistedStateConflict):
            if attempt:
                raise


def _close_rows(root, ids_reasons):
    if not ids_reasons:
        return
    rows = _load(root)
    for row in rows:
        reason = ids_reasons.get(row['subscription_id'])
        if reason and row['state'] == 'active':
            row['state'] = 'closed'
            row['close_reason'] = reason
    _save(root, rows)


def pump(owner, *, limit=50) -> dict:
    """Deliver stored source events of every active subscription as GoalState evidence."""
    summary = {'committed': 0, 'duplicate': 0, 'stale': 0, 'closed': 0, 'errors': 0}
    root = _existing_root(owner)
    if root is None:
        return summary
    from modules import source_watch
    with _LOCK:
        rows = [row for row in _load(root) if row['state'] == 'active']
        if not rows:
            return summary
        seen = runtime_event.PersistentSeen(root / SEEN)
        rules = {row['id'] for row in source_watch.rows(owner)}
        closing = {}
        for row in rows:
            path = _state_path(root, row['job_id'])
            try:
                state = goal_state_store.load(path)
            except FileNotFoundError:
                closing[row['subscription_id']] = 'JOB_MISSING'
                continue
            if state['owner'] != owner or state['job_id'] != row['job_id']:
                closing[row['subscription_id']] = 'JOB_IDENTITY_MISMATCH'
                continue
            if goal_state.terminal(state):
                closing[row['subscription_id']] = 'JOB_TERMINAL'
                continue
            if row['source_id'] not in rules:
                closing[row['subscription_id']] = 'SOURCE_REMOVED'
                continue
            for source_event in source_watch.rule_events(owner, row['source_id'], row['fresh_after'], limit):
                try:
                    event = event_for(row, source_event)
                    if event['event_id'] in seen:
                        summary['duplicate'] += 1
                        continue
                    _commit(path, event, row, seen)
                    summary['committed'] += 1
                except runtime_event.DuplicateEventError:
                    summary['duplicate'] += 1
                except runtime_event.StaleEventError:
                    summary['stale'] += 1
                except core_state_reducer.TerminalStateError:
                    closing[row['subscription_id']] = 'JOB_TERMINAL'
                    break
                except Exception:
                    # Fail closed per subscription: stop this binding for this
                    # round, keep the others flowing.
                    _record_failure('modules/runtime_event_subscription.py:pump')
                    summary['errors'] += 1
                    break
        _close_rows(root, closing)
        summary['closed'] = len(closing)
    return summary


def pump_safely(owner):
    """pump() for background/tool callers: a broken binding never stops source polling or outbox."""
    try:
        return pump(owner)
    except Exception:
        _record_failure('modules/runtime_event_subscription.py:pump_safely')
        return None
