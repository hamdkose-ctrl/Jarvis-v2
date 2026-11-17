"""Bound prepare approval artifacts for ask-required workers without native prepare receipts.

Only adapters explicitly listed in ``prepare`` may use this bridge.  It never
grants a native action and never replaces an adapter's own exact-action approval.
"""
from __future__ import annotations

import hashlib
import json

from modules import capability_manifest

SCHEMA = 'runtime_prepare_approval.v1'
_FIELDS = frozenset({'state','text','id','approval_schema','owner','job_id','step_id',
                     'capability_id','capability_version','input_digest'})


def _digest(data: dict) -> str:
    payload=json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def expected(identity: dict, kind: str, data: dict) -> dict:
    if not isinstance(identity,dict):raise ValueError('Prepare approval kimliği geçersiz.')
    owner=identity.get('owner');job_id=identity.get('job_id');step_id=identity.get('task_id')
    if not all(isinstance(value,str) and value for value in (owner,job_id,step_id)):
        raise ValueError('Prepare approval execution kimliği eksik.')
    row=_capability(kind)
    return {'owner':owner,'job_id':job_id,'step_id':step_id,'capability_id':row['id'],
            'capability_version':str(row['version']),'input_digest':_digest(data)}


def prepare(identity: dict, kind: str, data: dict) -> dict:
    if kind not in {'coder','desktop','publish','browser','writer'}:raise ValueError('Sentetik prepare approval bu capability için desteklenmez.')
    bound=expected(identity,kind,data)
    text = ('Kod geliştirme adımı gerçek taslak üretmeden önce açık onay bekliyor.'
            if kind == 'coder' else
            'Dış gönderim başlamadan önce kesin hedef ve içerik için onay bekliyor.'
            if kind == 'publish' else
            'Writer dosyayı oluşturmadan önce kullanıcı onayı bekliyor.'
            if kind == 'writer' else
            'Tarayıcı gerçek sayfada işlem adımına geçmeden önce açık onay bekliyor.'
            if kind == 'browser' else
            'PC görevi gerçek masaüstü işlemi başlatmadan önce açık onay bekliyor.')
    return {'state':'approval','text':text,
            'id':bound['step_id'],'approval_schema':SCHEMA,**bound}


def accept(approval: dict, identity: dict, kind: str, data: dict) -> bool:
    if kind not in {'coder','desktop','publish','browser','writer'} or not isinstance(approval,dict) or set(approval)!=_FIELDS:
        raise PermissionError('Prepare approval kaydı geçersiz.')
    if approval.get('state')!='approval' or approval.get('approval_schema')!=SCHEMA or approval.get('id')!=approval.get('step_id'):
        raise PermissionError('Prepare approval kaydı geçersiz.')
    bound=expected(identity,kind,data)
    if any(approval.get(key)!=value for key,value in bound.items()):
        raise PermissionError('Prepare onayı mevcut job/step/input ile eşleşmiyor.')
    from modules import hooks
    hooks.observe('approval',{'kind':kind,'decision':'accepted','job_id':str(identity.get('job_id','')),
                              'step_id':str(identity.get('step_id',''))},owner=identity.get('owner'))
    return True


def _capability(kind: str) -> dict:
    """Read the existing manifest view; this is not a second catalog."""
    try:
        return capability_manifest.from_task_tool(kind)
    except ValueError:
        return capability_manifest.from_goal_tool(kind)



def require_writer_execution(owner: str, task: dict) -> bool:
    """Native Writer's last authorization fence: check persisted Core consent.

    A boolean in worker execution context is not an approval certificate.
    Verify the current owner/job/step/input and consumed exact authorization
    from the existing ExecutionRecord before ANY model or filesystem access.
    Direct callers, model-created identities and legacy queue executions cannot
    manufacture consent by setting _writer_approved=True.
    """
    from modules import goal_approval, goal_executor
    identity = task.get('execution') if isinstance(task, dict) else None
    data = task.get('input') if isinstance(task, dict) else None
    if (not isinstance(identity, dict) or identity.get('_writer_approved') is not True
            or not isinstance(data, dict) or identity.get('owner') != owner
            or not isinstance(identity.get('job_id'), str)
            or not isinstance(identity.get('task_id'), str)):
        raise PermissionError('Writer açık kullanıcı onayı olmadan dosya oluşturamaz.')
    try:
        job = goal_executor.read_job(owner, identity['job_id'])
    except (ValueError, OSError) as exc:
        # An invented/malformed ID is always a denied authorization, not an
        # unhandled exception that escapes the Writer's native boundary.
        raise PermissionError('Writer onayı geçerli kayıtlı hedefe ait değil.') from exc
    if (not isinstance(job, dict) or job.get('owner') != owner
            or job.get('id') != identity['job_id']
            or job.get('state') not in ('running', 'approval')):
        raise PermissionError('Writer onaylı canlı hedefi bulunamadı.')
    matches = [step for step in job.get('steps', ())
               if (isinstance(step, dict)
                   and step.get('id') == identity['task_id']
                   and step.get('tool') == 'writer'
                   and step.get('input') == data)]
    if len(matches) != 1:
        raise PermissionError('Writer onayı tam adım/girdi ile eşleşmiyor.')
    step = matches[0]
    canonical = identity.get('_canonical_scheduler_offer') is not None
    # Legacy GoalExecutor records the no-effect approval as attempt 1 and
    # performs the explicitly approved write as attempt 2. The approval
    # proposal remains in outputs until the write replaces it; it is not a
    # completed writer result. Canonical Scheduler starts its own attempt 1.
    prior = job.get('outputs', {}).get(step['id'])
    expected_attempt = 1 if canonical else 2
    if (step.get('state') != 'running'
            or step.get('attempts') != expected_attempt
            or step.get('started') is not True
            or (prior is not None and
                (not isinstance(prior, dict) or prior.get('state') != 'approval'))
            or (not canonical and prior is None)):
        raise PermissionError('Writer onayının tek deneme koşulu sağlanmadı.')
    if identity.get('_canonical_scheduler_offer') is not None:
        goal_approval.verify_canonical(job, step)
    else:
        # Legacy GoalExecutor has an explicit consumed GoalApproval record,
        # distinct from task_agents' unapproved task execution journal.
        approval = step.get('approval')
        proposal = job.get('outputs', {}).get(step['id'])
        if (not isinstance(approval, dict)
                or type(approval.get('consumed_at')) not in (int, float)
                or type(approval.get('execution_started_at')) not in (int, float)
                or approval.get('binding') != goal_approval.binding(job, step, proposal)):
            raise PermissionError('Writer için tüketilmiş Core onayı bulunamadı.')
    return True
