"""BRAIN-07H: ExecutionRecord and WorkerResult CAS share one short job lock.

Deterministic interleavings with real canonical CAS and ExecutionRecord files.
No worker/provider/model/network runs: only fake WorkerResult evidence is used.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import release_guard
from modules import (
    core_state_reducer, execution_record, goal_executor, goal_job_control,
    goal_state_save_hook, goal_state_store, runtime_worker_result,
    worker_result_commit, worker_result_hook,
)

OWNER = 'alice'
JOB = '0123456789abcdef'
DATA = {'url': 'https://example.test/source', 'question': 'compare sources'}


def node(name):
    return {
        'id': name, 'depends_on': [], 'capability_id': 'task.research',
        'input': dict(DATA), 'expected_output': 'source report',
        'acceptance': 'verified source evidence',
    }


def identity(step):
    return {
        'version': 1, 'owner': OWNER, 'job_id': JOB, 'task_id': step,
        'attempt': 1, 'request': 'Compare sources',
    }


class CrossRecordCommitLockTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'goals'
        self.user_dir = self.root / OWNER
        self.user_dir.mkdir(parents=True)
        self.canonical_path = self.user_dir / (JOB + '.goalstate.json')
        self.record_path = execution_record.path_for(self.user_dir, JOB)
        job = {
            'id': JOB, 'owner': OWNER, 'request': 'Compare sources',
            'state': 'running', 'goals': [], 'steps': [], 'outputs': {},
            'feedback': [],
        }
        for module, key, value in (
            (release_guard, 'atomic', goal_state_save_hook._atomic),
            (goal_executor, 'STORE', self.root),
        ):
            patcher = patch.object(module, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        release_guard.atomic(
            self.user_dir / (JOB + '.json'),
            json.dumps(job, ensure_ascii=False).encode(),
        )
        state = goal_state_store.load(self.canonical_path)
        planned = core_state_reducer.apply(state, {
            'op': 'set_goal_plan', 'reason_code': 'TEST_PLAN',
            'plan': {'plan_version': 1, 'nodes': [node('left'), node('right')]},
            'expected_version': state['version'],
        })
        goal_state_store.compare_and_swap(
            self.canonical_path,
            expected_version=state['version'], next_state=planned,
        )
        self.job = execution_record.load(self.user_dir, OWNER, JOB)
        goal_job_control.capture(self.user_dir, self.job)
        self.plan_version = planned['version']

    def prepared(self, step):
        enriched, expected = runtime_worker_result.prepare(
            identity(step), 'research', DATA,
        )
        wrapped = worker_result_hook.wrap_output({
            'state': 'done', 'verification': {'fixture': step},
        }, enriched)
        return wrapped, expected

    def commit(self, prepared):
        return runtime_worker_result.accept_and_commit(*prepared)

    def test_canonical_worker_cannot_interleave_execution_record_write(self):
        prepared = self.prepared('left')
        record_entered = threading.Event()
        release_record = threading.Event()
        worker_started = threading.Event()
        worker_inside_control = threading.Event()
        original_atomic = goal_state_save_hook._ORIGINAL_ATOMIC
        original_commit_once = worker_result_commit._commit_once

        def pause_at_record(path, data):
            if Path(path) == self.record_path:
                record_entered.set()
                if not release_record.wait(12):
                    raise TimeoutError('ExecutionRecord test rendezvous timed out')
            return original_atomic(path, data)

        def tagged_commit_once(*args, **kwargs):
            worker_inside_control.set()
            return original_commit_once(*args, **kwargs)

        def second_worker():
            worker_started.set()
            return self.commit(prepared)

        self.job['feedback'] = ['persist local step outcome']
        try:
            with (patch.object(goal_state_save_hook, '_ORIGINAL_ATOMIC',
                               side_effect=pause_at_record),
                  patch.object(worker_result_commit, '_commit_once',
                               side_effect=tagged_commit_once),
                  ThreadPoolExecutor(max_workers=2) as pool):
                save = pool.submit(goal_executor._save, self.job)
                self.assertTrue(record_entered.wait(8))
                worker = pool.submit(second_worker)
                self.assertTrue(worker_started.wait(8))
                # A shared control lock prevents even *entering* CAS while
                # the execution record transaction is unfinished.
                self.assertFalse(worker_inside_control.wait(0.25))
                self.assertEqual(goal_state_store.load(self.canonical_path)['evidence'], [])
                release_record.set()
                save.result(timeout=12)
                worker.result(timeout=12)
                self.assertTrue(worker_inside_control.is_set())
        finally:
            release_record.set()
        saved_record = execution_record.load(self.user_dir, OWNER, JOB)
        self.assertEqual(saved_record['feedback'], ['persist local step outcome'])
        accepted = goal_state_store.load(self.canonical_path)
        self.assertEqual([v['step_id'] for v in accepted['evidence']], ['left'])

    def test_execution_save_waits_for_canonical_cas_then_rejects_stale_version(self):
        prepared = self.prepared('left')
        cas_entered = threading.Event()
        release_cas = threading.Event()
        save_started = threading.Event()
        save_done = threading.Event()
        original_cas = goal_state_store.compare_and_swap
        previous_record = self.record_path.read_bytes()

        def paused_cas(path, *, expected_version, next_state):
            if (Path(path) == self.canonical_path
                    and next_state['audit'][-1]['reason_code']
                    == 'WORKER_RESULT_ACCEPTED'):
                cas_entered.set()
                if not release_cas.wait(12):
                    raise TimeoutError('WorkerResult CAS rendezvous timed out')
            return original_cas(
                path, expected_version=expected_version, next_state=next_state,
            )

        def save():
            save_started.set()
            try:
                goal_executor._save(self.job)
            finally:
                save_done.set()

        try:
            with (patch.object(goal_state_store, 'compare_and_swap',
                               side_effect=paused_cas),
                  ThreadPoolExecutor(max_workers=2) as pool):
                writer = pool.submit(self.commit, prepared)
                self.assertTrue(cas_entered.wait(8))
                saver = pool.submit(save)
                self.assertTrue(save_started.wait(8))
                self.assertFalse(save_done.wait(0.25))
                release_cas.set()
                writer.result(timeout=12)
                with self.assertRaisesRegex(ValueError, 'Hedef sürümü'):
                    saver.result(timeout=12)
        finally:
            release_cas.set()
        self.assertEqual(self.record_path.read_bytes(), previous_record)
        current = goal_state_store.load(self.canonical_path)
        self.assertEqual(len(current['evidence']), 1)
        self.assertEqual(current['version'], self.plan_version + 1)

    def test_failed_record_write_rollback_precedes_worker_cas(self):
        prepared = self.prepared('right')
        record_entered = threading.Event()
        release_record = threading.Event()
        worker_started = threading.Event()
        worker_inside_control = threading.Event()
        original_atomic = goal_state_save_hook._ORIGINAL_ATOMIC
        original_commit_once = worker_result_commit._commit_once
        previous_record = self.record_path.read_bytes()
        previous_canonical = goal_state_store.load(self.canonical_path)

        def failing_write(path, data):
            if Path(path) == self.record_path:
                record_entered.set()
                if not release_record.wait(12):
                    raise TimeoutError('Rollback rendezvous timed out')
                raise OSError('synthetic execution journal IO error')
            return original_atomic(path, data)

        def tagged_commit_once(*args, **kwargs):
            worker_inside_control.set()
            return original_commit_once(*args, **kwargs)

        def worker():
            worker_started.set()
            return self.commit(prepared)

        # This job state causes a canonical lifecycle transition to waiting.
        # If the ExecutionRecord write then fails, the hook compensates it
        # before releasing the job lock; a second worker must not be lost.
        self.job['state'] = 'approval'
        self.job['blocker'] = 'synthetic approval'
        try:
            with (patch.object(goal_state_save_hook, '_ORIGINAL_ATOMIC',
                               side_effect=failing_write),
                  patch.object(worker_result_commit, '_commit_once',
                               side_effect=tagged_commit_once),
                  ThreadPoolExecutor(max_workers=2) as pool):
                saving = pool.submit(goal_executor._save, self.job)
                self.assertTrue(record_entered.wait(8))
                committing = pool.submit(worker)
                self.assertTrue(worker_started.wait(8))
                self.assertFalse(worker_inside_control.wait(0.25))
                release_record.set()
                with self.assertRaisesRegex(OSError, 'journal IO'):
                    saving.result(timeout=12)
                committing.result(timeout=12)
        finally:
            release_record.set()
        current = goal_state_store.load(self.canonical_path)
        self.assertEqual(current['state'], previous_canonical['state'])
        self.assertEqual(current['version'], previous_canonical['version'] + 1)
        self.assertEqual([x['step_id'] for x in current['evidence']], ['right'])
        self.assertEqual(self.record_path.read_bytes(), previous_record)


if __name__ == '__main__':
    unittest.main()
