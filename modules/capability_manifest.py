"""Read-only Capability Manifest view over the existing tool catalogs.

This is a compatibility adapter, not a dispatcher or a second tool catalog.
Existing execution, discovery and permission boundaries remain their sources of
truth; this module only exposes their static metadata in a fail-closed shape.
"""
from __future__ import annotations

import json
import re

from modules.permission_gate import CLASSES

VERSION = 1
_ID = re.compile(r'[a-z0-9][a-z0-9_.-]{0,79}\Z')
_EFFECT_POLICIES = frozenset({
    'read_only', 'local_reversible', 'local_destructive', 'external_write',
    'physical_effect',
})
_AUTHORITIES = frozenset({'execute', 'ask_required', 'suggest_only', 'forbidden'})
_FIELDS = frozenset({
    'id', 'version', 'source', 'permission_class', 'effect_policy',
    'decision_authority', 'replay', 'reconciliation', 'evidence_contract',
})

_TASK_POLICIES = {
    'media': ('local_reversible', 'local_reversible', 'execute', 'safe', 'none'),
    'publish': ('publish', 'external_write', 'ask_required', 'conditional', 'required'),
    'account': ('read', 'read_only', 'execute', 'safe', 'none'),
    'research': ('read', 'read_only', 'execute', 'safe', 'none'),
    'file': ('read', 'read_only', 'execute', 'safe', 'none'),
    'finance': ('read', 'read_only', 'execute', 'safe', 'none'),
    'computer': ('read', 'read_only', 'execute', 'safe', 'none'),
    'writer': ('local_reversible', 'local_reversible', 'execute', 'safe', 'none'),
    'browser': ('local_destructive', 'external_write', 'ask_required', 'conditional', 'required'),
    'coder': ('local_destructive', 'local_destructive', 'ask_required', 'conditional', 'required'),
    'verify': ('read', 'read_only', 'execute', 'safe', 'none'),
}

_GOAL_POLICIES = {
    'action': ('local_reversible', 'local_reversible', 'ask_required'),
    'desktop': ('physical', 'physical_effect', 'ask_required'),
    'document': ('read', 'read_only', 'execute'),
    'observe': ('read', 'read_only', 'execute'),
    'application': ('local_reversible', 'local_reversible', 'ask_required'),
    'diagnose': ('read', 'read_only', 'execute'),
    'sharing': ('physical', 'physical_effect', 'ask_required'),
    'schedule': ('local_reversible', 'local_reversible', 'ask_required'),
    'system': ('system_config', 'local_destructive', 'ask_required'),
    'monitor': ('local_reversible', 'local_reversible', 'ask_required'),
    'capability': ('local_reversible', 'local_reversible', 'ask_required'),
    'data': ('read', 'read_only', 'execute'),
}


def _row(ident: str, source: str, permission_class: str, effect_policy: str,
         authority: str, replay: str, reconciliation: str,
         evidence_contract: str) -> dict:
    return {
        'id': ident,
        'version': VERSION,
        'source': source,
        'permission_class': permission_class,
        'effect_policy': effect_policy,
        'decision_authority': authority,
        'replay': replay,
        'reconciliation': reconciliation,
        'evidence_contract': evidence_contract,
    }


def _effect_for_permission(permission_class: str) -> tuple[str, str, str, str]:
    if permission_class == 'read':
        return 'read_only', 'execute', 'safe', 'none'
    if permission_class == 'local_reversible':
        return 'local_reversible', 'execute', 'safe', 'none'
    if permission_class == 'physical':
        return 'physical_effect', 'ask_required', 'conditional', 'required'
    if permission_class in {'publish', 'message_out'}:
        return 'external_write', 'ask_required', 'conditional', 'required'
    return 'local_destructive', 'ask_required', 'conditional', 'required'


def from_task_tool(kind: str) -> dict:
    """Return one static manifest row for an existing task_tools kind."""
    from modules import task_tools
    if kind not in task_tools.CATALOG or kind not in _TASK_POLICIES:
        raise ValueError('Bilinmeyen task capability kaynağı.')
    permission, effect, authority, replay, reconciliation = _TASK_POLICIES[kind]
    return _row(f'task.{kind}', 'task_tools', permission, effect, authority,
                replay, reconciliation, f'task_result.{kind}.v1')


