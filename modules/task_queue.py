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
# Admission must fail once engine shutdown begins, even while the old
# scheduler OS thread is still alive and draining its current iteration.
_SCHEDULER_STOP_EVENT=None
# One bounded pool of scheduled owner executions, owned by the existing
# scheduler loop. No second task poller or GoalState writer.
_OWNER_TICKS={}
_LAST_ADMITTED={}
# Read-only canonical workers belong to this same scheduler loop, not another
# background poller. One owner may run at least three independent jobs while
# a fourth global slot is reserved for another owner under sustained load.
_CANONICAL_WORKERS={}
# A recovered completion is attempted once per Scheduler process/snapshot.
# No repeated model billing every five seconds on semantic rejection/failure.
_CANONICAL_RESUME_ATTEMPTED=set()
_LAST_CANONICAL_ADMITTED={}
_MAX_CANONICAL_WORKERS=4
_MAX_CANONICAL_PER_OWNER=3
# Soft timeout for each read-only worker. Expiry fences Core CAS but cannot
# forcibly abort a provider call; keep its OS resource claim until return.
_CANONICAL_WORKER_DEADLINE_SECONDS=300
_MAX_OWNER_WORKERS=3
_DAILY_NOTIFY=None
_DAILY_NEXT=0.0
_DAILY_NOTIFY_THREAD=None
# A single admission wake belongs to the existing Scheduler; there is no
# second poller/worker. Wake is best-effort after a durable commit and NEVER
# bypasses per-owner Core leases, request cancellation or planner fences.
_SCHEDULER_WAKE=threading.Event()
_SCHEDULER_TICK_SECONDS=5.0


def wake_scheduler():
    """Request a prompt rescan of the one Scheduler after journal commit."""
    _SCHEDULER_WAKE.set()


def _wait_for_scheduler_tick(stop_event):
    """Wake on durable admission or a finished worker without polling disk.

    A worker must actually EXIT before its pool slot is reusable. The former
    five-second scan made a completed first worker and a queued second step
    wait for another tick; probing only up to seven OS thread states is cheap
    and never releases the in-flight claim of a still-running provider.
    """
    deadline=time.monotonic()+_SCHEDULER_TICK_SECONDS
    while not stop_event.is_set():
        left=deadline-time.monotonic()
        if left<=0:
            return not stop_event.is_set()
        if _SCHEDULER_WAKE.wait(timeout=min(0.25,left)):
            _SCHEDULER_WAKE.clear()
            return not stop_event.is_set()
        if (any(not worker.is_alive() for worker in tuple(_CANONICAL_WORKERS.values()))
                or any(not worker.is_alive() for worker in tuple(_OWNER_TICKS.values()))):
            return not stop_event.is_set()
    return False

# States a user may pull forward with "kuyruk çalıştır"; never cancelled/done.
RUN_NOW_STATES=frozenset({'queued','paused'})
# Workers that never call a model (research/writer do).
SCRIPT_AGENTS=frozenset({'account','verify','media'})


def _quarantine_expired_workers():
    """Journal overdue attempts without dropping a live thread or its claims."""
    from modules import canonical_scheduler_dispatch
    for worker in tuple(_CANONICAL_WORKERS.values()):
        lifecycle = getattr(worker, '_canonical_lifecycle', None)
        if not worker.is_alive() or not isinstance(lifecycle, dict) or lifecycle.get('quarantined'):
            continue
        deadline = lifecycle.get('deadline')
        offer = lifecycle.get('offer')
        if deadline is None or deadline.stop_reason() != 'worker_deadline' or offer is None:
            continue
        selected = offer.selection
        try:
            canonical_scheduler_dispatch._record_failed_if_unaccepted(
                selected.owner, selected.job_id, selected.node_id,
                plan_version=selected.plan_version, node_digest=selected.node_digest,
                deadline_expired=True, provider_still_running=True)
            lifecycle['quarantined'] = True
        except Exception:
            _record_failure('modules/task_queue.py:quarantine_overdue')


