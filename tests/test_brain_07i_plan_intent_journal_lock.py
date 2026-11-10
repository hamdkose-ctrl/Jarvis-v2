"""BRAIN-07I: user-intent/plan CAS and execution journal share a short lock.

Deterministic file interleavings only. The existing goal executor, canonical
Reducer/CAS and save hook run against temporary files. No external workers,
models, permissions, provider actions or new scheduler are involved.
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
    goal_state, goal_state_compat, goal_state_save_hook, goal_state_store,
)

OWNER = 'alice'
JOB = '0123456789abcdef'


def node(step):
    return {
        'id': step, 'depends_on': [], 'capability_id': 'task.research',
        'input': {'question': 'x', 'url': 'https://example.test'},
        'expected_output': 'source report', 'acceptance': 'verified source',
    }


class PlanIntentJournalLockTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'goals'
        self.owner_root = self.root / OWNER
        self.owner_root.mkdir(parents=True)
        self.canonical = self.owner_root / (JOB + '.goalstate.json')
        self.record = execution_record.path_for(self.owner_root, JOB)
        for module, name, value in (
            (release_guard, 'atomic', goal_state_save_hook._atomic),
            (goal_executor, 'STORE', self.root),
        ):
            p = patch.object(module, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.job = {
            'id': JOB, 'owner': OWNER, 'request': 'Read sources',
            'state': 'running', 'goals': [], 'steps': [], 'outputs': {},
            'feedback': [],
        }
        release_guard.atomic(
            self.owner_root / (JOB + '.json'),
            json.dumps(self.job, ensure_ascii=False).encode(),
        )
        before = goal_state_store.load(self.canonical)
        planned = core_state_reducer.apply(before, {
            'op': 'set_goal_plan', 'expected_version': before['version'],
            'reason_code': 'TEST_PLAN',
            'plan': {'plan_version': 1, 'nodes': [node('left')]},
        })
        goal_state_store.compare_and_swap(
            self.canonical, expected_version=before['version'],
            next_state=planned,
        )
        self.job = execution_record.load(self.owner_root, OWNER, JOB)
        goal_job_control.capture(self.owner_root, self.job)
        self.base = planned['version']

    def revised_plan(self):
        return {'plan_version': 2, 'nodes': [node('left'), node('right')]}

    def _apply(self, kind):
        if kind == 'intent':
            return goal_state_compat.apply_goal_intent(
                self.canonical, owner=OWNER, job_id=JOB,
                expected_version=self.base,
                operation='revise', text='Change to another source',
            )
        return goal_state_compat.apply_goal_plan(
            self.canonical, owner=OWNER, job_id=JOB,
            expected_version=self.base, plan=self.revised_plan(),
        )

    def _check_mutation_waits_for_execution_record(self, kind):
        writing = threading.Event()
        release = threading.Event()
        competing_started = threading.Event()
        competing_inside = threading.Event()
        original_atomic = goal_state_save_hook._ORIGINAL_ATOMIC
        original_load = goal_state_store.load

        def slow_record(path, data):
            if Path(path) == self.record:
                writing.set()
                if not release.wait(12):
                    raise TimeoutError('Execution journal pause timed out')
            return original_atomic(path, data)

        def tracked_load(path):
            if Path(path) == self.canonical and threading.current_thread().name.startswith('intent-writer'):
                competing_inside.set()
            return original_load(path)

        def run_mutation():
            threading.current_thread().name = 'intent-writer-' + kind
            competing_started.set()
            return self._apply(kind)

        self.job['feedback'] = ['persist executor observation']
        try:
            with (patch.object(goal_state_save_hook, '_ORIGINAL_ATOMIC',
                               side_effect=slow_record),
                  patch.object(goal_state_store, 'load', side_effect=tracked_load),
                  ThreadPoolExecutor(max_workers=2) as pool):
                executor_save = pool.submit(goal_executor._save, self.job)
                self.assertTrue(writing.wait(8))
                mutated = pool.submit(run_mutation)
                self.assertTrue(competing_started.wait(8))
                # Without the shared lock the mutator would reach the
                # canonical load while the ExecutionRecord write is paused.
                self.assertFalse(competing_inside.wait(0.25))
                self.assertEqual(goal_state_store.load(self.canonical)['version'], self.base)
                release.set()
                executor_save.result(timeout=12)
                result = mutated.result(timeout=12)
                self.assertTrue(competing_inside.is_set())
        finally:
            release.set()
        self.assertEqual(result['version'], self.base + 1)
        self.assertEqual(
            execution_record.load(self.owner_root, OWNER, JOB)['feedback'],
            ['persist executor observation'],
        )
        self.assertEqual(goal_state_store.load(self.canonical), result)

    def test_user_intent_cas_waits_until_execution_record_write_finishes(self):
        self._check_mutation_waits_for_execution_record('intent')

    def test_plan_revision_cas_waits_until_execution_record_write_finishes(self):
        self._check_mutation_waits_for_execution_record('plan')

    def test_execution_record_cannot_pass_inflight_plan_cas_version_fence(self):
        entered = threading.Event()
        release = threading.Event()
        journal_started = threading.Event()
        journal_done = threading.Event()
        before_record = self.record.read_bytes()
        original_cas = goal_state_store.compare_and_swap

        def slow_plan_cas(path, *, expected_version, next_state):
            if (Path(path) == self.canonical
                    and next_state['audit'][-1]['op'] == 'set_goal_plan'):
                entered.set()
                if not release.wait(12):
                    raise TimeoutError('Plan CAS pause timed out')
            return original_cas(
                path, expected_version=expected_version, next_state=next_state,
            )

        def save():
            journal_started.set()
            try:
                goal_executor._save(self.job)
            finally:
                journal_done.set()

        try:
            with (patch.object(goal_state_store, 'compare_and_swap',
                               side_effect=slow_plan_cas),
                  ThreadPoolExecutor(max_workers=2) as pool):
                planned = pool.submit(self._apply, 'plan')
                self.assertTrue(entered.wait(8))
                journal = pool.submit(save)
                self.assertTrue(journal_started.wait(8))
                self.assertFalse(journal_done.wait(0.25))
                release.set()
                updated = planned.result(timeout=12)
                with self.assertRaisesRegex(ValueError, 'Hedef sürümü'):
                    journal.result(timeout=12)
        finally:
            release.set()
        self.assertEqual(goal_state_store.load(self.canonical), updated)
        self.assertEqual(self.record.read_bytes(), before_record)

    def test_canonical_only_short_identity_has_no_execution_journal_lock(self):
        # GoalState IDs are intentionally broader than the 16-hex executor
        # journal schema. Existing canonical-only callers must still work.
        short_path = self.owner_root / 'abc.goalstate.json'
        original = goal_state.new(
            owner=OWNER, job_id='abc', goal='Standalone canonical intent',
            authority='canonical',
        )
        goal_state_store.create(short_path, original)
        planned = goal_state_compat.apply_goal_plan(
            short_path, owner=OWNER, job_id='abc',
            expected_version=original['version'],
            plan={'plan_version': 1, 'nodes': [node('only')]},
        )
        updated = goal_state_compat.apply_goal_intent(
            short_path, owner=OWNER, job_id='abc',
            expected_version=planned['version'],
            operation='revise', text='Keep the standalone plan safe',
        )
        self.assertEqual(updated['version'], 2)
        self.assertEqual(updated['goal_plan']['plan_version'], 1)
        self.assertEqual(updated['goal_intent']['revision'],
                         'Keep the standalone plan safe')
        self.assertEqual(goal_state_store.load(short_path), updated)
        self.assertFalse(
            execution_record.path_for(self.owner_root, JOB).with_name(
                'abc.execution.json'
            ).exists()
        )

    def test_existing_nested_goal_executor_control_lock_is_reentrant(self):
        with goal_job_control.locked(self.owner_root, JOB):
            revised = self._apply('intent')
            self.assertEqual(revised['version'], self.base + 1)
            self.assertEqual(revised['goal_intent']['revision'],
                             'Change to another source')
        self.assertEqual(
            goal_state_store.load(self.canonical)['version'], self.base + 1,
        )


if __name__ == '__main__':
    unittest.main()
