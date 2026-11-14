"""Canonical read-only verification/query service for UI callers."""
from __future__ import annotations

import re

from modules import execution_record, goal_executor, result_presentation, service_store, task_agents

_ID_RE = re.compile(r'^[a-f0-9]{12,32}$')


def verify(owner: str, kind: str, identity: str) -> dict:
    """Verify completed goal/task outputs without placing authority in the UI."""
    service_store.identity(owner)
    if not isinstance(identity, str) or not _ID_RE.fullmatch(identity):
        raise ValueError('Görev kimliği geçersiz.')

    if kind == 'task':
        job = task_agents._load(owner, identity)
    elif kind == 'goal':
        try:
            job = execution_record.load(goal_executor._root(owner), owner, identity)
        except PermissionError:
            raise ValueError('Görev sahibi eşleşmiyor.') from None
        except (OSError, ValueError):
            raise ValueError('Görev kaydı geçersiz.') from None
    else:
        raise ValueError('Görev türü geçersiz.')

    outputs = {
        key: value
        for key, value in job.get('outputs', {}).items()
        if value.get('state') == 'done'
    }
    if not outputs:
        return {'ok': False, 'message': 'Doğrulanacak tamamlanmış çıktı yok.'}

    checked=result_presentation.inspect_job(job,kind)
    failed=sorted(set(outputs)-checked['verified'])

    return {
        'ok': not failed,
        'checked': len(outputs),
        'failed': failed,
        'message': 'Yerel kanıtlar denetlendi. İçerik doğruluğu ve hesapların güncel durumu bu kontrolün kapsamında değil.',
    }