def set_daily_notify(callback):
    """Register one lightweight engine-owned daily hook; the scheduler dispatches it
    on its own daemon thread so a slow mail/plan source never delays goal admission."""
    global _DAILY_NOTIFY, _DAILY_NEXT
    if callback is not None and not callable(callback):
        raise ValueError('Günlük bildirim callback geçersiz.')
    _DAILY_NOTIFY=callback
    _DAILY_NEXT=0.0


def _dispatch_daily_notify(now):
    """Fire the due daily hook off the scheduler thread: one in-flight at a time,
    the 60-second throttle and the recorded-failure channel are unchanged."""
    global _DAILY_NEXT, _DAILY_NOTIFY_THREAD
    callback=_DAILY_NOTIFY
    if callback is None or now<_DAILY_NEXT:return False
    if _DAILY_NOTIFY_THREAD is not None and _DAILY_NOTIFY_THREAD.is_alive():return False
    _DAILY_NEXT=now+60
    def run():
        try:callback()
        except Exception:_record_failure('modules/task_queue.py:daily_notify')
    _DAILY_NOTIFY_THREAD=threading.Thread(target=run,daemon=True,name='jarvis-daily-notify')
    _DAILY_NOTIFY_THREAD.start()
    return True


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
    wake_scheduler()
    return qid


def rows(owner):
    with service_store.database(owner) as db:
        return [dict(row) for row in db.execute('SELECT id,state,due,job_id,error,repeat_seconds,last_job_id,cron,instruction FROM queue ORDER BY created DESC LIMIT 50')]

