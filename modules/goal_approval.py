"""Core approval certificates in the existing per-step ExecutionRecord.

No separate store or executor. Native approvals remain mandatory; this outer
certificate binds one displayed native proposal to one durable task and plan.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import time
import uuid

TTL_SECONDS = 120
SCHEMA = 'goal_approval.v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def local_target_digest(profile, data):
    """Version the actual owner record, not just a reusable integer/index."""
    action=data.get('action');params=data.get('params',{})
    refs={'task_toggle':('tasks','tid'),'task_delete':('tasks','tid'),
          'note_delete':('items','nid'),'event_delete':('events','eid'),'kb_remove':('kb','did')}
    if action in refs:
        if profile is None:raise PermissionError('Onay için gerçek owner kayıt görünümü gerekli.')
        collection,key=refs[action]
        matches=[row for row in profile.data.get(collection,[]) if row.get('id')==params.get(key)]
        if len(matches)!=1:raise PermissionError('Onay hedef kaydı artık tekil değil.')
        return digest(matches[0])
    for prefix,collection in (('goal_','goals'),('fact_','facts'),('rule_','rules')):
        if action in (prefix+'delete',prefix+'update'):
            if profile is None:raise PermissionError('Onay için owner kayıt görünümü gerekli.')
            index=params.get('idx');rows=profile.data.get(collection,[])
            if type(index) is not int or not 0<=index<len(rows):raise PermissionError('Onay hedef kaydı bulunamadı.')
            return digest(rows[index])
    return None


def binding(job, step, proposal, profile=None):
    from modules import capability_manifest, goal_executor, goal_state_store
    if profile is not None and getattr(profile,'slug',None)!=job['owner']:
        raise PermissionError('Onay profil sahibi eşleşmiyor.')
    try:
        capability=capability_manifest.from_task_tool(step['tool'])
    except ValueError:
        capability=capability_manifest.from_goal_tool(step['tool'])
    path = goal_executor._owner_root(job['owner']) / (job['id'] + '.goalstate.json')
    state = goal_state_store.load(path) if path.exists() or path.is_symlink() else {}
    if state and (state['owner'], state['job_id']) != (job['owner'], job['id']):
        raise PermissionError('Onay hedef sahibi eşleşmiyor.')
    if state.get('state') in ('done', 'cancelled', 'failed'):
        raise PermissionError('Kapalı hedefin onayı kullanılamaz.')
    plan = state.get('goal_plan')
    steps = [{key: item.get(key) for key in ('id', 'goal', 'tool', 'input', 'depends')}
             for item in job['steps']]
    intent = state.get('goal_intent') or {}
    return {'owner': job['owner'], 'job_id': job['id'], 'task_id': step['id'],
            'capability_id':capability['id'],'capability_version':str(capability['version']),
            'operation': step['tool'], 'input_digest': digest(step['input']),
            'target_digest': digest(proposal), 'plan_version': plan.get('plan_version') if plan else None,
            'target_state_digest':local_target_digest(profile,step['input']) if step['tool']=='action' else None,
            'plan_digest': digest({'request': job['request'], 'steps': steps, 'plan': plan,
                                   'intent': {key:intent.get(key) for key in ('revision','additions')}})}


def prepare(job, step, proposal, profile=None):
    now = time.time()
    return {'schema': SCHEMA, 'approval_id': uuid.uuid4().hex,
            'binding': binding(job, step, proposal, profile), 'created_at': now,
            'expires_at': now + TTL_SECONDS, 'consumed_at': None}


def consume(job, step, proposal, *, now=None, profile=None):
    """Validate and durably consume BEFORE any checkpoint/provider invocation."""
    from modules import goal_executor, goal_job_control
    root = goal_executor._owner_root(job['owner'])
    with goal_job_control.locked(root, job['id']):
        goal_job_control.assert_fresh(root, job)
        row = step.get('approval')
        now = time.time() if now is None else now
        if (not isinstance(row, dict) or set(row) != {'schema', 'approval_id', 'binding', 'created_at', 'expires_at', 'consumed_at'}
                or row['schema'] != SCHEMA or not isinstance(row['approval_id'], str)
                or len(row['approval_id']) != 32 or any(c not in '0123456789abcdef' for c in row['approval_id'])
                or row['consumed_at'] is not None
                or any(type(row[k]) not in (int, float) or not math.isfinite(row[k]) for k in ('created_at', 'expires_at'))
                or not row['created_at'] <= now < row['expires_at'] <= row['created_at'] + TTL_SECONDS
                or row['binding'] != binding(job, step, proposal, profile)):
            raise PermissionError('Onay eski, tüketilmiş veya işlem/hedef/plan değişmiş; işlem başlatılmadı.')
        step['approval'] = dict(copy.deepcopy(row), consumed_at=now)
        # Same optimistic snapshot and process lock as other Core controls.
        # A save failure never authorizes the external adapter.
        goal_executor._save(job)
        return row['approval_id']


def verify_canonical(job, step, *, pending=False, now=None) -> dict:
    """Verify one immutable Core approval without consuming/replaying an effect.

    The existing goal_approval certificate is reused. A canonical worker may
    run only after an exact owner/job/input/plan-bound user approval has been
    durably consumed. The approval is short-lived and single use.
    """
    from modules import runtime_prepare_approval
    now = time.time() if now is None else now
    proposal = step.get('_canonical_approval_proposal')
    row = step.get('approval')
    if (not isinstance(proposal, dict) or not isinstance(row, dict)
            or set(row) != {'schema','approval_id','binding','created_at','expires_at','consumed_at'}
            or row.get('schema') != SCHEMA
            or not isinstance(row.get('approval_id'), str)
            or len(row['approval_id']) != 32
            or any(c not in '0123456789abcdef' for c in row['approval_id'])
            or any(type(row[k]) not in (int,float) or not math.isfinite(row[k])
                   for k in ('created_at','expires_at'))
            or not row['created_at'] <= now
            or row['expires_at'] > row['created_at'] + TTL_SECONDS
            or row.get('binding') != binding(job,step,proposal)):
        raise PermissionError('Canonical approval owner, input or plan changed.')
    bound = runtime_prepare_approval.expected(
        {'owner':job['owner'],'job_id':job['id'],'task_id':step['id']},
        step['tool'],step['input'],
    )
    if (set(proposal) != runtime_prepare_approval._FIELDS
            or proposal.get('state') != 'approval'
            or proposal.get('approval_schema') != runtime_prepare_approval.SCHEMA
            or proposal.get('id') != step['id']
            or any(proposal.get(key) != value for key,value in bound.items())):
        raise PermissionError('Canonical prepare approval has changed.')
    consumed = row.get('consumed_at')
    if pending:
        if consumed is not None or not now < row['expires_at']:
            raise PermissionError('Canonical approval expired or already consumed.')
    elif (type(consumed) not in (int,float) or not math.isfinite(consumed)
          or not row['created_at'] <= consumed < row['expires_at']
          or now > consumed + TTL_SECONDS):
        raise PermissionError('Canonical approval is not a live consumed authorization.')
    return copy.deepcopy(row)


def pending(owner):
    """All owner's pending goal approvals, independent of the latest pointer."""
    from modules import goal_executor
    root = goal_executor._owner_root(owner)
    rows = []
    for ident in goal_executor._job_stamps(root):
        job = goal_executor.read_job(owner, ident)
        if job and job.get('state') == 'approval' and goal_executor.is_open(job):
            rows.append(job)
    return rows


def select(owner):
    rows = pending(owner)
    if len(rows) > 1:
        raise ValueError('Birden fazla hedef onay bekliyor. Hedef kartındaki kimlikli onay düğmesini kullan: '
                         + ', '.join(job['id'] for job in rows))
    return rows[0] if rows else None
