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
    if kind not in {'coder','desktop'}:raise ValueError('Sentetik prepare approval bu capability için desteklenmez.')
    bound=expected(identity,kind,data)
    text = ('Kod geliştirme adımı gerçek taslak üretmeden önce açık onay bekliyor.'
            if kind == 'coder' else
            'PC görevi gerçek masaüstü işlemi başlatmadan önce açık onay bekliyor.')
    return {'state':'approval','text':text,
            'id':bound['step_id'],'approval_schema':SCHEMA,**bound}


def accept(approval: dict, identity: dict, kind: str, data: dict) -> bool:
    if kind not in {'coder','desktop'} or not isinstance(approval,dict) or set(approval)!=_FIELDS:
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
