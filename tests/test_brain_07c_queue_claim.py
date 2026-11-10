"""BRAIN-07C1: existing queue scheduler claim fencing through real SQLite state.

These tests exercise tick -> durable SQL claim -> worker dispatch -> finalization.
They do not claim canonical DAG ResourceLease or cross-process worker cancellation.
"""
from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from modules import llm, service_store, task_agents, task_queue


TASKS = [{'id': 'check', 'agent': 'verify', 'depends': [], 'input': {}}]


class QueueClaimFenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        token = llm._key_context.set('alice')
        self.addCleanup(llm._key_context.reset, token)
        for obj, attr, value in (
            (service_store, 'ROOT', self.root / 'service'),
            (task_agents, 'STORE', self.root / 'tasks'),
        ):
            fixture = patch.object(obj, attr, value)
            fixture.start()
            self.addCleanup(fixture.stop)

    def test_stolen_token_cannot_finalize_or_notify_success(self):
        qid = task_queue.enqueue('alice', TASKS)
        callback = Mock()
        claims = []

        def execute(*args, **kwargs):
            with service_store.database('alice') as db:
                row = db.execute(
                    'SELECT lease_token FROM queue WHERE id=?', (qid,)
                ).fetchone()
                claims.append(row['lease_token'])
                self.assertEqual(len(claims[0]), 32)
                # Another claim took over while the worker was running.
                db.execute(
                    'UPDATE queue SET lease_token=?,lease=? WHERE id=?',
                    ('new-generation', time.time() + 90, qid),
                )
            return {'state': 'done'}

        with patch.object(task_agents, 'execute', side_effect=execute) as work:
            task_queue.tick('alice', callback)
            work.assert_called_once()
        with service_store.database('alice') as db:
            row = db.execute('SELECT * FROM queue WHERE id=?', (qid,)).fetchone()
            self.assertEqual(row['state'], 'running')
            self.assertEqual(row['lease_token'], 'new-generation')
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM queue_runs WHERE qid=?', (qid,)
            ).fetchone()[0], 0)
        callback.assert_not_called()

    def test_expired_claim_cannot_commit_even_without_successor(self):
        qid = task_queue.enqueue('alice', TASKS)

        def execute(*args, **kwargs):
            with service_store.database('alice') as db:
                db.execute('UPDATE queue SET lease=0 WHERE id=?', (qid,))
            return {'state': 'done'}

        with patch.object(task_agents, 'execute', side_effect=execute) as work:
            task_queue.tick('alice')
            work.assert_called_once()
        with service_store.database('alice') as db:
            row = db.execute(
                'SELECT state,lease FROM queue WHERE id=?', (qid,)
            ).fetchone()
            self.assertEqual(row['state'], 'running')
            self.assertEqual(row['lease'], 0)
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM queue_runs'
            ).fetchone()[0], 0)

    def test_cancel_invalidates_live_token_and_does_not_publish_done(self):
        qid = task_queue.enqueue('alice', TASKS)
        callback = Mock()

        def execute(*args, **kwargs):
            task_queue.cancel('alice', qid)
            return {'state': 'done'}

        with patch.object(task_agents, 'execute', side_effect=execute):
            task_queue.tick('alice', callback)
        with service_store.database('alice') as db:
            row = db.execute('SELECT state,lease_token FROM queue WHERE id=?', (qid,)).fetchone()
            self.assertEqual(row['state'], 'cancelled')
            self.assertEqual(row['lease_token'], '')
            self.assertEqual(db.execute(
                'SELECT COUNT(*) FROM queue_runs'
            ).fetchone()[0], 0)
        callback.assert_not_called()

    def test_old_queue_schema_is_migrated_without_losing_rows(self):
        service_store.ROOT.mkdir(parents=True, exist_ok=True)
        old = service_store.ROOT / 'alice.sqlite3'
        with sqlite3.connect(old) as db:
            db.execute(
                "CREATE TABLE queue (id TEXT PRIMARY KEY, tasks TEXT, instruction TEXT, "
                "due REAL, state TEXT, job_id TEXT, created REAL, error TEXT, "
                "lease REAL DEFAULT 0, cron TEXT DEFAULT '')"
            )
            db.execute(
                "INSERT INTO queue(id,tasks,instruction,due,state,job_id,created,error) "
                "VALUES(?,?,?,?,?,?,?,?)",
                ('old-entry', '[]', 'legacy', 1.0, 'queued', 'old-job', 1.0, ''),
            )
        with service_store.database('alice') as db:
            columns = {row[1] for row in db.execute('PRAGMA table_info(queue)')}
            self.assertIn('lease_token', columns)
            self.assertEqual(db.execute(
                "SELECT lease_token FROM queue WHERE id='old-entry'"
            ).fetchone()[0], '')


if __name__ == '__main__':
    unittest.main()
