"""Durable RuntimeEvent subscriptions and source-event producer bridge."""
from __future__ import annotations

import hashlib
import re
import time
import uuid
from pathlib import Path

from config import DATA_DIR
from modules import core_state_reducer, goal_state_compat, goal_state_store, runtime_event, runtime_event_commit, service_store
from modules.diagnostics import record_failure as _record_failure


_OWNER = re.compile(r"[\w-]{1,100}\Z")


def _seen_path(owner: str, subscription_id: str) -> Path:
    if not _OWNER.fullmatch(owner):
        raise ValueError("Runtime Event sahibi geçersiz.")
    if not re.fullmatch(r"[a-f0-9]{16}", subscription_id):
        raise ValueError("Runtime Event abonelik kimliği geçersiz.")
    return DATA_DIR / "runtime_events" / owner / (subscription_id + ".json")


def _schema(db) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS runtime_subscriptions("
        "id TEXT PRIMARY KEY,source_event_key TEXT,source_generation INTEGER,"
        "subject_version INTEGER,resume_token TEXT,goal_state_path TEXT,job_id TEXT,"
        "step_id TEXT,fresh_after REAL,expected_job_version INTEGER,active INTEGER,"
        "created REAL,last_event_at REAL DEFAULT 0,error TEXT DEFAULT '')"
    )


def _subscription(row) -> dict:
    return {
        "source_event_key": row["source_event_key"],
        "source_generation": row["source_generation"],
        "subject_version": row["subject_version"],
        "resume_token": row["resume_token"],
        "fresh_after": row["fresh_after"],
    }


def subscribe(
    owner: str,
    source_event_key: str,
    *,
    goal_state_path,
    job_id: str,
    step_id: str = "",
    source_generation: int = 0,
    subject_version: int = 0,
    resume_token: str = "",
    fresh_after: float | None = None,
) -> str:
    """Create one durable source-to-GoalState subscription."""
    service_store.identity(owner)
    if not isinstance(source_event_key, str) or not source_event_key.strip():
        raise ValueError("Runtime Event kaynak anahtarı gerekli.")
    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("Runtime Event job kimliği gerekli.")
    if not isinstance(step_id, str) or len(step_id) > 100:
        raise ValueError("Runtime Event step kimliği geçersiz.")
    if type(source_generation) is not int or source_generation < 0:
        raise ValueError("Runtime Event kaynak nesli geçersiz.")
    if type(subject_version) is not int or subject_version < 0:
        raise ValueError("Runtime Event konu sürümü geçersiz.")
    path = Path(goal_state_path)
    state = goal_state_store.load(path)
    if state["owner"] != owner or state["job_id"] != job_id:
        raise ValueError("Runtime Event aboneliği GoalState kimliğiyle eşleşmiyor.")
    expected = state["version"]
    now = time.time()
    fresh_after = now if fresh_after is None else fresh_after
    if not isinstance(fresh_after, (int, float)) or isinstance(fresh_after, bool):
        raise ValueError("Runtime Event tazelik başlangıcı geçersiz.")
    token = resume_token or uuid.uuid4().hex
    if not isinstance(token, str) or not token:
        raise ValueError("Runtime Event resume token geçersiz.")
    ident = uuid.uuid4().hex[:16]
    with service_store.database(owner) as db:
        _schema(db)
        db.execute(
            "INSERT INTO runtime_subscriptions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ident, source_event_key.strip(), source_generation, subject_version, token,
             str(path), job_id, step_id, float(fresh_after), expected, 1, now, 0.0, ""),
        )
    return ident


def rows(owner: str, *, active_only: bool = False) -> list[dict]:
    service_store.identity(owner)
    with service_store.database(owner) as db:
        _schema(db)
        query = "SELECT * FROM runtime_subscriptions"
        if active_only:
            query += " WHERE active=1"
        query += " ORDER BY created DESC"
        return [dict(row) for row in db.execute(query)]


def close(owner: str, subscription_id: str) -> None:
    service_store.identity(owner)
    with service_store.database(owner) as db:
        _schema(db)
        if not db.execute(
            "UPDATE runtime_subscriptions SET active=0 WHERE id=?",
            (subscription_id,),
        ).rowcount:
            raise ValueError("Bu kullanıcıya ait Runtime Event aboneliği yok.")


def _source_state_path(owner: str, source_event_key: str) -> tuple[Path, str]:
    if not _OWNER.fullmatch(owner):
        raise ValueError("Runtime Event sahibi geçersiz.")
    digest = hashlib.sha256(source_event_key.encode("utf-8")).hexdigest()[:16]
    job_id = "source-" + digest
    return DATA_DIR / "runtime_events" / owner / (job_id + ".goalstate.json"), job_id


