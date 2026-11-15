"""User-bound command IDs, cancellation and cooperative request deadlines."""
from contextvars import ContextVar
from contextlib import contextmanager, closing
import threading
import time
import json
import os
import logging
import sqlite3
from config import DATA_DIR
_journal = DATA_DIR / "requests.json"

_lock = threading.RLock()
_TERMINAL_LIMIT = 512
try:
    _saved = json.loads(_journal.read_text(encoding="utf-8"))
    _records = {(r['user'], r['rid']): {'state': r['state'] if r['state'] in ('done','cancelled') else 'cancelled', 'deadline': 0} for r in _saved}
except (OSError, ValueError, KeyError, TypeError):
    _records = {}

def _archive_path():
    return _journal.with_suffix('.archive.sqlite3')

def _archived(key):
    path = _archive_path()
    if not path.exists():
        return False
    try:
        with closing(sqlite3.connect(str(path), timeout=5)) as db:
            return db.execute('SELECT 1 FROM tombstones WHERE user=? AND rid=?', key).fetchone() is not None
    except sqlite3.Error as exc:
        # An unreadable deduplication index must not permit repeating old work.
        raise OSError('İstek kimliği arşivi okunamadı; işlem başlatılmadı.') from exc

def _save():
    now = time.monotonic()
    for record in _records.values():
        if record['state'] in ('queued', 'running') and record['deadline'] <= now:
            record['state'] = 'cancelled'
    terminal = [key for key, record in _records.items() if record['state'] in ('done', 'cancelled')]
    archived = terminal[:-_TERMINAL_LIMIT] if len(terminal) > _TERMINAL_LIMIT else []
    if archived:
        try:
            with closing(sqlite3.connect(str(_archive_path()), timeout=5)) as db, db:
                db.execute('CREATE TABLE IF NOT EXISTS tombstones (user TEXT NOT NULL, rid TEXT NOT NULL, PRIMARY KEY(user,rid)) WITHOUT ROWID')
                db.executemany('INSERT OR IGNORE INTO tombstones(user,rid) VALUES (?,?)', archived)
        except sqlite3.Error as exc:
            raise OSError('İstek kimlikleri güvenli arşivlenemedi.') from exc
    omitted = set(archived)
    rows = [{'user':k[0], 'rid':k[1], 'state':v['state']} for k,v in _records.items() if k not in omitted]
    tmp = _journal.with_suffix('.tmp')
    tmp.write_text(json.dumps(rows), encoding='utf-8')
    os.replace(tmp, _journal)
    # Commit the archive and replacement journal before discarding RAM entries.
    for key in archived:
        _records.pop(key, None)

def _save_terminal_state():
    # Already executed/cancelled work must stay blocked even if its journal is full.
    try:
        _save()
    except OSError:
        logging.getLogger(__name__).exception('İstek günlüğü yazılamadı; tamamlanan/iptal edilen kimlik bellekte korundu.')
_current = ContextVar('jarvis_request', default=None)
_budget_deadline = ContextVar('jarvis_budget_deadline', default=None)
_budget_cancel = ContextVar('jarvis_budget_cancel', default=None)
# The request layer cannot import Brain/Core; the canonical Scheduler may
# attach one additional cooperative stop/deadline callback for its worker
# thread. Every existing requests_state.check() then fences the next
# network/model/read step without replacing request cancellation authority.
_worker_probe = ContextVar('jarvis_worker_cooperative_probe', default=None)


@contextmanager
def worker_probe(callback):
    """Add an optional current-thread cooperative fence, never an authority."""
    if not callable(callback):
        raise ValueError('Worker probe must be callable.')
    token = _worker_probe.set(callback)
    try:
        yield
    finally:
        _worker_probe.reset(token)


@contextmanager
def budget(seconds, *, cancel=None):
    previous=_budget_deadline.get()
    deadline=time.monotonic()+seconds
    token=_budget_deadline.set(min(previous,deadline) if previous is not None else deadline)
    cancelled=_budget_cancel.set(cancel or _budget_cancel.get())
    try:yield
    finally:
        _budget_cancel.reset(cancelled)
        _budget_deadline.reset(token)


class Cancelled(RuntimeError):
    pass


