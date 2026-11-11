"""BRAIN-07: old task journal CAS and live queue-generation write fence.

Real SQLite and filesystem persistence; no provider calls or external effects.
"""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import llm, requests_state, service_store, task_agents, task_queue


class DurableQueuedWorkerFenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        for module, attr, value in (
            (task_agents, 'STORE', base / 'jobs'),
            (service_store, 'ROOT', base / 'sqlite'),
        ):
            p = patch.object(module, attr, value)
            p.start()
            self.addCleanup(p.stop)
        token = llm._key_context.set('alice')
        self.addCleanup(llm._key_context.reset, token)

    def saved(self):
        return {'id': 'a' * 12, 'state': 'running', 'tasks': [], 'outputs': {}}

    def test_stale_snapshot_cannot_overwrite_newer_job_across_independent_loads(self):
        root = task_agents._root('alice')
        job = self.saved()
        task_agents._save(root, job)
        first = task_agents._load('alice', job['id'])
        second = task_agents._load('alice', job['id'])
        second['state'] = 'cancelled'
        task_agents._save(root, second)
        first['state'] = 'done'
        with self.assertRaisesRegex(ValueError, 'başka yürütmede'):
            task_agents._save(root, first)
        self.assertEqual(task_agents._load('alice', job['id'])['state'], 'cancelled')

    def test_new_claim_accepted_then_stolen_generation_blocks_journal(self):
        qid = task_queue.enqueue('alice', [{'id':'a', 'agent':'verify'}])
        assigned = task_queue.rows('alice')[0]['job_id']
        current = 'c' * 32
        with service_store.database('alice') as db:
            db.execute(
                "UPDATE queue SET state='running',lease=?,lease_token=? WHERE id=?",
                (time.time() + 90, current, qid),
            )
        job = {'id': assigned, 'queue_id': qid, 'state': 'running',
               'tasks': [], 'outputs': {}}
        root = task_agents._root('alice')
        token = task_agents._QUEUE_CLAIM.set(('alice', qid, assigned, current))
        try:
            task_agents._save(root, job)
            oldbytes = task_agents._job_path(root, assigned).read_bytes()
            with service_store.database('alice') as db:
                db.execute(
                    "UPDATE queue SET lease_token=? WHERE id=?",
                    ('d' * 32, qid),
                )
            job['state'] = 'done'
            with self.assertRaises(requests_state.Cancelled):
                task_agents._save(root, job)
            with self.assertRaises(requests_state.Cancelled):
                task_agents._check_job('alice', job)
            self.assertEqual(
                task_agents._job_path(root, assigned).read_bytes(), oldbytes,
            )
        finally:
            task_agents._QUEUE_CLAIM.reset(token)

    def test_external_cancel_keeps_original_cancel_exception_not_stale_write(self):
        import threading
        started = threading.Event()
        release = threading.Event()
        result = []
        def work(owner, task, deps):
            started.set()
            release.wait(8)
            return {'state':'done','text':'late'}
        def worker_thread():
            try:
                task_agents.execute('alice', [{'id':'a','agent':'research'}])
            except requests_state.Cancelled:
                result.append('cancelled')
        with patch.object(task_agents, 'worker', side_effect=work):
            thread = threading.Thread(target=worker_thread)
            thread.start()
            self.assertTrue(started.wait(5))
            job = task_agents.cancel_job('alice')
            release.set()
            thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(result, ['cancelled'])
        self.assertEqual(task_agents._load('alice', job['id'])['state'], 'cancelled')

    def test_queue_lease_lost_during_worker_cannot_record_done(self):
        qid = task_queue.enqueue('alice', [{'id':'a', 'agent':'verify'}])
        def revoke(owner, task, deps):
            with service_store.database(owner) as db:
                db.execute("UPDATE queue SET lease_token=? WHERE id=?",
                           ('stolen', qid))
            return {'state': 'done', 'text': 'should never be recorded'}
        with patch.object(task_agents, 'worker', side_effect=revoke) as worker:
            task_queue.tick('alice')
            worker.assert_called_once()
        self.assertEqual(task_queue.rows('alice')[0]['state'], 'running')
        job_id = task_queue.rows('alice')[0]['job_id']
        durable = task_agents._load('alice', job_id)
        self.assertNotEqual(durable['state'], 'done')
        self.assertNotEqual(durable['tasks'][0]['state'], 'done')
        self.assertNotIn('a', durable['outputs'])

    def test_expired_generation_is_rejected_before_first_worker(self):
        qid = task_queue.enqueue('alice', [{'id':'a', 'agent':'verify'}])
        assigned = task_queue.rows('alice')[0]['job_id']
        with service_store.database('alice') as db:
            db.execute("UPDATE queue SET state='running',lease=?,lease_token=? WHERE id=?",
                       (time.time() - 1, 'e' * 32, qid))
        marker = task_agents._QUEUE_CLAIM.set(('alice', qid, assigned, 'e' * 32))
        try:
            with self.assertRaises(requests_state.Cancelled):
                task_agents._save(
                    task_agents._root('alice'),
                    {'id': assigned, 'queue_id': qid, 'state': 'running',
                     'tasks': [], 'outputs': {}},
                )
            self.assertFalse(task_agents._job_path(
                task_agents._root('alice'), assigned,
            ).exists())
        finally:
            task_agents._QUEUE_CLAIM.reset(marker)


if __name__ == '__main__':
    unittest.main()
