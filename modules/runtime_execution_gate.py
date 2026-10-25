"""Transitional runtime gate joining manifest/decision policy to durable task execution.

Ask-required capabilities may enter a prepare phase only to obtain the existing
approval artifact. A prepare call is fail-closed unless it returns state=approval.
After verified approval, the normal decision line must explicitly allow execution.
"""
from __future__ import annotations

from modules import capability_decision, capability_manifest


def _action(kind: str, data: dict) -> dict:
    row = _capability(kind)
    permission = row['permission_class']
    if kind == 'publish':
        target = str(data.get('destination', ''))
        via = 'outbox'
    elif kind in {'research', 'browser'}:
        target = str(data.get('url', kind))
        via = 'browser'
    elif kind == 'account':
        target = str(data.get('service', 'account'))
        via = 'browser'
    elif kind in {'writer', 'media', 'coder', 'verify'}:
        target = str(data.get('filename') or kind)
        via = 'file'
    elif kind == 'desktop':
        target = str(data.get('target', '')).strip()
        via = 'desktop'
    else:
        target = kind
        via = 'file'
    return {'class': permission, 'target': target, 'via': via}


def plan_task(kind: str, data: dict, *, approval_verified: bool,
              domain_invariant: str, domain_authority: str,
              user_authority: str, job_authority: str,
              effect_state: str, grants: dict | None = None,
              now: float | None = None) -> dict:
    row = _capability(kind)
    decision = capability_decision.decide(
        row,
        domain_invariant=domain_invariant,
        domain_authority=domain_authority,
        user_authority=user_authority,
        job_authority=job_authority,
        action=_action(kind, data),
        effect_state=effect_state,
        grants=grants,
        now=now,
        approval_verified=approval_verified,
    )
    phase = 'execute' if decision['worker_allowed'] else (
        'prepare' if row['decision_authority'] == 'ask_required' and not approval_verified
        and decision['reason_code'] in {'DECISION_AUTHORITY_RESTRICTED', 'PERMISSION_NOT_ALLOWED'}
        else 'blocked'
    )
    return {**decision, 'phase': phase}


def _capability(kind: str) -> dict:
    """Adapt an existing task or local-goal capability without dispatching it."""
    try:
        return capability_manifest.from_task_tool(kind)
    except ValueError:
        return capability_manifest.from_goal_tool(kind)


def accept_prepare_result(plan: dict, output: dict) -> dict:
    if not isinstance(plan, dict) or plan.get('phase') != 'prepare':
        raise ValueError('Prepare sonucu yalnız prepare aşamasında kabul edilir.')
    if not isinstance(output, dict) or output.get('state') != 'approval':
        raise PermissionError('Ask-required capability onaysız gerçek etki sonucu döndüremez.')
    return output
