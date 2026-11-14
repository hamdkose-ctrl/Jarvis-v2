"""Core performance regression without relaxing owner, lease or schema safety."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sqlite3
import tempfile
import threading
import time
import unittest

from modules import llm, requests_state, service_store, task_queue


class SqliteHotPathTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "service"
        self.enterContext(patch.object(service_store, "ROOT", self.root))
        token = llm._key_context.set("alice")
        self.addCleanup(llm._key_context.reset, token)
        request_token = requests_state._current.set(None)
        self.addCleanup(requests_state._current.reset, request_token)

    def test_new_database_one_schema_migration_and_hot_path_keeps_claim_transaction(self):
        sql = []
        original = sqlite3.connect

        def traced(*args, **kwargs):
            connection = original(*args, **kwargs)
            connection.set_trace_callback(sql.append)
            return connection

        with patch.object(service_store.sqlite3, "connect", side_effect=traced):
            with service_store.database("alice") as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0],
                                 service_store._SCHEMA_VERSION)
                db.execute("INSERT INTO grants(service,destination,expires) VALUES('x','y',1)")
            before = len(sql)
            with service_store.database("alice") as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM grants").fetchone()[0], 1)
                db.execute("UPDATE grants SET expires=2 WHERE service='x'")
            hot_path = sql[before:]

        upper = [statement.strip().upper() for statement in hot_path]
        self.assertTrue(any(statement.startswith("BEGIN IMMEDIATE") for statement in upper))
        self.assertFalse(any("CREATE TABLE" in statement
                             or "ALTER TABLE" in statement
                             or "PRAGMA TABLE_INFO" in statement for statement in upper))
        with sqlite3.connect(self.root / "alice.sqlite3") as db:
            self.assertEqual(db.execute("SELECT expires FROM grants").fetchone()[0], 2)

    def test_existing_version_zero_database_migrates_without_losing_rows(self):
        self.root.mkdir(parents=True)
        path = self.root / "alice.sqlite3"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE queue(id TEXT PRIMARY KEY,tasks TEXT,instruction TEXT,due REAL,state TEXT,job_id TEXT,created REAL,error TEXT)")
            db.execute("INSERT INTO queue(id,tasks,state) VALUES('old','[]','queued')")
            db.execute("CREATE TABLE outbox(id TEXT PRIMARY KEY,work_key TEXT UNIQUE,payload TEXT,digest TEXT,state TEXT,created REAL,updated REAL,receipt TEXT,error TEXT)")
        with service_store.database("alice") as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(queue)")}
            self.assertTrue({"lease", "lease_token", "repeat_seconds", "last_job_id", "cron"} <= columns)
            columns = {row[1] for row in db.execute("PRAGMA table_info(outbox)")}
            self.assertTrue({"connection_digest", "approval_expires", "approval_consumed", "authorized_until"} <= columns)
            self.assertEqual(db.execute("SELECT state FROM queue WHERE id='old'").fetchone()[0], "queued")
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0],
                             service_store._SCHEMA_VERSION)

    def test_concurrent_first_open_has_one_atomic_migration(self):
        barrier = threading.Barrier(2)
        errors = []

        def work(n):
            token = llm._key_context.set("alice")
            try:
                barrier.wait(timeout=3)
                with service_store.database("alice") as db:
                    db.execute("INSERT INTO grants(service,destination,expires) VALUES(?,?,?)",
                               ("s", str(n), 1))
            except Exception as exc:
                errors.append(exc)
            finally:
                llm._key_context.reset(token)

        workers = [threading.Thread(target=work, args=(n,)) for n in (1, 2)]
        for thread in workers:
            thread.start()
        for thread in workers:
            thread.join(8)
        self.assertTrue(all(not thread.is_alive() for thread in workers))
        self.assertEqual(errors, [])
        with service_store.database("alice") as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM grants").fetchone()[0], 2)

    def test_unknown_future_schema_fails_closed(self):
        self.root.mkdir(parents=True)
        path = self.root / "alice.sqlite3"
        with sqlite3.connect(path) as db:
            db.execute("PRAGMA user_version=99")
        with self.assertRaises(ValueError):
            with service_store.database("alice"):
                self.fail("accepted unknown schema")
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 99)


class SchedulerWakeTests(unittest.TestCase):
    def setUp(self):
        self.wake_event = self.enterContext(
            patch.object(task_queue, "_SCHEDULER_WAKE", threading.Event()))

    def test_admission_wakes_without_waiting_five_seconds(self):
        stop = threading.Event()
        result = []
        waiting = threading.Event()

        def wait():
            waiting.set()
            result.append(task_queue._wait_for_scheduler_tick(stop))

        thread = threading.Thread(target=wait)
        thread.start()
        self.assertTrue(waiting.wait(1))
        try:
            task_queue.wake_scheduler()
            thread.join(2)
            self.assertFalse(thread.is_alive(), "wake did not interrupt 5-second timer")
            self.assertEqual(result, [True])
        finally:
            stop.set()
            task_queue.wake_scheduler()
            thread.join(2)

    def test_stop_remains_responsive_without_busy_db_poller(self):
        stop = threading.Event()
        result = []
        thread = threading.Thread(
            target=lambda: result.append(task_queue._wait_for_scheduler_tick(stop)))
        thread.start()
        stop.set()
        thread.join(2)
        self.assertFalse(thread.is_alive(), "scheduler stop became a 5-second delay")
        self.assertEqual(result, [False])

    def test_scheduled_enqueue_wakes_only_after_durable_commit(self):
        sequence = []

        @contextmanager
        def fake_database(owner):
            self.assertEqual(owner, "alice")
            db = SimpleNamespace(execute=lambda *args: sequence.append("write"))
            yield db
            sequence.append("commit")

        with patch.object(task_queue.service_store, "database", side_effect=fake_database), \
             patch("modules.task_agents.validate", return_value=None), \
             patch.object(task_queue, "wake_scheduler",
                          side_effect=lambda: sequence.append("wake")):
            task_queue.enqueue("alice", [{"agent": "account"}], "İş")
        self.assertEqual(sequence, ["write", "commit", "wake"])

    def test_failed_enqueue_never_wakes_workers(self):
        @contextmanager
        def bad_database(owner):
            raise OSError("journal commit failed")
            yield  # pragma: no cover

        with patch.object(task_queue.service_store, "database", side_effect=bad_database), \
             patch("modules.task_agents.validate", return_value=None), \
             patch.object(task_queue, "wake_scheduler") as wake:
            with self.assertRaises(OSError):
                task_queue.enqueue("alice", [{"agent": "account"}], "İş")
            wake.assert_not_called()


if __name__ == "__main__":
    unittest.main()
