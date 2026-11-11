"""BRAIN-07: the existing Scheduler dispatches bounded owner ticks.

Mocks only the per-owner tick worker; uses real threads/ContextVars and no
model or external tool. Proves a slow owner cannot monopolize the poll loop.
"""
from __future__ import annotations

import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import llm, outbox, privacy, service_store, source_watch, task_queue


class _FastStop:
    def __init__(self):
        self.e=threading.Event()
    def wait(self, _):
        return self.e.wait(.01)
    def is_set(self):
        return self.e.is_set()
    def set(self):
        self.e.set()


class ExistingSchedulerOwnerDispatchTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)
        root=self.path / 'sqlite'
        root.mkdir()
        p=patch.object(service_store, 'ROOT', root)
        p.start();self.addCleanup(p.stop)
        for owner in ('alice','bob','carol','dave'):
            (root / (owner+'.sqlite3')).touch()
        for module, attr, value in (
            (task_queue, '_THREAD', None),
            (task_queue, '_DAILY_NOTIFY', None),
            (task_queue, '_OWNER_TICKS', {}),
            (task_queue, '_LAST_ADMITTED', {}),
            (outbox, 'has_pending', lambda _: False),
            (privacy, 'blocked', lambda _: None),
        ):
            p=patch.object(module, attr, value)
            p.start();self.addCleanup(p.stop)
        p=patch.object(source_watch, 'poll')
        p.start();self.addCleanup(p.stop)
        self.stop=_FastStop()
        self.release=threading.Event()
        self.addCleanup(self.release.set)
        self.addCleanup(self.stop.set)
        # Thread cleanup must run while the temporary task_queue registry and
        # test-owned directories still exist, including assertion failures.
        self.addCleanup(self.finish_threads)

    def finish_threads(self):
        self.stop.set()
        self.release.set()
        loop = task_queue._THREAD
        if loop:
            loop.join(8)
        for worker in tuple(task_queue._OWNER_TICKS.values()):
            worker.join(8)
        self.assertFalse(
            any(worker.is_alive() for worker in task_queue._OWNER_TICKS.values()),
            'Owner tick survived test teardown',
        )

    def test_blocked_first_owner_does_not_block_other_owners(self):
        first=threading.Event()
        next_owner=threading.Event()
        seen=[]
        mutex=threading.Lock()
        def tick(owner, notify=None):
            self.assertEqual(llm._key_context.get(), owner)
            with mutex:
                seen.append(owner)
            if owner=='alice':
                first.set()
                self.release.wait(4)
            elif owner=='bob':
                next_owner.set()
        with patch.object(task_queue, 'tick', side_effect=tick):
            task_queue.start(self.stop)
            self.assertTrue(first.wait(8), 'First owner was not dispatched')
            self.assertTrue(next_owner.wait(8), 'Second owner starved on first worker')
            self.assertIn('alice',seen)
            self.assertIn('bob',seen)
            self.assertLessEqual(len(task_queue._OWNER_TICKS), 3)
            self.stop.set()
            self.release.set()
            task_queue._THREAD.join(3)

    def test_bounded_pool_and_fair_owner_admission(self):
        started=set()
        observed=[]
        lock=threading.Lock()
        first_three=threading.Event()
        fourth=threading.Event()
        def tick(owner, notify=None):
            with lock:
                started.add(owner)
                observed.append(owner)
                if len(started)>=3:
                    first_three.set()
                if len(started)==4:
                    fourth.set()
            if owner in ('alice','bob','carol'):
                self.release.wait(5)
        with patch.object(task_queue, 'tick', side_effect=tick):
            task_queue.start(self.stop)
            self.assertTrue(first_three.wait(8))
            self.assertFalse(fourth.is_set(), 'Capacity limit was bypassed')
            self.release.set()
            self.assertTrue(fourth.wait(8), 'Fourth owner did not get a fair slot')
            self.stop.set()
            task_queue._THREAD.join(3)


if __name__ == '__main__':
    unittest.main()
