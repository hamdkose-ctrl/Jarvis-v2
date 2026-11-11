"""BRAIN-07D: canonical read-only DAG readiness from accepted CAS evidence.

Uses the real GoalState store/reducer and WorkerResult commit adapter, but only
synthetic worker outputs; it does NOT dispatch workers or verify outside effects.
A readiness candidate is never a lease, effect approval or global completion.
"""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import (
    core_state_reducer, goal_plan_gate, goal_state, goal_state_store,
    runtime_worker_result, worker_result_hook,
)

OWNER = 'alice'
JOB = '0123456789abcdef'
DATA = {'url': 'https://example.test', 'question': 'x'}


def node(name, deps=(), capability='task.research'):
    return {
        'id': name, 'depends_on': list(deps), 'capability_id': capability,
        'input': copy.deepcopy(DATA),
        'expected_output': 'verified research', 'acceptance': 'confirmed source',
    }


def ident(step, attempt=1):
    return {'version': 1, 'owner': OWNER, 'job_id': JOB, 'task_id': step,
            'attempt': attempt, 'request': 'research'}


class CanonicalReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.path = root / OWNER / (JOB + '.goalstate.json')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        init = goal_state.new(
            owner=OWNER, job_id=JOB, goal='Research two independent sources',
            authority='canonical',
        )
        self.plan = {
            'plan_version': 1, 'nodes': [
                node('left'), node('right'), node('dependent', ('left',)),
                node('last', ('dependent', 'right')),
            ],
        }
        state = core_state_reducer.apply(init, {
            'op': 'set_goal_plan', 'plan': self.plan, 'reason_code': 'TEST_PLAN',
            'expected_version': init['version'],
        })
        goal_state_store.create(self.path, state)
        from modules import goal_executor
        patch_store = patch.object(goal_executor, 'STORE', root)
        patch_store.start()
        self.addCleanup(patch_store.stop)

    def ready(self):
        return tuple(c.node_id for c in goal_plan_gate.ready_read_only_candidates(
            goal_state_store.load(self.path), owner=OWNER, job_id=JOB,
        ))

    def commit(self, step, *, attempt=1, state='done'):
        enriched, expected = runtime_worker_result.prepare(
            ident(step, attempt), 'research', DATA,
        )
        wrapped = worker_result_hook.wrap_output({
            'state': state, 'verification': {'fixture': 'contract-only'},
        }, enriched)
        runtime_worker_result.accept_and_commit(wrapped, expected)

    def mutate(self, op, *, reason, **kwargs):
        old = goal_state_store.load(self.path)
        revised = core_state_reducer.apply(old, {
            'op': op, 'expected_version': old['version'],
            'reason_code': reason, **kwargs,
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=old['version'], next_state=revised,
        )
        return revised

    def test_initial_roots_only_and_bounded_readiness(self):
        self.assertEqual(self.ready(), ('left', 'right'))
        self.assertEqual(self.ready(), ('left', 'right'))
        snapshot = goal_state_store.load(self.path)
        chosen = goal_plan_gate.ready_read_only_candidates(
            snapshot, owner=OWNER, job_id=JOB,
        )
        self.assertTrue(all(isinstance(x, goal_plan_gate.NodeCandidate)
                            for x in chosen))
        self.assertEqual(snapshot['version'], 1)

    def test_accepted_root_unblocks_only_direct_child_not_unproven_grandchild(self):
        self.commit('left')
        self.assertEqual(self.ready(), ('right', 'dependent'))
        self.assertEqual(self.ready(), ('right', 'dependent'))
        # Readiness is *not* actual dependent dispatch: BRAIN-06C still
        # blocks dependency execution until its own proof path is complete.
        with self.assertRaises(ValueError):
            runtime_worker_result.prepare(ident('dependent'), 'research', DATA)
        self.commit('right')
        self.assertEqual(self.ready(), ('dependent',))
        self.assertEqual(goal_state_store.load(self.path)['state'], 'pending')

    def test_failed_node_is_not_requeued_automatically(self):
        self.commit('left', state='failed')
        self.assertEqual(self.ready(), ('right',))
        self.commit('right')
        self.assertEqual(self.ready(), ())
        # Explicit retry at current canonical version can still succeed.
        self.commit('left', attempt=2)
        self.assertEqual(self.ready(), ('dependent',))

    def test_same_command_replay_does_not_multiply_ready_steps(self):
        enriched, expected = runtime_worker_result.prepare(
            ident('left'), 'research', DATA,
        )
        output = worker_result_hook.wrap_output(
            {'state': 'done', 'verification': {'fixture': True}}, enriched,
        )
        runtime_worker_result.accept_and_commit(output, expected)
        runtime_worker_result.accept_and_commit(output, expected)
        self.assertEqual(self.ready(), ('right', 'dependent'))
        self.assertEqual(len(goal_state_store.load(self.path)['evidence']), 1)

    def test_existing_lease_gate_rejects_already_committed_root(self):
        from modules import resource_leases, scheduler_resource_gate
        screen = {
            'id': 'screen', 'depends_on': [],
            'capability_id': 'goal.observe',
            'input': {'kind': 'screen', 'question': 'Describe the visible window'},
            'expected_output': 'verified screen observation',
            'acceptance': 'verified read-only observation',
        }
        state = self.mutate(
            'set_goal_plan', reason='TEST_READ_ONLY_PLAN',
            plan={'plan_version': 2, 'nodes': [screen]},
        )
        table = resource_leases.LeaseTable()
        selected = goal_plan_gate.candidate(
            state, owner=OWNER, job_id=JOB, node_id='screen',
        )
        ticket = scheduler_resource_gate.admit(
            table, state, selected, attempt=1,
        )
        self.assertTrue(table.validate(ticket))
        enriched, expected = runtime_worker_result.prepare(
            ident('screen'), 'observe', screen['input'],
        )
        wrapped = worker_result_hook.wrap_output({
            'state': 'done', 'local_evidence': 'observe', 'owner': OWNER,
            'text': 'synthetic fixture',
        }, enriched)
        runtime_worker_result.accept_and_commit(wrapped, expected)
        newer = goal_state_store.load(self.path)
        fresh = goal_plan_gate.candidate(
            newer, owner=OWNER, job_id=JOB, node_id='screen',
        )
        with self.assertRaises(scheduler_resource_gate.ReadOnlyAdmissionError):
            scheduler_resource_gate.validate_before_dispatch(
                table, newer, fresh, ticket, attempt=1,
            )
        table.release(ticket)
        with self.assertRaises(scheduler_resource_gate.ReadOnlyAdmissionError):
            scheduler_resource_gate.admit(
                table, newer, fresh, attempt=2,
            )
        self.assertFalse(table.occupied('pc_desktop'))

    def test_untrusted_worker_shape_without_worker_accept_audit_is_rejected(self):
        self.mutate(
            'append_evidence', reason='USER_EVIDENCE',
            evidence={'kind': 'worker_result', 'step_id': 'left'},
        )
        with self.assertRaisesRegex(goal_plan_gate.PlanFenceError, 'authority'):
            self.ready()

    def test_worker_accept_reason_without_worker_result_is_rejected(self):
        self.mutate(
            'append_evidence', reason='WORKER_RESULT_ACCEPTED',
            evidence={'kind': 'unverified'},
        )
        with self.assertRaisesRegex(goal_plan_gate.PlanFenceError, 'authority'):
            self.ready()

    def test_current_plan_forged_worker_digest_is_rejected(self):
        self.mutate(
            'append_evidence', reason='WORKER_RESULT_ACCEPTED',
            evidence={
                'kind': 'worker_result', 'owner': OWNER, 'job_id': JOB,
                'step_id': 'left', 'plan_version': 1, 'attempt': 1,
                'status': 'succeeded', 'node_digest': '0' * 64,
            },
        )
        with self.assertRaises(goal_plan_gate.PlanFenceError):
            self.ready()

    def test_tampered_committed_result_digest_or_owner_never_unblocks_a_child(self):
        self.commit('left')
        state = goal_state_store.load(self.path)
        for field, forged in (
            ('node_digest', 'f' * 64),
            ('input_digest', 'f' * 64),
            ('owner', 'mallory'),
            ('capability_version', '99'),
        ):
            with self.subTest(field=field):
                snapshot = copy.deepcopy(state)
                snapshot['evidence'][0][field] = forged
                with self.assertRaises(goal_plan_gate.PlanFenceError):
                    goal_plan_gate.ready_read_only_candidates(
                        snapshot, owner=OWNER, job_id=JOB,
                    )
        self.assertEqual(self.ready(), ('right', 'dependent'))

    def test_evidence_audit_length_mismatch_fails_closed(self):
        self.commit('left')
        snapshot = goal_state_store.load(self.path)
        snapshot['evidence'].append({'kind': 'extra'})
        with self.assertRaisesRegex(goal_plan_gate.PlanFenceError, 'sırası'):
            goal_plan_gate.ready_read_only_candidates(
                snapshot, owner=OWNER, job_id=JOB,
            )

    def test_old_plan_accepted_result_is_not_completion_after_revision(self):
        self.commit('left')
        latest = self.mutate(
            'set_goal_plan', reason='USER_REPLAN',
            plan={'plan_version': 2, 'nodes': self.plan['nodes']},
        )
        self.assertEqual(latest['goal_plan']['plan_version'], 2)
        self.assertEqual(self.ready(), ('left', 'right'))

    def test_unreconciled_user_intent_blocks_stale_readiness_until_replan(self):
        self.commit('left')
        self.mutate(
            'mutate_goal_intent', reason='USER_CORRECTION',
            operation='revise', text='Research a different source',
            priority=None,
        )
        with self.assertRaisesRegex(goal_plan_gate.PlanFenceError, 'plan revalidation'):
            self.ready()
        # A new canonical plan revision (even with the same topology) must
        # precede any fresh eligibility; old-plan success is never reused.
        self.mutate(
            'set_goal_plan', reason='REPLAN_AFTER_CORRECTION',
            plan={'plan_version': 2, 'nodes': self.plan['nodes']},
        )
        self.assertEqual(self.ready(), ('left', 'right'))

    def test_stopped_goal_and_other_owner_cannot_select_ready_nodes(self):
        self.commit('left')
        stopped = self.mutate('set_state', reason='USER_PAUSE', state='paused')
        with self.assertRaises(goal_plan_gate.PlanFenceError):
            goal_plan_gate.ready_read_only_candidates(
                stopped, owner=OWNER, job_id=JOB,
            )
        with self.assertRaises(goal_plan_gate.PlanFenceError):
            goal_plan_gate.ready_read_only_candidates(
                goal_state_store.load(self.path), owner='mallory', job_id=JOB,
            )

    def test_non_read_only_or_unknown_capabilities_are_never_ready(self):
        self.mutate('set_goal_plan', reason='USER_REPLAN', plan={
            'plan_version': 2, 'nodes': [
                node('unknown', capability='task.no-such-tool'),
                node('writer', capability='task.writer'),
                node('read'),
            ],
        })
        self.assertEqual(self.ready(), ('read',))


if __name__ == '__main__':
    unittest.main()