def ensure_source(owner: str, source_event_key: str, *, goal: str, fresh_after: float) -> str:
    """Idempotently open the canonical GoalState + subscription for one live source.

    Production producers (source watch, event webhooks) call this before
    publishing so every real source has exactly one active subscription.
    """
    service_store.identity(owner)
    if not isinstance(source_event_key, str) or not source_event_key.strip():
        raise ValueError("Runtime Event kaynak anahtarı gerekli.")
    with service_store.database(owner) as db:
        _schema(db)
        row = db.execute(
            "SELECT id FROM runtime_subscriptions WHERE active=1 AND source_event_key=? ORDER BY created LIMIT 1",
            (source_event_key,),
        ).fetchone()
    if row:
        return row["id"]
    path, job_id = _source_state_path(owner, source_event_key)
    state = goal_state_compat.open_subscription_state(path, owner=owner, job_id=job_id, goal=goal)
    if state["state"] in {"done", "cancelled"}:
        raise ValueError("Kaynak aboneliği kapatılmış; yeniden açılmadı.")
    return subscribe(owner, source_event_key, goal_state_path=path, job_id=job_id, fresh_after=fresh_after)


def close_source(owner: str, source_event_key: str) -> int:
    """Close every active subscription of a removed source and cancel its GoalState."""
    service_store.identity(owner)
    with service_store.database(owner) as db:
        _schema(db)
        count = db.execute(
            "UPDATE runtime_subscriptions SET active=0 WHERE active=1 AND source_event_key=?",
            (source_event_key,),
        ).rowcount
    path, _ = _source_state_path(owner, source_event_key)
    goal_state_compat.close_subscription_state(path)
    return count


def _event_id(subscription_id: str, source_event_key: str, payload: dict) -> str:
    raw = service_store.encode([subscription_id, source_event_key, payload]).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def publish(
    owner: str,
    source_event_key: str,
    payload: dict,
    *,
    occurred_at: float | None = None,
    kind: str = "source_update",
) -> list[str]:
    """Produce fresh RuntimeEvents and commit only accepted evidence."""
    service_store.identity(owner)
    if not isinstance(payload, dict):
        raise ValueError("Runtime Event payload sözlük olmalı.")
    if not isinstance(kind, str) or not kind:
        raise ValueError("Runtime Event türü geçersiz.")
    occurred_at = time.time() if occurred_at is None else occurred_at
    with service_store.database(owner) as db:
        _schema(db)
        subscriptions = [
            dict(row) for row in db.execute(
                "SELECT * FROM runtime_subscriptions "
                "WHERE active=1 AND source_event_key=? ORDER BY created",
                (source_event_key,),
            )
        ]
    accepted_ids = []
    for row in subscriptions:
        event = {
            "schema": runtime_event.SCHEMA,
            "event_id": _event_id(row["id"], source_event_key, payload),
            "source_event_key": source_event_key,
            "source_generation": row["source_generation"],
            "subject_version": row["subject_version"],
            "occurred_at": occurred_at,
            "kind": kind,
            "payload": payload,
        }
        seen = runtime_event.PersistentSeen(_seen_path(owner, row["id"]))
        try:
            try:
                persisted = runtime_event_commit.commit(
                    row["goal_state_path"], event, _subscription(row), seen,
                    expected_job_version=row["expected_job_version"],
                )
            except core_state_reducer.StaleStateError:
                # The goal moved on since subscribe/last event. Evidence append is
                # order-independent, so re-read the version once and retry.
                current = goal_state_store.load(row["goal_state_path"])
                persisted = runtime_event_commit.commit(
                    row["goal_state_path"], event, _subscription(row), seen,
                    expected_job_version=current["version"],
                )
        except core_state_reducer.TerminalStateError:
            # A finished/cancelled goal can never take evidence; stop retrying forever.
            with service_store.database(owner) as db:
                _schema(db)
                db.execute(
                    "UPDATE runtime_subscriptions SET active=0,error='TerminalStateError' WHERE id=?",
                    (row["id"],),
                )
            continue
        except Exception as exc:
            _record_failure('modules/runtime_subscription.py:publish')
            with service_store.database(owner) as db:
                _schema(db)
                db.execute(
                    "UPDATE runtime_subscriptions SET error=? WHERE id=?",
                    (type(exc).__name__, row["id"]),
                )
            continue
        with service_store.database(owner) as db:
            _schema(db)
            db.execute(
                "UPDATE runtime_subscriptions SET expected_job_version=?,last_event_at=?,error='' WHERE id=?",
                (persisted["version"], float(occurred_at), row["id"]),
            )
        accepted_ids.append(row["id"])
    return accepted_ids
