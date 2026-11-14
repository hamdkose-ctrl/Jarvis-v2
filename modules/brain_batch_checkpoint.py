"""Write-ahead batch progress in the existing owner-scoped service SQLite.

A checkpoint is an observation, never an execution/approval grant. Repeating a
request returns its persisted progress; an interrupted started action is unknown
and is never replayed, even when its reply or final checkpoint was lost.
"""
from __future__ import annotations
import hashlib
import json
import time
from modules import service_store


def _schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS brain_batches(
        request_id TEXT PRIMARY KEY, digest TEXT NOT NULL, progress TEXT NOT NULL)''')


def begin(owner, request_id, actions):
    if not isinstance(request_id,str) or not request_id or len(request_id)>200:
        raise ValueError('Batch request kimliği gerekli.')
    payload=json.dumps(actions,ensure_ascii=False,sort_keys=True,default=dict,allow_nan=False)
    digest=hashlib.sha256(payload.encode()).hexdigest()
    with service_store.database(owner) as db:
        _schema(db)
        prior=db.execute('SELECT digest,progress FROM brain_batches WHERE request_id=?',(request_id,)).fetchone()
        if prior:
            if prior['digest']!=digest:raise ValueError('Aynı batch request farklı işlemlere taşınamaz.')
            return json.loads(prior['progress'])
        progress={'state':'running','actions':{str(a['action_id']):'queued' for a in actions},
                  'lines':[],'updated_at':time.time()}
        db.execute('INSERT INTO brain_batches VALUES(?,?,?)',(request_id,digest,service_store.encode(progress)))
    return None


def record(owner, request_id, action_id, status, text=''):
    allowed={'running','succeeded','failed','unknown','handled','partial','needs_input','blocked',
             'unavailable','cancelled','skipped_dependency','deferred_core_pending'}
    if status not in allowed:raise ValueError('Batch checkpoint durumu geçersiz.')
    with service_store.database(owner) as db:
        row=db.execute('SELECT progress FROM brain_batches WHERE request_id=?',(request_id,)).fetchone()
        progress=json.loads(row['progress'])
        if action_id not in progress['actions']:raise ValueError('Batch action kimliği geçersiz.')
        before=progress['actions'][action_id]
        if before not in ('queued','running') or (status=='running' and before!='queued'):
            raise ValueError('Batch action tekrar başlatılamaz.')
        progress['actions'][action_id]=status
        if text:progress['lines'].append(str(text)[:2000])
        progress['updated_at']=time.time()
        db.execute('UPDATE brain_batches SET progress=? WHERE request_id=?',(service_store.encode(progress),request_id))


def finish(owner, request_id, status):
    with service_store.database(owner) as db:
        row=db.execute('SELECT progress FROM brain_batches WHERE request_id=?',(request_id,)).fetchone()
        progress=json.loads(row['progress']);progress['state']=status;progress['updated_at']=time.time()
        db.execute('UPDATE brain_batches SET progress=? WHERE request_id=?',(service_store.encode(progress),request_id))


def replay_text(progress):
    rows=[f'{ident}: '+('unknown' if state=='running' else state)
          for ident,state in progress['actions'].items()]
    return ('Bu isteğin kayıtlı ilerlemesi korundu; önceki işlemler tekrar yürütülmedi.\n'
            +'\n'.join(progress['lines']+rows))
