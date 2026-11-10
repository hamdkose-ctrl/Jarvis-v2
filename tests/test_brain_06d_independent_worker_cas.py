"""BRAIN-06D: concurrent canonical roots may persist independent results.

Uses the real canonical GoalState reducer/CAS and WorkerResult acceptance seam.
Workers are mocked; this does not launch a Scheduler, grant effect permission,
or imply a successful WorkerResult is global Goal completion.
"""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import (
    core_state_reducer, goal_state, goal_state_store, runtime_worker_result,
    worker_result_hook,
)

OWNER = 'alice'
JOB = '0123456789abcdef'
DATA = {'url': 'https://example.test', 'question': 'x'}


def node(name):
    return {
        'id': name, 'depends_on': [], 'capability_id': 'task.research',
        'input': copy.deepcopy(DATA), 'expected_output': 'verified source report',
        'acceptance': 'confirmed source evidence',
    }


def identity(name, attempt=1):
    return {
        'version': 1, 'owner': OWNER, 'job_id': JOB,
        'task_id': name, 'attempt': attempt, 'request': 'özetle',
    }


class IndependentRootResultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / OWNER / (JOB + '.goalstate.json')
        self.path.parent.mkdir(parents=True)
        new = goal_state.new(
            owner=OWNER, job_id=JOB, goal='İki kaynağı oku', authority='canonical',
        )
        planned = core_state_reducer.apply(new, {
            'op': 'set_goal_plan', 'plan': {
                'plan_version': 1, 'nodes': [node('left'), node('right')],
            },
            'expected_version': new['version'], 'reason_code': 'TEST_PLAN',
        })
        goal_state_store.create(self.path, planned)
        from modules import goal_executor
        owner_store = patch.object(goal_executor, 'STORE', self.root)
        owner_store.start()
        self.addCleanup(owner_store.stop)

    def _prepared(self, step, attempt=1, state='done'):
        enriched, expected = runtime_worker_result.prepare(
            identity(step, attempt), 'research', DATA,
        )
        wrapped = worker_result_hook.wrap_output({
            'state': state, 'verification': {'source': 'example.test'},
        }, enriched)
        return expected, wrapped

    def _commit(self, prepared):
        return runtime_worker_result.accept_and_commit(prepared[1], prepared[0])

    def test_independent_roots_from_same_snapshot_both_commit_through_cas(self):
        left = self._prepared('left')
        right = self._prepared('right')
        self.assertEqual(left[0]['expected_job_version'], 1)
        self.assertEqual(right[0]['expected_job_version'], 1)
        self._commit(left)
        self._commit(right)
        saved = goal_state_store.load(self.path)
        self.assertEqual(saved['version'], 3)
        self.assertEqual(len(saved['evidence']), 2)
        self.assertEqual([row['step_id'] for row in saved['evidence']], ['left', 'right'])
        self.assertEqual(saved['goal_plan']['plan_version'], 1)
        # Repeated delivery of the SAME accepted envelope remains idempotent.
        self._commit(left)
        self.assertEqual(goal_state_store.load(self.path), saved)

    def test_goal_intent_or_unrelated_canonical_mutation_still_rejects_stale_root(self):
        other = self._prepared('right')
        before = goal_state_store.load(self.path)
        updated = core_state_reducer.apply(before, {
            'op': 'append_evidence', 'evidence': {'kind': 'user_change'},
            'expected_version': before['version'], 'reason_code': 'USER_UPDATED_GOAL',
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=before['version'], next_state=updated,
        )
        with self.assertRaisesRegex(ValueError, 'stale'):
            self._commit(other)
        self.assertEqual(goal_state_store.load(self.path), updated)

    def test_forged_worker_reason_with_nonworker_evidence_does_not_allow_rebase(self):
        other = self._prepared('right')
        before = goal_state_store.load(self.path)
        updated = core_state_reducer.apply(before, {
            'op': 'append_evidence', 'evidence': {'kind': 'untrusted'},
            'expected_version': before['version'],
            'reason_code': 'WORKER_RESULT_ACCEPTED',
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=before['version'], next_state=updated,
        )
        with self.assertRaisesRegex(ValueError, 'stale'):
            self._commit(other)
        self.assertEqual(goal_state_store.load(self.path), updated)

    def test_concurrent_attempts_of_same_root_do_not_rebase(self):
        first = self._prepared('left', state='failed')
        duplicate = self._prepared('left', attempt=2, state='done')
        self._commit(first)
        with self.assertRaisesRegex(ValueError, 'stale'):
            self._commit(duplicate)
        saved = goal_state_store.load(self.path)
        self.assertEqual(len(saved['evidence']), 1)
        self.assertEqual(saved['evidence'][0]['status'], 'failed')

    def test_already_succeeded_root_rejects_a_new_attempt(self):
        first = self._prepared('left')
        self._commit(first)
        another = self._prepared('left', attempt=2)
        with self.assertRaisesRegex(ValueError, 'önceki başarılı'):
            self._commit(another)
        self.assertEqual(len(goal_state_store.load(self.path)['evidence']), 1)

    def test_plan_revision_remains_a_hard_fence(self):
        right = self._prepared('right')
        left = self._prepared('left')
        self._commit(left)
        before = goal_state_store.load(self.path)
        revised = core_state_reducer.apply(before, {
            'op': 'set_goal_plan',
            'plan': {'plan_version': 2, 'nodes': [node('left'), node('right')]},
            'expected_version': before['version'], 'reason_code': 'USER_REPLAN',
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=before['version'], next_state=revised,
        )
        with self.assertRaises(ValueError):
            self._commit(right)
        self.assertEqual(goal_state_store.load(self.path), revised)


if __name__ == '__main__':
    unittest.main()
