"""User-scoped transactional journals for outbound work and scheduling."""
from contextlib import contextmanager
import json
import re
import sqlite3
from config import DATA_DIR
from modules import requests_state

ROOT = DATA_DIR / 'service_work'

# Durable per-file schema version, not a process-local or owner-scoped cache.
# Old files are version 0. Migrations happen once under the same SQLite writer
# lock as queue claims, including when two Jarvis processes start together.
_SCHEMA_VERSION = 1


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
        # Preserve BEGIN IMMEDIATE for atomic lease/claim operations. The
        # old hot path also executed three CREATEs and multiple table scans on
        # *every* read/write. A durable schema version skips that redundant
        # work while retaining the exact transaction and owner fences.
        observed_version = db.execute('PRAGMA user_version').fetchone()[0]
        if observed_version > _SCHEMA_VERSION:
            raise ValueError('İşlem veritabanı bu sürümden yeni; eski uygulamayla açılamaz.')
        db.execute('BEGIN IMMEDIATE')
        # Re-check AFTER acquiring the write lock: a separate process may
        # have completed the same migration while this one was waiting.
        current_version = db.execute('PRAGMA user_version').fetchone()[0]
        if current_version > _SCHEMA_VERSION:
            raise ValueError('İşlem veritabanı şeması desteklenmiyor.')
        if current_version < _SCHEMA_VERSION:
            # executescript() implicitly commits an open SQLite transaction:
            # use individual statements to make DDL + migration + version
            # marker one atomic commit, even during concurrent startup.
            db.execute('CREATE TABLE IF NOT EXISTS grants(service TEXT, destination TEXT, expires REAL, PRIMARY KEY(service,destination))')
            db.execute('''CREATE TABLE IF NOT EXISTS outbox(
                id TEXT PRIMARY KEY, work_key TEXT UNIQUE, payload TEXT, digest TEXT,
                state TEXT, created REAL, updated REAL, receipt TEXT, error TEXT)''')
            db.execute('''CREATE TABLE IF NOT EXISTS queue(
                id TEXT PRIMARY KEY, tasks TEXT, instruction TEXT, due REAL,
                state TEXT, job_id TEXT, created REAL, error TEXT,
                lease REAL DEFAULT 0, lease_token TEXT DEFAULT '', cron TEXT DEFAULT '')''')
            queue_columns = {row[1] for row in db.execute('PRAGMA table_info(queue)')}
            for column, ddl in (
                ('lease', 'ALTER TABLE queue ADD COLUMN lease REAL DEFAULT 0'),
                ('lease_token', "ALTER TABLE queue ADD COLUMN lease_token TEXT DEFAULT ''"),
                ('repeat_seconds', 'ALTER TABLE queue ADD COLUMN repeat_seconds INTEGER DEFAULT 0'),
                ('last_job_id', "ALTER TABLE queue ADD COLUMN last_job_id TEXT DEFAULT ''"),
                ('cron', "ALTER TABLE queue ADD COLUMN cron TEXT DEFAULT ''"),
            ):
                if column not in queue_columns:
                    db.execute(ddl)
            db.execute('CREATE TABLE IF NOT EXISTS queue_runs(qid TEXT,job_id TEXT PRIMARY KEY,state TEXT,finished REAL)')
            outbox_columns = {row[1] for row in db.execute('PRAGMA table_info(outbox)')}
            for column, ddl in (
                ('authorized_until', 'ALTER TABLE outbox ADD COLUMN authorized_until REAL DEFAULT 0'),
                ('approval_expires', 'ALTER TABLE outbox ADD COLUMN approval_expires REAL DEFAULT 0'),
                ('approval_consumed', 'ALTER TABLE outbox ADD COLUMN approval_consumed REAL DEFAULT 0'),
                ('connection_digest', "ALTER TABLE outbox ADD COLUMN connection_digest TEXT DEFAULT ''"),
            ):
                if column not in outbox_columns:
                    db.execute(ddl)
            # Written inside the same transaction as schema changes. A crash
            # rolls back both; stale/unknown schema never claims to be ready.
            db.execute(f'PRAGMA user_version = {_SCHEMA_VERSION}')
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
