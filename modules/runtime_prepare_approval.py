"""Bound prepare approval artifacts for ask-required workers without native prepare receipts."""
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
    row=capability_manifest.from_task_tool(kind)
    return {'owner':owner,'job_id':job_id,'step_id':step_id,'capability_id':row['id'],
            'capability_version':str(row['version']),'input_digest':_digest(data)}


def prepare(identity: dict, kind: str, data: dict) -> dict:
    if kind!='coder':raise ValueError('Sentetik prepare approval yalnız coder için desteklenir.')
    bound=expected(identity,kind,data)
    return {'state':'approval','text':'Kod geliştirme adımı gerçek taslak üretmeden önce açık onay bekliyor.',
            'id':bound['step_id'],'approval_schema':SCHEMA,**bound}


def accept(approval: dict, identity: dict, kind: str, data: dict) -> bool:
    if kind!='coder' or not isinstance(approval,dict) or set(approval)!=_FIELDS:
        raise PermissionError('Coder prepare approval kaydı geçersiz.')
    if approval.get('state')!='approval' or approval.get('approval_schema')!=SCHEMA or approval.get('id')!=approval.get('step_id'):
        raise PermissionError('Coder prepare approval kaydı geçersiz.')
    bound=expected(identity,kind,data)
    if any(approval.get(key)!=value for key,value in bound.items()):
        raise PermissionError('Coder onayı mevcut job/step/input ile eşleşmiyor.')
    return True