def from_goal_tool(kind: str) -> dict:
    """Return one static manifest row for an existing goal_tools local kind."""
    from modules import goal_tools
    if kind not in goal_tools.LOCAL or kind not in _GOAL_POLICIES:
        raise ValueError('Bilinmeyen goal capability kaynağı.')
    permission, effect, authority = _GOAL_POLICIES[kind]
    return _row(f'goal.{kind}', 'goal_tools', permission, effect, authority,
                'conditional' if authority == 'ask_required' else 'safe',
                'required' if effect != 'read_only' else 'none',
                f'goal_result.{kind}.v1')


def from_tool_contract(contract: dict, action: dict | None = None) -> dict:
    """Adapt one existing CONTRACT action without exposing its callable bindings."""
    from modules import tool_contract
    errors = tool_contract.validate(contract)
    if errors:
        raise ValueError('; '.join(errors))
    if action is None:
        if len(contract['actions']) != 1:
            raise ValueError('Birden fazla eylem için açık action seçimi gerekli.')
        action = contract['actions'][0]
    if action not in contract['actions']:
        raise ValueError('Action sözleşmeye ait değil.')
    effect, authority, replay, reconciliation = _effect_for_permission(action['class'])
    suffix = '' if len(contract['actions']) == 1 else '.' + action['id']
    return _row(f"tool.{contract['id']}{suffix}", 'tool_contract', action['class'],
                effect, authority, replay, reconciliation,
                f"tool_result.{contract['id']}.{action['id']}.v1")


def validate_catalog(rows) -> tuple[dict, ...]:
    """Reject duplicates and unknown schema/policy values before any use."""
    if not isinstance(rows, (list, tuple)):
        raise ValueError('Capability catalog liste olmalı.')
    accepted = []
    ids = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != _FIELDS:
            raise ValueError(f'Capability[{index}] şeması geçersiz.')
        ident = row.get('id')
        if not isinstance(ident, str) or not _ID.fullmatch(ident) or ident in ids:
            raise ValueError(f'Capability[{index}] kimliği geçersiz veya yinelenmiş.')
        if row.get('version') != VERSION:
            raise ValueError(f'Capability[{index}] sürümü desteklenmiyor.')
        if not isinstance(row.get('source'), str) or row['source'] not in {'tool_contract', 'task_tools', 'goal_tools'}:
            raise ValueError(f'Capability[{index}] kaynağı geçersiz.')
        if row.get('permission_class') not in CLASSES:
            raise ValueError(f'Capability[{index}] permission sınıfı geçersiz.')
        if row.get('effect_policy') not in _EFFECT_POLICIES:
            raise ValueError(f'Capability[{index}] effect politikası geçersiz.')
        if row.get('decision_authority') not in _AUTHORITIES:
            raise ValueError(f'Capability[{index}] authority geçersiz.')
        if row.get('replay') not in {'safe', 'conditional'} or row.get('reconciliation') not in {'none', 'required'}:
            raise ValueError(f'Capability[{index}] replay/reconciliation politikası geçersiz.')
        if not isinstance(row.get('evidence_contract'), str) or not _ID.fullmatch(row['evidence_contract']):
            raise ValueError(f'Capability[{index}] evidence sözleşmesi geçersiz.')
        try:
            json.dumps(row, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            raise ValueError(f'Capability[{index}] JSON uyumlu değil.') from None
        ids.add(ident)
        accepted.append(dict(row))
    return tuple(accepted)


def catalog() -> dict:
    """Build a validated, JSON-only view from existing catalogs; never dispatches."""
    from modules import goal_tools, task_tools, tool_contract

    rows = [from_task_tool(kind) for kind in task_tools.CATALOG]
    rows.extend(from_goal_tool(kind) for kind in goal_tools.LOCAL)
    for contract in tool_contract.load_all().values():
        rows.extend(from_tool_contract(contract, action) for action in contract['actions'])
    return {'version': VERSION, 'capabilities': list(validate_catalog(rows))}
