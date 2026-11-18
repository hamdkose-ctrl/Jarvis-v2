"""Canonical Core authority for goal/task lifecycle controls requested by UIs."""
from __future__ import annotations

import re
from collections.abc import Callable

from modules import goal_executor, service_store, task_agents

_ID_RE = re.compile(r'^[a-f0-9]{12,32}$')
_APPROVAL_RE = re.compile(r'^[a-f0-9]{16}$')
_ACTIONS = frozenset({'cancel', 'resume', 'approve', 'answer'})


def dispatch(
    owner: str,
    profile_name: str,
    submit: Callable[..., object],
    kind: str,
    identity: str,
    action: str,
    control: str = '',
    answer: str = '',
    approval_id: str = '',
) -> str:
    """Validate and dispatch one exact lifecycle control under Core authority.

    ``submit`` is the existing engine transport.  The caller supplies user input;
    this service owns all lifecycle/state/receipt decisions and command shaping.
    """
    service_store.identity(owner)
    if not isinstance(identity, str) or not _ID_RE.fullmatch(identity):
        raise ValueError('Görev kimliği geçersiz.')
    if action not in _ACTIONS:
        raise ValueError('Görev işlemi geçersiz.')
    if not isinstance(answer, str) or len(answer) > 2000:
        raise ValueError('Yanıt fazla uzun.')

    if kind == 'goal':
        # BRAIN-05: bir hedef kendi kimliğiyle yönetilebilir; `latest()` tek hedef seçicisi değildir.
        # Sahip, kimlik biçimi ve tazelik (`control_key`) burada yeniden doğrulanır.
        job = goal_executor.read_job(owner, identity)
        if not job:
            raise ValueError('Seçilen hedef bulunamadı veya sana ait değil; başka hedefe işlem uygulanmadı.')
        if action == 'cancel':
            return goal_executor.cancel_job(owner, identity)
        if not isinstance(control, str) or goal_executor.control_key(job) != control:
            raise ValueError('Görev değişmiş; önce yenile.')
        if action == 'approve' and job['state'] != 'approval':
            raise ValueError('Hedef onay beklemiyor.')
        if action == 'answer' and (job['state'] != 'question' or not answer.strip()):
            raise ValueError('Hedef yanıt beklemiyor veya yanıt boş.')
        if action == 'resume' and job['state'] not in {'paused', 'question', 'running'}:
            raise ValueError('Bu hedef bu düğmeyle sürdürülemez.')
        verb = {'resume': 'devam', 'approve': 'onayla', 'answer': 'yanıtla'}[action]
        command = f'hedef {verb} {identity} {control}' + (': ' + answer.strip() if action == 'answer' else '')
    elif kind == 'task':
        job = task_agents._load(owner, identity)
        if action == 'cancel':
            task_agents.cancel_job(owner, identity)
            return 'Seçilen görev için iptal kaydedildi.'
        if goal_executor.control_key(job) != control:
            raise ValueError('Görev veya bekleyen işlem değişmiş; önce yenile.')
        if action == 'resume':
            command = 'görev devam ' + identity
        elif action == 'approve':
            step = next((s for s in job['tasks'] if s['state'] == 'approval'), None)
            receipt = job['outputs'].get(step['id'], {}) if step else {}
            if not step or receipt.get('id') != approval_id or not _APPROVAL_RE.fullmatch(approval_id or ''):
                raise ValueError('Onay seçilen görevin bekleyen işlemiyle eşleşmiyor.')
            if step['agent'] != 'publish':
                # Karar 2 Aşama C: a legacy task job has no browser approval.
                # An interactive browser plan only exists on a canonical goal
                # card, which the 'goal' branch above already owns.
                raise ValueError('Bu işlem sohbetten yönetilmeli.')
            command = 'işlem onayla ' + approval_id
        else:
            raise ValueError('Bu görev türü serbest yanıt kabul etmiyor.')
    else:
        raise ValueError('Görev türü geçersiz.')

    import uuid
    if submit(command, 'yazı', profile_name, rid=uuid.uuid4().hex) is False:
        raise ValueError('Kontrol isteği kuyruğa alınamadı.')
    return 'Kontrol isteği seçilen görev için Jarvis’e iletildi.'
