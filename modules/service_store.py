"""User-scoped transactional journals for outbound work and scheduling."""
from contextlib import contextmanager
import json
import re
import sqlite3
from config import DATA_DIR
from modules import requests_state

ROOT = DATA_DIR / 'service_work'


def identity(owner):
    from modules import llm
    if not isinstance(owner, str) or not re.fullmatch(r'[\w-]{1,100}', owner) or llm._key_context.get() != owner:
        raise PermissionError('İşlem için açık kullanıcı bağlamı gerekli.')
    request = requests_state._current.get()
    if request is not None and request[0] != owner:
        raise PermissionError('İşlem ve istek kullanıcısı eşleşmiyor.')


@contextmanager
def database(owner):
    identity(owner)
    ROOT.mkdir(parents=True, exist_ok=True)
    if ROOT.is_symlink():
        raise ValueError('İşlem klasörü sembolik bağ olamaz.')
    path = ROOT / (owner + '.sqlite3')
    if any(path.with_name(path.name + suffix).is_symlink() for suffix in ('', '-journal', '-wal', '-shm')):
        raise ValueError('İşlem kaydı sembolik bağ olamaz.')
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA synchronous=FULL')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS grants(service TEXT, destination TEXT, expires REAL, PRIMARY KEY(service,destination));
        CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, work_key TEXT UNIQUE, payload TEXT, digest TEXT,
          state TEXT, created REAL, updated REAL, receipt TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS queue(id TEXT PRIMARY KEY, tasks TEXT, instruction TEXT, due REAL,
          state TEXT, job_id TEXT, created REAL, error TEXT, lease REAL DEFAULT 0);
        ''')
        if 'lease' not in [row[1] for row in db.execute('PRAGMA table_info(queue)')]:
            db.execute('ALTER TABLE queue ADD COLUMN lease REAL DEFAULT 0')
        columns=[row[1] for row in db.execute('PRAGMA table_info(queue)')]
        if 'repeat_seconds' not in columns:db.execute('ALTER TABLE queue ADD COLUMN repeat_seconds INTEGER DEFAULT 0')
        if 'last_job_id' not in columns:db.execute("ALTER TABLE queue ADD COLUMN last_job_id TEXT DEFAULT ''")
        db.execute('CREATE TABLE IF NOT EXISTS queue_runs(qid TEXT,job_id TEXT PRIMARY KEY,state TEXT,finished REAL)')
        if 'authorized_until' not in [row[1] for row in db.execute('PRAGMA table_info(outbox)')]:
            db.execute('ALTER TABLE outbox ADD COLUMN authorized_until REAL DEFAULT 0')
        db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
