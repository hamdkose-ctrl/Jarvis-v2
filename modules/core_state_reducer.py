"""Pure single-writer reducer for canonical GoalState v1.

The reducer is deliberately storage-agnostic. Callers provide one validated
snapshot and an expected_version proposal; persistence/CAS integration is a
separate compatibility step.
"""
from __future__ import annotations

import copy
import json

from modules import goal_state


class StaleStateError(ValueError):
    pass


class TerminalStateError(ValueError):
    pass


class InvalidTransitionError(ValueError):
    pass


_TRANSITIONS = {
    'pending': frozenset({'running', 'waiting', 'paused', 'failed', 'done', 'cancelled'}),
    'running': frozenset({'waiting', 'paused', 'failed', 'done', 'cancelled'}),
    'waiting': frozenset({'running', 'paused', 'failed', 'cancelled'}),
    'paused': frozenset({'running', 'waiting', 'failed', 'cancelled'}),
    'failed': frozenset({'running', 'waiting', 'paused', 'cancelled'}),
    'done': frozenset(),
    'cancelled': frozenset(),
}


def _json_only(value, message):
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError(message) from None


def _reason(proposal):
    reason = proposal.get('reason_code')
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('Reducer reason_code zorunlu.')
    return reason.strip()


def _audit(state, *, op, reason_code):
    state['version'] += 1
    state['audit'].append({
        'version': state['version'],
        'op': op,
        'state': state['state'],
        'reason_code': reason_code,
    })
    return goal_state.validate(state)


def apply(current: dict, proposal: dict) -> dict:
    """Apply one fail-closed proposal and return a new GoalState snapshot."""
    state = goal_state.validate(current)
    if not isinstance(proposal, dict):
        raise ValueError('Reducer proposal sözlük olmalı.')
    expected = proposal.get('expected_version')
    if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
        raise ValueError('Reducer expected_version geçersiz.')
    if expected != state['version']:
        raise StaleStateError('GoalState sürümü değişti; eski proposal uygulanmadı.')
    if state['state'] in {'done', 'cancelled'}:
        raise TerminalStateError('Terminal GoalState değiştirilemez.')

    op = proposal.get('op')
    if op == 'set_state':
        target = proposal.get('state')
        if target not in goal_state.STATES:
            raise InvalidTransitionError('Hedef state geçersiz.')
        if target not in _TRANSITIONS[state['state']]:
            raise InvalidTransitionError(
                f"Geçersiz state geçişi: {state['state']} -> {target}."
            )
        reason = _reason(proposal)
        next_state = copy.deepcopy(state)
        next_state['state'] = target
        if target not in {'waiting', 'paused'}:
            next_state['blocker'] = None
        return _audit(next_state, op=op, reason_code=reason)

    if op == 'append_evidence':
        reason = _reason(proposal)
        evidence = proposal.get('evidence')
        if not isinstance(evidence, dict) or not evidence:
            raise ValueError('Reducer evidence geçersiz.')
        _json_only(evidence, 'Reducer evidence JSON uyumlu değil.')
        next_state = copy.deepcopy(state)
        next_state['evidence'].append(copy.deepcopy(evidence))
        return _audit(next_state, op=op, reason_code=reason)

    if op == 'set_blocker':
        reason = _reason(proposal)
        blocker = proposal.get('blocker')
        if not isinstance(blocker, dict) or not isinstance(blocker.get('code'), str) or not blocker['code']:
            raise ValueError('Reducer blocker geçersiz.')
        _json_only(blocker, 'Reducer blocker JSON uyumlu değil.')
        next_state = copy.deepcopy(state)
        next_state['blocker'] = copy.deepcopy(blocker)
        return _audit(next_state, op=op, reason_code=reason)

    if op == 'clear_blocker':
        reason = _reason(proposal)
        next_state = copy.deepcopy(state)
        next_state['blocker'] = None
        return _audit(next_state, op=op, reason_code=reason)

    raise ValueError('Bilinmeyen reducer işlemi.')