class LocalDeadline(TimeoutError):
    """Yerel süre bütçesi doldu; sağlayıcı hatası değildir.

    TimeoutError alt sınıfıdır, böylece eski `except TimeoutError` yolları çalışmaya devam eder.
    Yanıt gelmiş olsa bile sonuç uygulanmaz; sağlayıcı bu yüzden cezalandırılmaz (cooldown yok).

    `local_deadline` işareti sınıflandırmanın sınıf adı eşleşmesine değil açık bir niteliğe
    dayanır: failure_policy bunu unknown saymaz, sağlayıcı zaman aşımı da saymaz."""
    local_deadline = True
    reason_code = 'LOCAL_DEADLINE_EXCEEDED'


def budget_remaining():
    """Etkin yerel bütçenin kalan saniyesi; bütçe yoksa None. Taşıma süresi bu sınırdan büyük olamaz."""
    deadline = _budget_deadline.get()
    return None if deadline is None else deadline - time.monotonic()


def request_identity(owner):
    key=_current.get()
    if key is None:return None
    if key[0]!=owner:raise PermissionError('Model isteği başka kullanıcının runtime bağlamında.')
    return key[1]

def register(user, rid, seconds=90, *, execution_seconds=None):
    """Register one request; optional queued wait is separate from its turn budget.

    A spoken/text request may sit behind a long foreground task. The wait
    allowance is finite, and its *execution* clock starts only after this
    request is actually activated. Background workers and existing callers
    without execution_seconds retain their original deadline contract.
    """
    if execution_seconds is not None and (
            type(execution_seconds) not in (int, float)
            or not 0 < execution_seconds <= 1800):
        raise ValueError('İstek yürütme süresi geçersiz.')
    key = (user, rid)
    with _lock:
        if key in _records or _archived(key):
            return False
        # Completed/cancelled identifiers remain tombstones: retries never apply again.
        record = {'state': 'queued', 'deadline': time.monotonic()+seconds}
        if execution_seconds is not None:
            record['execution_seconds'] = execution_seconds
        _records[key] = record
        try:
            _save()
        except BaseException:
            # Nothing was queued yet; allow the exact same ID after storage recovers.
            del _records[key]
            raise
    return True

def register_background(user, rid, seconds=90):
    """Queue cancellable work atomically with the parent's cancellation check."""
    with _lock:
        parent = _current.get()
        if parent is not None and parent[0] != user:
            raise ValueError('Arka plan görevi istek kullanıcısına ait olmalı.')
        check()
        return register(user, rid, seconds)


def cancel(user, rid):
    """Cancel only the explicitly identified owner-bound request.

    Omitting the request ID must never turn into a user-wide sweep.
    Canonical goals use their separate owner-bound job-ID control.
    """
    if not isinstance(rid, str) or not rid:
        raise ValueError('İptal için açık istek kimliği gerekli.')
    with _lock:
        record = _records.get((user, rid))
        if record is not None and record['state'] in ('queued', 'running'):
            record['state'] = 'cancelled'
            _save_terminal_state()


def cancel_foreground(user):
    """Cancel one actively executing foreground turn, never queued/background work.

    Only interactive engine activations set the transient foreground marker.
    Background Scheduler workers never set it. Ambiguity fails closed.
    Returns ("cancelled", rid), ("ambiguous", None), or ("none", None).
    """
    with _lock:
        now = time.monotonic()
        active = [key for key, record in _records.items()
                  if key[0] == user and record['state'] == 'running'
                  and record.get('foreground') is True
                  and record['deadline'] > now]
        if len(active) != 1:
            return ('ambiguous' if active else 'none'), None
        key = active[0]
        # A late model/engine reply must not restart the speech just interrupted.
        # Mark only this turn; never mute a background goal's later notice.
        _records[key]['speech'] = True
        _records[key]['state'] = 'cancelled'
        _save_terminal_state()
        return 'cancelled', key[1]


