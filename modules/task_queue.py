"""Persistent opt-in read/production queue, serviced only while Jarvis runs."""
import json
import math
import secrets
import threading
import time
import uuid
from datetime import datetime
from modules import llm, service_store
from modules.cron_schedule import CronExpression
from modules.diagnostics import record_failure as _record_failure

_START_LOCK=threading.Lock()
_THREAD=None
_DAILY_NOTIFY=None
_DAILY_NEXT=0.0
# States a user may pull forward with "kuyruk çalıştır"; never cancelled/done.
RUN_NOW_STATES=frozenset({'queued','paused','blocked'})
# Workers that never call a model (research/writer do).
SCRIPT_AGENTS=frozenset({'account','verify','media'})


def set_daily_notify(callback):
    """Register one lightweight engine-owned daily hook on the existing scheduler thread."""
    global _DAILY_NOTIFY, _DAILY_NEXT
    if callback is not None and not callable(callback):
        raise ValueError('Günlük bildirim callback geçersiz.')
    _DAILY_NOTIFY=callback
    _DAILY_NEXT=0.0


def enqueue(owner, tasks, instruction='', delay=0, repeat_seconds=0, cron=''):
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
    cron = cron.strip() if isinstance(cron, str) else ''
    schedule = CronExpression(cron) if cron else None
    if schedule and (delay or repeat_seconds):
        raise ValueError('Cron görevi gecikme veya saniye tekrarıyla birlikte kullanılamaz.')
    qid=uuid.uuid4().hex[:16];job_id=uuid.uuid4().hex[:12]
    due = schedule.next_after(datetime.now()).timestamp() if schedule else time.time()+delay
    with service_store.database(owner) as db:
        db.execute('INSERT INTO queue(id,tasks,instruction,due,state,job_id,created,error,repeat_seconds,cron) VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (qid,service_store.encode(tasks),instruction,due,'queued',job_id,time.time(),'',repeat_seconds,cron))
    return qid


def rows(owner):
    with service_store.database(owner) as db:
        return [dict(row) for row in db.execute('SELECT id,state,due,job_id,error,repeat_seconds,last_job_id,cron,instruction FROM queue ORDER BY created DESC LIMIT 50')]

def render_rows(items):
    from modules import privacy
    if not items:return 'Zamanlanmış görevin yok.'
    labels={'paused':'Duraklatıldı; yeniden açılana kadar çalışmaz','running':'Çalışıyor','done':'Tamamlandı','cancelled':'İptal edildi','blocked':'Durdu; görev sonucunu incele'}
    lines=[]
    for row in items:
        remaining=max(0,math.ceil(row['due']-time.time()))
        status=(f'{remaining} saniye sonra başlayacak' if remaining else 'Zamanı geldi; çalışma sırasını bekliyor') if row['state']=='queued' else labels.get(row['state'],'Durum bilinmiyor')
        text=privacy.redact(row.get('instruction','')).strip() or 'Zamanlanmış görev'
        result_id=row.get('last_job_id') if row['state']=='queued' else row['job_id']
        cadence = ('\nCron: '+row['cron'] if row.get('cron') else
                   (f"\nHer {row['repeat_seconds']} saniyede tekrar eder." if row['repeat_seconds'] else ''))
        run_now = '\nŞimdi çalıştır: kuyruk çalıştır '+row['id'] if row['state'] in RUN_NOW_STATES else ''
        lines.append(text+'\nDurum: '+status+cadence+
                     ('\nSonuç: görev durumu '+result_id if result_id else '\nSonuç, iş çalıştıktan sonra oluşacak.')+run_now+'\nİptal: kuyruk iptal '+row['id'])
    return '\n\n'.join(lines)



def run_now(owner, qid):
    """Put one waiting schedule at the front without changing its definition.

    Cancelled or finished one-shot entries are never revived.
    """
    with service_store.database(owner) as db:
        row = db.execute('SELECT * FROM queue WHERE id=?', (qid,)).fetchone()
        if not row:
            raise ValueError('Bu kullanıcıya ait kuyruk işi yok.')
        if row['state'] == 'running':
            raise ValueError('Görev zaten çalışıyor; ikinci bir çalışma başlatılmadı.')
        if row['state'] not in RUN_NOW_STATES:
            raise ValueError('İptal edilmiş veya bitmiş iş yeniden başlatılmaz; yeni görev olarak zamanla.')
        new_job_id = uuid.uuid4().hex[:12]
        db.execute(
            "UPDATE queue SET state='queued',due=?,job_id=?,last_job_id=?,error='',lease=0,lease_token='' WHERE id=?",
            (time.time(), new_job_id, row['job_id'], qid),
        )
    return qid


def enqueue_script(owner, tasks, instruction='', cron=''):
    """Queue an explicit task DAG that never calls a planner or a model.

    Only model-free workers are accepted, so every run is a clean,
    deterministic script run with no chat history.
    """
    if not isinstance(tasks, list) or any(not isinstance(t, dict) or t.get('agent') not in SCRIPT_AGENTS for t in tasks):
        raise ValueError('Modelsiz betik görevi yalnız ' + ', '.join(sorted(SCRIPT_AGENTS)) + ' adımlarını içerebilir.')
    return enqueue(owner, tasks, instruction or 'Modelsiz betik görevi', cron=cron)


def cancel(owner,qid):
    with service_store.database(owner) as db:
        row=db.execute('SELECT * FROM queue WHERE id=?',(qid,)).fetchone()
        if not row:raise ValueError('Bu kullanıcıya ait kuyruk işi yok.')
        db.execute("UPDATE queue SET state='cancelled',lease=0,lease_token='' WHERE id=? AND state IN ('queued','running','blocked','paused')",(qid,))
    from modules import task_agents
    if row['state']=='running':
        try:task_agents.cancel_job(owner,row['job_id'])
        except ValueError:pass


def configure(owner,qid,*,operation,repeat_seconds=None):
    """Edit only idle queue entries under the existing transaction/lease boundary."""
    if operation not in {'pause','resume','interval'}:raise ValueError('Takip işlemi geçersiz.')
    if operation=='interval' and (type(repeat_seconds) is not int or repeat_seconds!=0 and not 300<=repeat_seconds<=30*86400):
        raise ValueError('Tekrar aralığı en az 300 saniye olmalı; 0 tek seferdir.')
    with service_store.database(owner) as db:
        row=db.execute('SELECT * FROM queue WHERE id=?',(qid,)).fetchone()
        if not row:raise ValueError('Bu kullanıcıya ait takip yok.')
        if row['state'] not in {'queued','paused'}:raise ValueError('Yalnız bekleyen veya duraklatılmış takip düzenlenebilir; çalışan işi önce bitir veya iptal et.')
        if operation=='pause':
            db.execute("UPDATE queue SET state='paused',lease=0,lease_token='' WHERE id=?",(qid,))
        elif operation=='resume':
            if row['state']!='paused':raise ValueError('Takip zaten sırada.')
            db.execute("UPDATE queue SET state='queued',due=?,lease=0,lease_token='' WHERE id=?",(time.time(),qid))
        else:
            db.execute('UPDATE queue SET repeat_seconds=? WHERE id=?',(repeat_seconds,qid))
    return True


def tick(owner, notify=None):
    """One atomic queue claim per run; old wakeups cannot finalize a successor.

    This is the existing Scheduler's durable queue fence, not the separate
    canonical DAG ResourceLease. A lost claim cannot write a successful queue
    result. Workers must still obey their existing cancellation/effect gates.
    """
    from modules import task_agents
    service_store.identity(owner)
    with task_agents._LOCK:
        if owner in task_agents._ACTIVE:
            return
    now = time.time()
    claim = secrets.token_hex(16)
    with service_store.database(owner) as db:
        row = db.execute(
            "SELECT * FROM queue WHERE (state='queued' AND due<=?) "
            "OR (state='running' AND lease<=?) ORDER BY due LIMIT 1",
            (now, now),
        ).fetchone()
        if not row:
            return
        row = dict(row)
        # database() holds BEGIN IMMEDIATE from selection through the claim.
        # Still require the exact job and ready state to prevent replay.
        changed = db.execute(
            "UPDATE queue SET state='running',lease=?,lease_token=? "
            "WHERE id=? AND job_id=? AND "
            "((state='queued' AND due<=?) OR (state='running' AND lease<=?))",
            (now + 90, claim, row['id'], row['job_id'], now, now),
        ).rowcount
        if changed != 1:
            return

    heartbeat_stop = threading.Event()
    lost = threading.Event()

    def heartbeat():
        token = llm._key_context.set(owner)
        try:
            while not heartbeat_stop.wait(20):
                instant = time.time()
                with service_store.database(owner) as db:
                    renewed = db.execute(
                        "UPDATE queue SET lease=? WHERE id=? AND job_id=? "
                        "AND state='running' AND lease_token=? AND lease>?",
                        (instant + 90, row['id'], row['job_id'], claim, instant),
                    ).rowcount
                if renewed != 1:
                    lost.set()
                    return
        except Exception:
            _record_failure('modules/task_queue.py:heartbeat')
            lost.set()
        finally:
            llm._key_context.reset(token)

    pulse = threading.Thread(target=heartbeat, daemon=True, name='task-lease')
    pulse.start()
    try:
        # A cancel/run-now/reclaimed lease that arrives before the worker starts
        # must not invoke any worker, even if the original SELECT was valid.
        with service_store.database(owner) as db:
            still_owned = db.execute(
                "SELECT 1 FROM queue WHERE id=? AND job_id=? "
                "AND state='running' AND lease_token=? AND lease>?",
                (row['id'], row['job_id'], claim, time.time()),
            ).fetchone()
        if not still_owned or lost.is_set():
            return
        tasks = json.loads(row['tasks'])
        task_agents.validate(tasks)
        if any(t['agent'] not in ('research', 'writer', 'account', 'verify', 'media') for t in tasks):
            raise ValueError('Kuyruk planı güvenli araç sınırını aşıyor.')
        # Preserve the assigned journal identity across restart; never create
        # a second job from an expired wake if its journal already exists.
        path = task_agents._job_path(task_agents._root(owner), row['job_id'])
        if path.exists():
            job = task_agents.continue_job(
                owner, row['job_id'], queue_id=row['id'], queue_tasks=tasks,
            )
        else:
            job = task_agents.execute(
                owner, tasks, row['instruction'],
                job_id=row['job_id'], queue_id=row['id'],
            )
        state = 'done' if job['state'] == 'done' else 'cancelled' if job['state'] == 'cancelled' else 'blocked'
        error = ''
    except task_agents.Busy:
        # Retry only if THIS claim still owns the exact scheduled run.
        heartbeat_stop.set()
        with service_store.database(owner) as db:
            db.execute(
                "UPDATE queue SET state='queued',lease=0,lease_token='' "
                "WHERE id=? AND job_id=? AND state='running' AND lease_token=? AND lease>?",
                (row['id'], row['job_id'], claim, time.time()),
            )
        return
    except Exception as exc:
        _record_failure('modules/task_queue.py:tick')
        state = 'blocked'
        error = type(exc).__name__
    finally:
        heartbeat_stop.set()

    if lost.is_set():
        # A timed-out or stolen claim never announces success. Recovery will
        # recheck the same durable job journal on a later scheduler wake.
        return
    with service_store.database(owner) as db:
        count = db.execute(
            "UPDATE queue SET state=?,error=?,lease=0,lease_token='' "
            "WHERE id=? AND job_id=? AND state='running' AND lease_token=? AND lease>?",
            (state, error, row['id'], row['job_id'], claim, time.time()),
        ).rowcount
        if count:
            db.execute(
                'INSERT OR IGNORE INTO queue_runs VALUES(?,?,?,?)',
                (row['id'], row['job_id'], state, time.time()),
            )
            if state in ('done', 'blocked') and row['cron']:
                next_due = CronExpression(row['cron']).next_after(datetime.now()).timestamp()
                db.execute(
                    "UPDATE queue SET state='queued',due=?,job_id=?,last_job_id=?,lease=0,lease_token='' "
                    "WHERE id=? AND state IN ('done','blocked')",
                    (next_due, uuid.uuid4().hex[:12], row['job_id'], row['id']),
                )
            elif state == 'done' and row['repeat_seconds']:
                db.execute(
                    "UPDATE queue SET state='queued',due=?,job_id=?,last_job_id=?,lease=0,lease_token='' "
                    "WHERE id=? AND state='done'",
                    (time.time() + row['repeat_seconds'], uuid.uuid4().hex[:12],
                     row['job_id'], row['id']),
                )
    if notify and count:
        notify(owner, row['id'], state, row['job_id'])


def is_cancelled(owner,qid):
    with service_store.database(owner) as db:
        row=db.execute('SELECT state FROM queue WHERE id=?',(qid,)).fetchone()
        return not row or row['state']=='cancelled'


def start(stop_event, notify=None, allowed_owners=None, source_notify=None):
    """One engine-owned worker; no boot-time model/network call without queued work."""
    global _THREAD
    with _START_LOCK:
        if _THREAD and _THREAD.is_alive():return
        def loop():
            global _DAILY_NEXT
            while not stop_event.wait(5):
                now=time.time()
                if _DAILY_NOTIFY is not None and now>=_DAILY_NEXT:
                    _DAILY_NEXT=now+60
                    try:_DAILY_NOTIFY()
                    except Exception:_record_failure('modules/task_queue.py:daily_notify')
                if not service_store.ROOT.exists():continue
                for path in sorted(service_store.ROOT.glob('*.sqlite3')):
                    if stop_event.is_set():return
                    if allowed_owners is not None and path.stem not in allowed_owners():continue
                    token=llm._key_context.set(path.stem)
                    from modules import outbox,task_agents,privacy
                    try:
                        tick(path.stem,notify)
                        from modules import source_watch
                        source_watch.poll(path.stem,source_notify)
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

