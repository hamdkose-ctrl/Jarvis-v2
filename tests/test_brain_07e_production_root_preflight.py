"""BRAIN-07E: production read-only root preflight and acceptance safety.

No real worker, network/model, resource lease or permission is granted here.
The specialist boundary test proves a canonical already-done root cannot call
a worker again merely because the legacy execution journal requested it.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from modules import (
    core_state_reducer, goal_plan_gate, goal_state, goal_state_store,
    goal_tools, runtime_worker_result, specialist_orchestrator,
    worker_result_hook,
)

OWNER = 'alice'
JOB = '0123456789abcdef'
DATA = {'url': 'https://example.test', 'question': 'x'}


def node(name, deps=(), capability='task.research'):
    return {
        'id': name, 'depends_on': list(deps), 'capability_id': capability,
        'input': dict(DATA), 'expected_output': 'verified source report',
        'acceptance': 'confirmed source evidence',
    }


def identity(step, attempt=1):
    return {
        'version': 1, 'owner': OWNER, 'job_id': JOB,
        'task_id': step, 'attempt': attempt, 'request': 'read source',
    }


class PlannedRootProductionFenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / OWNER / (JOB + '.goalstate.json')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        initial = goal_state.new(
            owner=OWNER, job_id=JOB, goal='Read two sources',
            authority='canonical',
        )
        self.plan = {'plan_version': 1, 'nodes': [
            node('left'), node('right'), node('dependent', ('left',)),
        ]}
        planned = core_state_reducer.apply(initial, {
            'op': 'set_goal_plan', 'plan': self.plan,
            'expected_version': initial['version'], 'reason_code': 'TEST_PLAN',
        })
        goal_state_store.create(self.path, planned)
        from modules import goal_executor
        patch_store = patch.object(goal_executor, 'STORE', self.root)
        patch_store.start()
        self.addCleanup(patch_store.stop)

    def prepare(self, step, attempt=1):
        return runtime_worker_result.prepare(
            identity(step, attempt), 'research', DATA,
        )

    def commit(self, prepared, state='done'):
        enriched, expected = prepared
        output = worker_result_hook.wrap_output({
            'state': state, 'verification': {'fixture': 'synthetic'},
        }, enriched)
        return runtime_worker_result.accept_and_commit(output, expected)

    def change(self, op, *, reason, **details):
        old = goal_state_store.load(self.path)
        updated = core_state_reducer.apply(old, {
            'op': op, 'reason_code': reason,
            'expected_version': old['version'], **details,
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=old['version'], next_state=updated,
        )
        return updated

    def test_fresh_roots_prepare_independently_and_complete_once(self):
        first = self.prepare('left')
        second = self.prepare('right')
        self.commit(first)
        self.commit(second)
        state = goal_state_store.load(self.path)
        self.assertEqual([v['step_id'] for v in state['evidence']], ['left', 'right'])
        self.assertEqual(state['version'], 3)
        self.assertEqual(state['goal_plan']['plan_version'], 1)

    def test_completed_root_cannot_prepare_again_but_same_commit_replays(self):
        prepared = self.prepare('left')
        self.commit(prepared)
        before = goal_state_store.load(self.path)
        with self.assertRaisesRegex(goal_plan_gate.PlanFenceError, 'tamamlanmış'):
            self.prepare('left', attempt=2)
        self.commit(prepared)
        self.assertEqual(goal_state_store.load(self.path), before)

    def test_exact_recovery_after_success_reuses_fence_without_new_worker(self):
        from modules import reconcile_worker_result
        prepared = self.prepare('left')
        self.commit(prepared)
        before = goal_state_store.load(self.path)
        recovered = {
            'state': 'done', 'verification': {'fixture': 'synthetic'},
        }
        with (patch.object(goal_tools, 'verify', return_value=True) as verified,
              patch.object(goal_tools, 'execute') as worker):
            result = reconcile_worker_result.accept_and_commit(
                recovered, identity('left'), 'research', DATA,
            )
        verified.assert_called_once_with(recovered, OWNER)
        worker.assert_not_called()
        self.assertEqual(result, recovered)
        self.assertEqual(goal_state_store.load(self.path), before)

    def test_recovery_cannot_mint_new_success_from_missing_execution_fence(self):
        from modules import reconcile_worker_result
        with (patch.object(goal_tools, 'verify') as verified,
              patch.object(goal_tools, 'execute') as worker):
            with self.assertRaisesRegex(ValueError, 'önceden kabul edilmiş'):
                reconcile_worker_result.accept_and_commit(
                    {'state': 'done'}, identity('left'), 'research', DATA,
                )
        verified.assert_not_called()
        worker.assert_not_called()
        self.assertEqual(goal_state_store.load(self.path)['evidence'], [])

    def test_real_specialist_boundary_never_launches_duplicate_worker(self):
        self.commit(self.prepare('left'))
        runtime = SimpleNamespace(profile=SimpleNamespace(slug=OWNER))
        job = {
            'id': JOB, 'owner': OWNER, 'request': 'read source',
            'state': 'running', 'outputs': {},
        }
        step = {
            'id': 'left', 'tool': 'research', 'input': dict(DATA),
            'depends': [], 'state': 'running',
        }
        with (patch('modules.runtime_execution_gate.plan_task',
                    return_value={'phase': 'execute'}),
              patch('modules.effect_recovery_runtime.required', return_value=False),
              patch('modules.research_evidence.news_requested', return_value=False),
              patch.object(goal_tools, 'execute') as worker):
            with self.assertRaises(goal_plan_gate.PlanFenceError):
                specialist_orchestrator._execute_step(
                    runtime, job, step, identity('left', 2),
                )
        worker.assert_not_called()

    def test_failed_attempt_needs_new_attempt_and_never_auto_ready(self):
        first = self.prepare('left')
        self.commit(first, state='failed')
        current = goal_state_store.load(self.path)
        ready = goal_plan_gate.ready_read_only_candidates(
            current, owner=OWNER, job_id=JOB,
        )
        self.assertEqual([c.node_id for c in ready], ['right'])
        with self.assertRaises(goal_plan_gate.PlanFenceError):
            self.prepare('left', attempt=1)
        retry = self.prepare('left', attempt=2)
        self.commit(retry)
        state = goal_state_store.load(self.path)
        self.assertEqual(
            [x['status'] for x in state['evidence']], ['failed', 'succeeded'],
        )

    def test_user_plan_correction_blocks_new_worker_and_stale_result_cas(self):
        pending = self.prepare('right')
        self.change(
            'mutate_goal_intent', reason='USER_CORRECTION',
            operation='revise', text='Use another research source',
            priority=None,
        )
        with self.assertRaises(goal_plan_gate.PlanFenceError):
            self.prepare('left')
        with self.assertRaisesRegex(
            goal_state_store.PersistedStateConflict, 'stale',
        ):
            self.commit(pending)
        self.assertEqual(len(goal_state_store.load(self.path)['evidence']), 0)

    def test_untrusted_current_plan_evidence_blocks_preflight(self):
        self.change(
            'append_evidence', reason='WORKER_RESULT_ACCEPTED',
            evidence={'kind': 'worker_result', 'step_id': 'left',
                      'owner': OWNER, 'job_id': JOB,
                      'plan_version': 1, 'status': 'succeeded'},
        )
        with self.assertRaises(goal_plan_gate.PlanFenceError):
            self.prepare('right')

    def test_dependency_and_effectful_capabilities_stay_blocked(self):
        self.commit(self.prepare('left'))
        with self.assertRaises(ValueError):
            self.prepare('dependent')
        self.change('set_goal_plan', reason='REPLAN', plan={
            'plan_version': 2,
            'nodes': [node('effect', capability='task.writer')],
        })
        with self.assertRaises(ValueError):
            runtime_worker_result.prepare(identity('effect'), 'writer', dict(DATA))


if __name__ == '__main__':
    unittest.main()