@contextmanager
def activate(user, rid, *, complete=True, foreground=False):
    token = _current.set((user,rid))
    try:
        check()
        with _lock:
            record = _records.get((user, rid))
            if record is not None:
                # check() above and this lock may be separated by another
                # thread's explicit cancellation. Never turn a cancelled or
                # timed-out record back into running by a late activation.
                now = time.monotonic()
                if record['state'] == 'cancelled' or now >= record['deadline']:
                    record['state'] = 'cancelled'
                    _save_terminal_state()
                    raise Cancelled('İstek iptal edildi veya bekleme süresi doldu.')
                if record['state'] == 'queued':
                    turn = record.pop('execution_seconds', None)
                    if turn is not None:
                        record['deadline'] = now + turn
                    record['state'] = 'running'
                if foreground and record['state'] == 'running':
                    record['foreground'] = True
        yield
    finally:
        try:
            with _lock:
                record = _records.get((user,rid))
                if record and record['state'] == 'running':
                    # Transcription hands this same request back to the queue.
                    record['state'] = 'done' if complete else 'queued'
                    _save_terminal_state()
                if foreground and record is not None:
                    record.pop('foreground', None)
        finally:
            _current.reset(token)

def check():
    probe = _worker_probe.get()
    if probe is not None:
        probe()
    cancelled=_budget_cancel.get()
    if cancelled is not None and cancelled.is_set():raise Cancelled('Model beklemesi bitti; yeni deneme başlatılmadı.')
    deadline=_budget_deadline.get()
    if deadline is not None and time.monotonic()>=deadline:
        raise LocalDeadline('Model bekleme süresi doldu; geç yanıt uygulanmadı.')
    key = _current.get()
    with _lock:
        record = _records.get(key)
        if record is None and key is not None and _archived(key):
            raise Cancelled('İstek tamamlandı veya iptal edildi; yeniden uygulanmadı.')
        if record and (record['state'] == 'cancelled' or time.monotonic() >= record['deadline']):
            record['state'] = 'cancelled'
            _save_terminal_state()
            raise Cancelled('İşlem iptal edildi veya süresi doldu; yeniden uygulanmadı.')


def allow_long_operation(seconds):
    """Extend only this active request, without reviving cancelled/expired work."""
    check()
    key = _current.get()
    with _lock:
        record = _records.get(key)
        if record and record['state'] == 'running':
            record['deadline'] = max(record['deadline'], time.monotonic() + min(1800, max(90, seconds)))

def request_state(user, rid):
    """Owner/RID-scoped read for a client waiting on a queued turn.

    A missing/tombstoned/expired record is never presented as still pending.
    This observation authorizes no execution or cancellation.
    """
    with _lock:
        key = (user, rid)
        record = _records.get(key)
        if record is not None:
            if (record['state'] in ('queued', 'running')
                    and time.monotonic() >= record['deadline']):
                return 'cancelled'
            return record['state']
        return 'cancelled' if _archived(key) else None


def is_cancelled(user,rid):
    with _lock:
        record=_records.get((user,rid))
        return bool(record and (record['state']=='cancelled' or time.monotonic()>=record['deadline'])) or (record is None and _archived((user,rid)))


def mute_speech(user, rid=None):
    """Speech-only mute for one request, or for all a user has in flight; returns their ids.

    This is deliberately NOT `cancel`: the command keeps running, Core keeps the
    written result and the GoalState, and only the audible presentation of those
    answers is dropped. Callers bound the scope with `rid` — "sus" mutes only the
    turn whose audio it stopped, so an unrelated background job keeps its future
    spoken result. Nothing is journaled — a mute belongs to the turn that asked for
    quiet, never to a restart.

    A named turn is muted even when its request already finished: the answer is
    marked `done` when the handler returns, while its audio can still be on the
    speaker for seconds after that. Tying the mute to the request lifecycle would
    let the next utterance of that very turn start speaking again after the user
    asked for quiet. The unscoped form keeps its original in-flight-only scope, so
    no finished request is ever marked by a sweep.
    """
    with _lock:
        muted = []
        for key, record in _records.items():
            if key[0] != user or record['state'] == 'cancelled':
                continue
            if rid is None:
                if record['state'] not in ('queued', 'running'):
                    continue
            elif key[1] != rid:
                continue
            record['speech'] = True
            muted.append(key[1])
        return tuple(muted)


def speech_muted(user, rid):
    """True once the user stopped speech for this exact request id."""
    if not rid:
        return False
    with _lock:
        return bool(_records.get((user, rid), {}).get('speech'))


_model_work_class = ContextVar('jarvis_model_work_class',default=None)


def model_work_class():
    return _model_work_class.get()


@contextmanager
def model_work_scope(value):
    if value not in ('interactive','background','explicit_custom'):raise ValueError('Model iş sınıfı geçersiz.')
    token=_model_work_class.set(value)
    try:yield
    finally:_model_work_class.reset(token)
