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

def register(user, rid, seconds=90):
    key = (user, rid)
    with _lock:
        if key in _records or _archived(key):
            return False
        # Completed/cancelled identifiers remain tombstones: retries never apply again.
        _records[key] = {'state': 'queued', 'deadline': time.monotonic()+seconds}
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


def cancel(user, rid=None):
    with _lock:
        for key, record in _records.items():
            if key[0] == user and (rid is None or key[1] == rid) and record['state'] in ('queued','running'):
                record['state'] = 'cancelled'
        _save_terminal_state()

@contextmanager
def activate(user, rid, *, complete=True):
    token = _current.set((user,rid))
    try:
        check()
        with _lock:
            if (user,rid) in _records:
                _records[(user,rid)]['state'] = 'running'
        yield
    finally:
        try:
            with _lock:
                record = _records.get((user,rid))
                if record and record['state'] == 'running':
                    # Transcription hands this same request back to the queue.
                    record['state'] = 'done' if complete else 'queued'
                    _save_terminal_state()
        finally:
            _current.reset(token)

def check():
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

def is_cancelled(user,rid):
    with _lock:
        record=_records.get((user,rid))
        return bool(record and (record['state']=='cancelled' or time.monotonic()>=record['deadline'])) or (record is None and _archived((user,rid)))
