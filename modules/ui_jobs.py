"""Bounded background work for read-only UI operations; results are isolated per owner."""
import secrets
import contextvars
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from modules.diagnostics import record_failure as _record_failure

_LOCK=threading.RLock()
_JOBS={}
_POOL=ThreadPoolExecutor(max_workers=2, thread_name_prefix='jarvis-ui')


def start(owner, kind, fn):
    context=contextvars.copy_context()
    now=time.monotonic()
    with _LOCK:
        for rid,row in list(_JOBS.items()):
            if row['state'] in ('done','error') and now-row['created']>300:
                del _JOBS[rid]
        for rid,row in _JOBS.items():
            if row['owner']==owner and row['kind']==kind and row['state'] in ('queued','running'):
                return {'job':rid,'state':row['state']}
        if sum(x['state'] in ('queued','running') for x in _JOBS.values())>=8:
            raise ValueError('Arka plan işlemleri dolu; mevcut işlemin bitmesini bekle.')
        if len(_JOBS)>=32:
            completed=[rid for rid,row in _JOBS.items() if row['state'] in ('done','error')]
            if completed:del _JOBS[completed[0]]
        rid=secrets.token_hex(16)
        _JOBS[rid]={'owner':owner,'kind':kind,'created':now,'state':'queued'}
    def run():
        with _LOCK:_JOBS[rid]['state']='running'
        try:
            result=context.run(fn)
            with _LOCK:_JOBS[rid].update(state='done',data=result)
        except Exception as exc:
            _record_failure('modules/ui_jobs.py:run')
            msg=str(exc) if isinstance(exc,ValueError) else 'İşlem tamamlanamadı; tanı günlüğünü kontrol et.'
            with _LOCK:_JOBS[rid].update(state='error',error=msg)
    try:_POOL.submit(run)
    except Exception:
        _record_failure('modules/ui_jobs.py:submit')
        with _LOCK:_JOBS.pop(rid,None)
        raise
    return {'job':rid,'state':'queued'}


def status(owner,rid):
    with _LOCK:
        row=_JOBS.get(str(rid))
        if row is None or row['owner']!=owner:
            raise ValueError('Bu kullanıcıya ait işlem bulunamadı.')
        return {k:row[k] for k in ('state','data','error') if k in row}
