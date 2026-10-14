"""Persistent opt-in read/production queue, serviced only while Jarvis runs."""
import json
import math
import threading
import time
import uuid
from modules import llm, service_store
from modules.diagnostics import record_failure as _record_failure

_START_LOCK=threading.Lock()
_THREAD=None


def enqueue(owner, tasks, instruction='', delay=0, repeat_seconds=0):
    from modules import task_agents
    task_agents.validate(tasks)
    # Unattended queue never hides a browser/code/write-account approval step.
    if any(t['agent'] not in ('research','writer','account','verify','media') for t in tasks):
        raise ValueError('Arka plan kuyruğu yalnız okuma/rapor/doğrulama kabul eder; dış gönderim burada çalışmaz.')
    if type(delay) not in (int,float) or not math.isfinite(delay) or not 0<=delay<=30*86400:
        raise ValueError('Kuyruk gecikmesi geçersiz.')
    if not isinstance(instruction,str) or len(instruction)>20000:raise ValueError('Kuyruk isteği geçersiz.')
    if type(repeat_seconds) is not int or repeat_seconds!=0 and not 300<=repeat_seconds<=30*86400:
        raise ValueError('Tekrar aralığı en az 300 saniye olmalı.')
    qid=uuid.uuid4().hex[:16];job_id=uuid.uuid4().hex[:12]
    with service_store.database(owner) as db:
        db.execute('INSERT INTO queue(id,tasks,instruction,due,state,job_id,created,error,repeat_seconds) VALUES(?,?,?,?,?,?,?,?,?)',
                   (qid,service_store.encode(tasks),instruction,time.time()+delay,'queued',job_id,time.time(),'',repeat_seconds))
    return qid


def rows(owner):
    with service_store.database(owner) as db:
        return [dict(row) for row in db.execute('SELECT id,state,due,job_id,error,repeat_seconds,last_job_id,instruction FROM queue ORDER BY created DESC LIMIT 50')]

def render_rows(items):
    from modules import privacy
    if not items:return 'Zamanlanmış görevin yok.'
    labels={'running':'Çalışıyor','done':'Tamamlandı','cancelled':'İptal edildi','blocked':'Durdu; görev sonucunu incele'}
    lines=[]
    for row in items:
        remaining=max(0,math.ceil(row['due']-time.time()))
        status=(f'{remaining} saniye sonra başlayacak' if remaining else 'Zamanı geldi; çalışma sırasını bekliyor') if row['state']=='queued' else labels.get(row['state'],'Durum bilinmiyor')
        text=privacy.redact(row.get('instruction','')).strip() or 'Zamanlanmış görev'
        result_id=row.get('last_job_id') if row['state']=='queued' else row['job_id']
        lines.append(text+'\nDurum: '+status+(f"\nHer {row['repeat_seconds']} saniyede tekrar eder." if row['repeat_seconds'] else '')+
                     ('\nSonuç: görev durumu '+result_id if result_id else '\nSonuç, iş çalıştıktan sonra oluşacak.')+'\nİptal: kuyruk iptal '+row['id'])
    return '\n\n'.join(lines)


def cancel(owner,qid):
    with service_store.database(owner) as db:
        row=db.execute('SELECT * FROM queue WHERE id=?',(qid,)).fetchone()
        if not row:raise ValueError('Bu kullanıcıya ait kuyruk işi yok.')
        db.execute("UPDATE queue SET state='cancelled' WHERE id=? AND state IN ('queued','running','blocked')",(qid,))
    from modules import task_agents
    if row['state']=='running':
        try:task_agents.cancel_job(owner,row['job_id'])
        except ValueError:pass


