"""BRAIN-07G: verified parallel WorkerResult advances do not strand ExecutionRecord.

Only the existing owner-scoped goal job save is tested. Worker results use the
real canonical Reducer/CAS and fake adapter outputs; no model, filesystem
effect, network, new scheduler or parallel worker dispatcher is involved.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import release_guard
from modules import (
    core_state_reducer, execution_record, goal_executor, goal_job_control,
    goal_state_compat, goal_state_save_hook, goal_state_store,
    runtime_worker_result, worker_result_hook,
)

OWNER = 'alice'
JOB = '0123456789abcdef'
DATA = {'url': 'https://example.test/source', 'question': 'compare sources'}


def node(step):
    return {
        'id': step, 'depends_on': [], 'capability_id': 'task.research',
        'input': dict(DATA), 'expected_output': 'source report',
        'acceptance': 'verified source evidence',
    }


def identity(step):
    return {
        'version': 1, 'owner': OWNER, 'job_id': JOB, 'task_id': step,
        'attempt': 1, 'request': 'Compare two sources',
    }


class WorkerOnlyProjectionFenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Path(self.temp.name) / 'goals'
        self.owner_root = self.store / OWNER
        self.owner_root.mkdir(parents=True)
        self.path = self.owner_root / (JOB + '.goalstate.json')
        self.job = {
            'id': JOB, 'owner': OWNER, 'request': 'Compare two sources',
            'state': 'running', 'goals': [], 'steps': [], 'outputs': {},
            'feedback': [],
        }
        for module, field, value in (
            (goal_executor, 'STORE', self.store),
            (release_guard, 'atomic', goal_state_save_hook._atomic),
        ):
            change = patch.object(module, field, value)
            change.start()
            self.addCleanup(change.stop)
        release_guard.atomic(
            self.owner_root / (JOB + '.json'),
            json.dumps(self.job, ensure_ascii=False).encode(),
        )
        canonical = goal_state_store.load(self.path)
        planned = core_state_reducer.apply(canonical, {
            'op': 'set_goal_plan',
            'plan': {'plan_version': 1, 'nodes': [node('left'), node('right')]},
            'expected_version': canonical['version'],
            'reason_code': 'TEST_PLAN',
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=canonical['version'],
            next_state=planned,
        )
        self.job = execution_record.load(self.owner_root, OWNER, JOB)
        goal_job_control.capture(self.owner_root, self.job)
        self.base_version = self.job['_canonical_version']
        self.record_file = execution_record.path_for(self.owner_root, JOB)

    def prepared(self, step):
        enriched, expected = runtime_worker_result.prepare(
            identity(step), 'research', dict(DATA),
        )
        wrapped = worker_result_hook.wrap_output({
            'state': 'done', 'verification': {'fixture': step},
        }, enriched)
        return wrapped, expected

    def commit(self, prepared):
        return runtime_worker_result.accept_and_commit(*prepared)

    def other_thread_commit(self, prepared):
        # In practice a second worker owns an independent thread-local mark.
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(self.commit, prepared).result(timeout=15)

    def save_projected_result(self):
        self.job['feedback'] = ['local execution result observed']
        goal_executor._save(self.job)
        return execution_record.load(self.owner_root, OWNER, JOB)

    def test_own_commit_then_independent_concurrent_commit_save_is_safe(self):
        own = self.prepared('left')
        other = self.prepared('right')
        self.commit(own)
        self.other_thread_commit(other)
        current = goal_state_store.load(self.path)
        self.assertEqual(current['version'], self.base_version + 2)
        saved = self.save_projected_result()
        self.assertEqual(saved['feedback'], ['local execution result observed'])
        self.assertEqual(self.job['_canonical_version'], current['version'])
        self.assertEqual(goal_state_store.load(self.path), current)
        self.assertEqual(
            [row['step_id'] for row in current['evidence']],
            ['left', 'right'],
        )

    def test_foreign_commit_first_then_own_cas_rebase_can_save(self):
        own = self.prepared('left')
        other = self.prepared('right')
        self.other_thread_commit(other)
        self.commit(own)
        current = goal_state_store.load(self.path)
        self.assertEqual(current['version'], self.base_version + 2)
        self.save_projected_result()
        self.assertEqual(self.job['_canonical_version'], current['version'])
        self.assertEqual(
            [row['step_id'] for row in current['evidence']],
            ['right', 'left'],
        )

    def test_no_thread_owned_worker_mark_cannot_adopt_foreign_success(self):
        other = self.prepared('right')
        self.other_thread_commit(other)
        record_before = self.record_file.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Hedef sürümü'):
            self.save_projected_result()
        self.assertEqual(self.record_file.read_bytes(), record_before)
        self.assertEqual(
            goal_state_store.load(self.path)['version'],
            self.base_version + 1,
        )

    def test_user_intent_change_after_owned_commit_never_advances_projection(self):
        own = self.prepared('left')
        self.commit(own)
        prior = goal_state_store.load(self.path)
        goal_state_compat.apply_goal_intent(
            self.path, owner=OWNER, job_id=JOB,
            expected_version=prior['version'],
            operation='revise', text='Stop and change research subject',
        )
        record_before = self.record_file.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Hedef sürümü'):
            self.save_projected_result()
        self.assertEqual(self.record_file.read_bytes(), record_before)

    def test_plan_revision_after_owned_commit_never_advances_projection(self):
        self.commit(self.prepared('left'))
        prior = goal_state_store.load(self.path)
        next_state = core_state_reducer.apply(prior, {
            'op': 'set_goal_plan', 'reason_code': 'USER_REPLAN',
            'plan': {'plan_version': 2, 'nodes': [node('left'), node('right')]},
            'expected_version': prior['version'],
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=prior['version'],
            next_state=next_state,
        )
        before = self.record_file.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Hedef sürümü'):
            self.save_projected_result()
        self.assertEqual(self.record_file.read_bytes(), before)

    def test_unrelated_evidence_append_never_rebases_owned_worker_projection(self):
        self.commit(self.prepared('left'))
        before = goal_state_store.load(self.path)
        extra = core_state_reducer.apply(before, {
            'op': 'append_evidence', 'reason_code': 'USER_NOTE',
            'evidence': {'kind': 'user_note', 'value': 'new interpretation'},
            'expected_version': before['version'],
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=before['version'],
            next_state=extra,
        )
        old_record = self.record_file.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Hedef sürümü'):
            self.save_projected_result()
        self.assertEqual(self.record_file.read_bytes(), old_record)

    def test_concurrent_execution_record_editor_remains_fenced(self):
        self.commit(self.prepared('left'))
        self.other_thread_commit(self.prepared('right'))
        changed = execution_record.load(self.owner_root, OWNER, JOB)
        changed['feedback'] = ['a different execution writer']
        release_guard.atomic(
            self.record_file, execution_record.encode(changed),
        )
        before = self.record_file.read_bytes()
        with self.assertRaisesRegex(ValueError, 'yürütme'):
            self.save_projected_result()
        self.assertEqual(self.record_file.read_bytes(), before)
        self.assertEqual(
            execution_record.load(self.owner_root, OWNER, JOB)['feedback'],
            ['a different execution writer'],
        )


if __name__ == '__main__':
    unittest.main()