def render_rows(items):
    from modules import privacy
    if not items:return 'Zamanlanmış görevin yok.'
    labels={'paused':'Duraklatıldı; yeniden açılana kadar çalışmaz','running':'Çalışıyor','done':'Tamamlandı','cancelled':'İptal edildi','blocked':'Durdu; sonucu incele. Belirsiz yürütme otomatik veya doğrudan tekrar başlatılmaz'}
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

    Cancelled, blocked or finished entries are never revived: blocked may
    contain a started-but-unknown effect and needs explicit reconciliation.
    """
    with service_store.database(owner) as db:
        row = db.execute('SELECT * FROM queue WHERE id=?', (qid,)).fetchone()
        if not row:
            raise ValueError('Bu kullanıcıya ait kuyruk işi yok.')
        if row['state'] == 'running':
            raise ValueError('Görev zaten çalışıyor; ikinci bir çalışma başlatılmadı.')
        if row['state'] not in RUN_NOW_STATES:
            raise ValueError('İptal, blocked veya bitmiş iş güvenli yeni deneme sayılmaz; önce eski sonucu incele, sonra yeni görev oluştur.')
        new_job_id = uuid.uuid4().hex[:12]
        db.execute(
            "UPDATE queue SET state='queued',due=?,job_id=?,last_job_id=?,error='',lease=0,lease_token='' WHERE id=?",
            (time.time(), new_job_id, row['job_id'], qid),
        )
    wake_scheduler()
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
    if operation == 'resume':
        wake_scheduler()
    return True


def _stop_queue_heartbeat_without_voice_block(stop, pulse, lost):
    """Bound daemon cleanup; never mark an ambiguously live claim completed."""
    stop.set()
    pulse.join(timeout=1.0)
    if pulse.is_alive():
        lost.set()
        _record_failure('modules/task_queue.py:heartbeat_cleanup_busy')
        return False
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
        marker = task_agents._QUEUE_CLAIM.set(
            (owner, row['id'], row['job_id'], claim),
        )
        from modules import requests_state
        def check_queue_generation():
            # Before NEXT external/model/read step, the durable SQLite claim
            # must still own this exact queue generation. The existing journal
            # CAS remains the final fence; this is only cooperative cancellation.
            if lost.is_set():
                raise requests_state.Cancelled('Queue heartbeat lost its owner.')
            with service_store.database(owner) as db:
                valid = db.execute(
                    "SELECT 1 FROM queue WHERE id=? AND job_id=? AND "
                    "state='running' AND lease_token=? AND lease>?",
                    (row['id'], row['job_id'], claim, time.time()),
                ).fetchone()
            if valid is None:
                raise requests_state.Cancelled('Queue claim changed before next action.')
        try:
            with requests_state.worker_probe(check_queue_generation):
                if path.exists():
                    job = task_agents.continue_job(
                        owner, row['job_id'], queue_id=row['id'], queue_tasks=tasks,
                    )
                else:
                    job = task_agents.execute(
                        owner, tasks, row['instruction'],
                        job_id=row['job_id'], queue_id=row['id'],
                    )
        finally:
            task_agents._QUEUE_CLAIM.reset(marker)
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
        # Ordinary heartbeat exits before this bound; a hung SQLite/transport
        # heartbeat must never hold the foreground voice lane forever. Keep
        # the queue claim unresolved if it has not exited; old claim expires
        # and the journal is reconciled, never blindly replayed.
        _stop_queue_heartbeat_without_voice_block(
            heartbeat_stop, pulse, lost,
        )

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
            # A failed or unknown attempt must not spawn a fresh timed
            # command merely because its CRON interval advanced.
            if state == 'done' and row['cron']:
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


def scheduler_active():
    """True only when the existing engine-owned poll loop is live."""
    with _START_LOCK:
        return bool(_THREAD is not None and _THREAD.is_alive()
                    and _SCHEDULER_STOP_EVENT is not None
                    and not _SCHEDULER_STOP_EVENT.is_set())


def start(stop_event, notify=None, allowed_owners=None, source_notify=None,
          canonical_profile_resolver=None, canonical_result_notify=None,
          canonical_plan_notify=None):
    """One engine-owned scheduler loop, dispatching bounded owner workers.

    Queue workers use tick() and its existing SQLite claim. Optional canonical
    workers use the same poll loop, pinned profiles, and the existing Core
    ResourceLease/WorkerResult fences. Voice is never serialized behind them.
    """
    global _THREAD, _SCHEDULER_STOP_EVENT
    with _START_LOCK:
        if _THREAD and _THREAD.is_alive():return
        _SCHEDULER_STOP_EVENT = stop_event

        def admit_owner(owner):
            # The only scheduler thread owns this registry. An owner may not
            # have two live tick() executions even across consecutive polls.
            for name, worker in tuple(_OWNER_TICKS.items()):
                if not worker.is_alive():
                    _OWNER_TICKS.pop(name, None)
            if owner in _OWNER_TICKS or len(_OWNER_TICKS) >= _MAX_OWNER_WORKERS:
                return False

            def work():
                from modules import task_agents
                token=llm._key_context.set(owner)
                try:
                    if not stop_event.is_set():
                        tick(owner, notify)
                except task_agents.Busy:
                    # A user-owned synchronous job has the same owner.
                    pass
                except Exception:
                    _record_failure('modules/task_queue.py:owner_tick')
                finally:
                    llm._key_context.reset(token)

            worker=threading.Thread(
                target=work, daemon=True, name='jarvis-task-owner-'+owner[:30],
            )
            _OWNER_TICKS[owner]=worker
            _LAST_ADMITTED[owner]=time.monotonic()
            worker.start()
            return True

        def admit_planning(owner, profile):
            """FIRST planning attempt uses the SAME owner pool and poll loop."""
            from modules import canonical_planning_queue
            for key, worker in tuple(_CANONICAL_WORKERS.items()):
                if not worker.is_alive():
                    _CANONICAL_WORKERS.pop(key, None)
            if (len(_CANONICAL_WORKERS) >= _MAX_CANONICAL_WORKERS
                    or sum(key[0] == owner for key in _CANONICAL_WORKERS)
                       >= _MAX_CANONICAL_PER_OWNER
                    or getattr(profile, "slug", None) != owner):
                return
            room = min(
                _MAX_CANONICAL_WORKERS - len(_CANONICAL_WORKERS),
                _MAX_CANONICAL_PER_OWNER -
                sum(key[0] == owner for key in _CANONICAL_WORKERS),
            )
            for job_id in canonical_planning_queue.discover(owner, max_results=min(3, room)):
                key = (owner, job_id, "__planning__", 1)
                if key in _CANONICAL_WORKERS:
                    continue

                def work(pinned_owner=owner, pinned_profile=profile, planned_job=job_id):
                    from modules import runtime_worker_result
                    token = llm._key_context.set(pinned_owner)
                    try:
                        if not stop_event.is_set():
                            deadline = runtime_worker_result.CanonicalWorkerDeadline(
                                stop_event, _CANONICAL_WORKER_DEADLINE_SECONDS)
                            result = canonical_planning_queue.execute(
                                pinned_profile, planned_job, stop_event=deadline)
                            if result in ("planned", "review") and canonical_plan_notify is not None:
                                canonical_plan_notify(pinned_owner, planned_job, result)
                    except Exception:
                        _record_failure("modules/task_queue.py:planning_dispatch")
                    finally:
                        llm._key_context.reset(token)

                worker = threading.Thread(
                    target=work, daemon=True,
                    name="jarvis-canonical-planner-" + owner[:16])
                _CANONICAL_WORKERS[key] = worker
                _LAST_CANONICAL_ADMITTED[owner] = time.monotonic()
                worker.start()

        def admit_canonical(owner, profile):
            from modules import canonical_scheduler_dispatch
            # The scheduler thread is the sole mutator of this thread registry.
            for key, worker in tuple(_CANONICAL_WORKERS.items()):
                if not worker.is_alive():
                    _CANONICAL_WORKERS.pop(key, None)
            if len(_CANONICAL_WORKERS) >= _MAX_CANONICAL_WORKERS:
                return
            active_here = sum(key[0] == owner for key in _CANONICAL_WORKERS)
            if active_here >= _MAX_CANONICAL_PER_OWNER:
                return
            # Never adopt the current foreground profile. A caller must
            # resolve a registered user and prove its immutable owner slug.
            if getattr(profile, 'slug', None) != owner:
                return
            for offer in canonical_scheduler_dispatch.discover(
                owner, max_offers=_MAX_CANONICAL_PER_OWNER - active_here,
            ):
                selected = offer.selection
                key = (owner, selected.job_id, selected.node_id, offer.attempt)
                if key in _CANONICAL_WORKERS:
                    continue
                if len(_CANONICAL_WORKERS) >= _MAX_CANONICAL_WORKERS:
                    break

                # Bind the pinned owner/profile at thread creation time.
                # The Scheduler can iterate another registered owner before
                # this new OS thread begins executing; late-bound locals must
                # never transplant one worker into another user's context.
                lifecycle = {'offer': offer, 'deadline': None, 'quarantined': False}
                def work(candidate=offer, pinned_owner=owner, pinned_profile=profile, lifecycle=lifecycle):
                    from modules import runtime_worker_result
                    token = llm._key_context.set(pinned_owner)
                    try:
                        if not stop_event.is_set():
                            # Each thread gets its own clock-based deadline.
                            # A stuck provider remains in the bounded pool;
                            # we never release an in-flight OS claim to launch
                            # a duplicate command or treat timeout as success.
                            deadline = runtime_worker_result.CanonicalWorkerDeadline(
                                stop_event, _CANONICAL_WORKER_DEADLINE_SECONDS,
                            )
                            lifecycle['deadline'] = deadline
                            completed = canonical_scheduler_dispatch.execute_offer(
                                pinned_profile, candidate, stop_event=deadline,
                            )
                            if completed and canonical_result_notify is not None:
                                # Keep this attempt's stop/deadline active until
                                # the semantic decision and owner event are fenced.
                                with runtime_worker_result.scheduler_stop_scope(deadline):
                                    canonical_result_notify(
                                        pinned_owner, candidate.selection.job_id,
                                    )
                    except Exception:
                        _record_failure('modules/task_queue.py:canonical_dispatch')
                    finally:
                        llm._key_context.reset(token)

                thread = threading.Thread(
                    target=work, daemon=True,
                    name='jarvis-canonical-'+owner[:16]+'-'+selected.node_id[:16],
                )
                _CANONICAL_WORKERS[key] = thread
                thread._canonical_lifecycle = lifecycle
                thread.start()
                # A registered owner with no recent admission goes first on
                # the next tick, even if earlier owners remain permanently busy.
                _LAST_CANONICAL_ADMITTED[owner] = time.monotonic()

        def admit_recovered_completion(owner):
            if canonical_result_notify is None or stop_event.is_set():
                return
            from modules import canonical_scheduler_dispatch
            for key, worker in tuple(_CANONICAL_WORKERS.items()):
                if not worker.is_alive():
                    _CANONICAL_WORKERS.pop(key, None)
            if (len(_CANONICAL_WORKERS) >= _MAX_CANONICAL_WORKERS
                    or sum(key[0] == owner for key in _CANONICAL_WORKERS)
                       >= _MAX_CANONICAL_PER_OWNER):
                return
            for candidate in canonical_scheduler_dispatch.recoverable_completions(
                    owner, max_results=1):
                key = (owner, candidate.job_id, '__canonical_completion__',
                       candidate.goal_version, candidate.record_digest)
                if (key in _CANONICAL_RESUME_ATTEMPTED
                        or any(active_key[0] == owner
                               and active_key[1] == candidate.job_id
                               for active_key in _CANONICAL_WORKERS)):
                    continue

                def recover(offer=candidate, pinned_owner=owner):
                    token = llm._key_context.set(pinned_owner)
                    try:
                        if not stop_event.is_set():
                            from modules import runtime_worker_result
                            # A restarted completion owns one bounded model
                            # attempt; it cannot re-execute a provider worker.
                            deadline = runtime_worker_result.CanonicalWorkerDeadline(
                                stop_event, _CANONICAL_WORKER_DEADLINE_SECONDS,
                            )
                            with runtime_worker_result.scheduler_stop_scope(deadline):
                                canonical_result_notify(pinned_owner, offer.job_id)
                    except Exception:
                        _record_failure('modules/task_queue.py:completion_recovery')
                    finally:
                        llm._key_context.reset(token)

                _CANONICAL_RESUME_ATTEMPTED.add(key)
                worker = threading.Thread(
                    target=recover, daemon=True,
                    name='jarvis-canonical-recover-'+owner[:16],
                )
                _CANONICAL_WORKERS[key] = worker
                worker.start()
                _LAST_CANONICAL_ADMITTED[owner] = time.monotonic()
                break

        def loop():
            while _wait_for_scheduler_tick(stop_event):
                # Only the one scheduler mutates these registries. Do not
                # free a slot until its OS thread is actually gone: a
                # quarantined/hung provider still occupies capacity.
                _quarantine_expired_workers()
                for registry in (_CANONICAL_WORKERS, _OWNER_TICKS):
                    for key, worker in tuple(registry.items()):
                        if not worker.is_alive():
                            registry.pop(key, None)
                now=time.time()
                _dispatch_daily_notify(now)
                # Canonical goals do not require a pre-existing SQLite queue.
                # The existing Scheduler inspects registered users directly,
                # without creating a second owner poller or opening a DB.
                # A missing/foreign profile fails closed per owner.
                if (canonical_profile_resolver is not None
                        and allowed_owners is not None):
                    try:
                        registered = sorted(
                            allowed_owners(),
                            key=lambda name: (_LAST_CANONICAL_ADMITTED.get(name, 0.0), name),
                        )
                    except Exception:
                        _record_failure('modules/task_queue.py:canonical_owners')
                        registered = ()
                    for registered_owner in registered:
                        if stop_event.is_set():return
                        try:
                            profile = canonical_profile_resolver(registered_owner)
                            if getattr(profile, 'slug', None) == registered_owner:
                                admit_planning(registered_owner, profile)
                                admit_canonical(registered_owner, profile)
                                admit_recovered_completion(registered_owner)
                        except Exception:
                            _record_failure('modules/task_queue.py:canonical_owner')
                if not service_store.ROOT.exists():continue
                # Least-recently-admitted owners first; a busy owner cannot
                # starve a later owner when the bounded pool is saturated.
                owners=sorted(
                    service_store.ROOT.glob('*.sqlite3'),
                    key=lambda path: (_LAST_ADMITTED.get(path.stem, 0.0), path.stem),
                )
                for path in owners:
                    if stop_event.is_set():return
                    if allowed_owners is not None and path.stem not in allowed_owners():continue
                    token=llm._key_context.set(path.stem)
                    from modules import outbox,task_agents,privacy
                    try:
                        admit_owner(path.stem)
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
        # The first scan need not wait for the fallback five-second timer.
        # Especially important when the restart discovers already queued
        # canonical records that were committed while Jarvis was offline.
        wake_scheduler()