def tick(owner, notify=None):
    from modules import task_agents
    service_store.identity(owner)
    with task_agents._LOCK:
        if owner in task_agents._ACTIVE:return
    with service_store.database(owner) as db:
        row=db.execute("SELECT * FROM queue WHERE (state='queued' AND due<=?) OR (state='running' AND lease<=?) ORDER BY due LIMIT 1",(time.time(),time.time())).fetchone()
        if not row:return
        row=dict(row)
        db.execute("UPDATE queue SET state='running',lease=? WHERE id=?",(time.time()+90,row['id']))
    heartbeat_stop=threading.Event()
    def heartbeat():
        token=llm._key_context.set(owner)
        try:
            while not heartbeat_stop.wait(20):
                with service_store.database(owner) as db:
                    db.execute("UPDATE queue SET lease=? WHERE id=? AND state='running'",(time.time()+90,row['id']))
        finally:llm._key_context.reset(token)
    pulse=threading.Thread(target=heartbeat,daemon=True,name='task-lease');pulse.start()
    try:
        tasks=json.loads(row['tasks']);task_agents.validate(tasks)
        if any(t['agent'] not in ('research','writer','account','verify','media') for t in tasks):raise ValueError('Kuyruk planı güvenli araç sınırını aşıyor.')
        # The assigned job identity is saved before any execution. After restart,
        # reuse its journal instead of creating a second independent job.
        path=task_agents._job_path(task_agents._root(owner),row['job_id'])
        if path.exists():job=task_agents.continue_job(owner,row['job_id'],queue_id=row['id'],queue_tasks=tasks)
        else:job=task_agents.execute(owner,tasks,row['instruction'],job_id=row['job_id'],queue_id=row['id'])
        state='done' if job['state']=='done' else 'cancelled' if job['state']=='cancelled' else 'blocked'
        error=''
    except task_agents.Busy:
        # Another task claimed this owner after the initial check. Keep the
        # assigned journal identity and retry later; cancellation remains final.
        heartbeat_stop.set()
        with service_store.database(owner) as db:
            db.execute("UPDATE queue SET state='queued',lease=0 WHERE id=? AND job_id=? AND state='running'",
                       (row['id'],row['job_id']))
        return
    except Exception as exc:
        _record_failure('modules/task_queue.py:tick')
        state='blocked';error=type(exc).__name__
    finally:heartbeat_stop.set()
    with service_store.database(owner) as db:
        count=db.execute("UPDATE queue SET state=?,error=? WHERE id=? AND state='running'",(state,error,row['id'])).rowcount
        if count:
            db.execute('INSERT OR IGNORE INTO queue_runs VALUES(?,?,?,?)',(row['id'],row['job_id'],state,time.time()))
            if state=='done' and row['repeat_seconds']:
                db.execute("UPDATE queue SET state='queued',due=?,job_id=?,last_job_id=?,lease=0 WHERE id=? AND state='done'",
                           (time.time()+row['repeat_seconds'],uuid.uuid4().hex[:12],row['job_id'],row['id']))
    if notify and count:notify(owner,row['id'],state,row['job_id'])


def is_cancelled(owner,qid):
    with service_store.database(owner) as db:
        row=db.execute('SELECT state FROM queue WHERE id=?',(qid,)).fetchone()
        return not row or row['state']=='cancelled'


def start(stop_event, notify=None, allowed_owners=None):
    """One engine-owned worker; no boot-time model/network call without queued work."""
    global _THREAD
    with _START_LOCK:
        if _THREAD and _THREAD.is_alive():return
        def loop():
            while not stop_event.wait(5):
                if not service_store.ROOT.exists():continue
                for path in sorted(service_store.ROOT.glob('*.sqlite3')):
                    if stop_event.is_set():return
                    if allowed_owners is not None and path.stem not in allowed_owners():continue
                    token=llm._key_context.set(path.stem)
                    from modules import outbox,task_agents,privacy
                    try:
                        tick(path.stem,notify)
                        if not privacy.blocked('web') and outbox.has_pending(path.stem):
                            with task_agents._active(path.stem):results=outbox.poll(path.stem)
                            for result in results:
                                if result['state'] in ('done','failed','blocked'):
                                    job=task_agents.recent(path.stem)
                                    if job and any(o.get('id')==result['id'] for o in job['outputs'].values()):
                                        resumed=task_agents.continue_job(path.stem,job['id'])
                                        if notify:notify(path.stem,result['id'],resumed['state'],job['id'])
                    except task_agents.Busy:pass
                    except Exception:
                        _record_failure('modules/task_queue.py:loop')
                        pass # corrupt/foreign journal never runs work
                    finally:llm._key_context.reset(token)
        _THREAD=threading.Thread(target=loop,name='jarvis-task-queue',daemon=True)
        _THREAD.start()
