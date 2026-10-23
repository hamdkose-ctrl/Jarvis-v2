"""Pure manifest-bound decision line before capability execution.

This module does not dispatch workers or mutate GoalState.  It combines static
manifest authority with domain/user/job authority, evaluates the current
Permission Gate input and records the caller-provided effect state.  Only the
fully permissive combination can be handed to a worker by a later integration.
"""
from __future__ import annotations

from modules import capability_manifest, permission_gate

AUTHORITIES = ('execute', 'ask_required', 'suggest_only', 'forbidden')
_AUTHORITY_RANK = {value: index for index, value in enumerate(AUTHORITIES)}
DOMAIN_INVARIANTS = {'pass', 'block'}
EFFECT_STATES = {'ready', 'reconcile', 'blocked'}


def _authority(*values: str) -> str:
    for value in values:
        if value not in _AUTHORITY_RANK:
            raise ValueError('Bilinmeyen Decision Authority değeri.')
    return max(values, key=_AUTHORITY_RANK.__getitem__)


def _permission_mismatch(row: dict, action: dict) -> dict | None:
    actual = action.get('class') if isinstance(action, dict) else None
    if actual == row['permission_class']:
        return None
    return {
        'decision': permission_gate.DENY,
        'class': actual if isinstance(actual, str) else '',
        'reason': 'Capability manifest ile eylem izin sınıfı eşleşmiyor.',
    }


def decide(capability: dict, *, domain_invariant: str,
           domain_authority: str, user_authority: str, job_authority: str,
           action: dict, effect_state: str, grants: dict | None = None,
           now: float | None = None) -> dict:
    """Return a fail-closed decision snapshot; never calls a worker.

    Fixed order is Domain Invariant -> Decision Authority -> Permission ->
    Effect Policy.  The manifest authority is always included in the authority
    intersection, so callers cannot raise a capability above its static limit.
    """
    row = capability_manifest.validate_catalog([capability])[0]
    if domain_invariant not in DOMAIN_INVARIANTS:
        raise ValueError('Bilinmeyen domain invariant sonucu.')
    if effect_state not in EFFECT_STATES:
        raise ValueError('Bilinmeyen effect policy sonucu.')

    if domain_invariant == 'block':
        authority = 'forbidden'
    else:
        authority = _authority(
            row['decision_authority'], domain_authority,
            user_authority, job_authority,
        )

    mismatch = _permission_mismatch(row, action)
    permission = mismatch or permission_gate.decide(action, grants=grants, now=now)

    worker_allowed = (
        domain_invariant == 'pass'
        and authority == 'execute'
        and permission['decision'] == permission_gate.ALLOW
        and effect_state == 'ready'
    )

    if domain_invariant == 'block':
        reason_code = 'DOMAIN_INVARIANT_BLOCKED'
    elif mismatch:
        reason_code = 'PERMISSION_CLASS_MISMATCH'
    elif authority != 'execute':
        reason_code = 'DECISION_AUTHORITY_RESTRICTED'
    elif permission['decision'] != permission_gate.ALLOW:
        reason_code = 'PERMISSION_NOT_ALLOWED'
    elif effect_state != 'ready':
        reason_code = 'EFFECT_NOT_READY'
    else:
        reason_code = 'READY_FOR_WORKER'

    return {
        'capability_id': row['id'],
        'capability_version': row['version'],
        'domain_invariant': domain_invariant,
        'authority': authority,
        'permission': permission,
        'effect': effect_state,
        'worker_allowed': worker_allowed,
        'reason_code': reason_code,
    }
