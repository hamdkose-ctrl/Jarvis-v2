"""Canonical read-only verification/query service for UI callers."""
from __future__ import annotations

import re

from modules import execution_record, goal_executor, goal_tools, service_store, task_agents, task_results

_ID_RE = re.compile(r'^[a-f0-9]{12,32}$')


def verify(owner: str, kind: str, identity: str) -> dict:
    """Verify completed goal/task outputs without placing authority in the UI."""
    service_store.identity(owner)
    if not isinstance(identity, str) or not _ID_RE.fullmatch(identity):
        raise ValueError('Görev kimliği geçersiz.')

    if kind == 'task':
        job = task_agents._load(owner, identity)
        verifier = lambda output: task_results.verify(output, owner=owner)
    elif kind == 'goal':
        try:
            job = execution_record.load(goal_executor._root(owner), owner, identity)
        except PermissionError:
            raise ValueError('Görev sahibi eşleşmiyor.') from None
        except (OSError, ValueError):
            raise ValueError('Görev kaydı geçersiz.') from None
        verifier = lambda output: goal_tools.verify(output, owner)
    else:
        raise ValueError('Görev türü geçersiz.')

    outputs = {
        key: value
        for key, value in job.get('outputs', {}).items()
        if value.get('state') == 'done'
    }
    if not outputs:
        return {'ok': False, 'message': 'Doğrulanacak tamamlanmış çıktı yok.'}

    failed = []
    for key, value in outputs.items():
        try:
            verifier(value)
        except (ValueError, PermissionError, OSError, KeyError, TypeError):
            failed.append(key)

    return {
        'ok': not failed,
        'checked': len(outputs),
        'failed': failed,
        'message': 'Yerel kanıtlar denetlendi. İçerik doğruluğu ve hesapların güncel durumu bu kontrolün kapsamında değil.',
    }
