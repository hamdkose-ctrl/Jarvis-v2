"""BRAIN-07J: canonical accepted predecessor output-to-journal binding.

Uses real GoalState reducer/CAS and WorkerResult acceptance, but synthetic
outputs and no external workers. Verifier is mocked only for synthetic
fixture outputs that do not contain real provider/file readback receipts.
"""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import (
    core_state_reducer, dependency_evidence, goal_plan_gate, goal_state,
    goal_state_store, runtime_worker_result, worker_result_hook,
)

OWNER = 'alice'
JOB = '0123456789abcdef'
DATA = {'url': 'https://example.test/source', 'question': 'compare'}


def node(step, deps=()):
    return {
        'id': step, 'depends_on': list(deps),
        'capability_id': 'task.research', 'input': dict(DATA),
        'expected_output': 'source report', 'acceptance': 'verified source',
    }


def identity(step, attempt=1):
    return {'version': 1, 'owner': OWNER, 'job_id': JOB,
            'task_id': step, 'attempt': attempt, 'request': 'compare'}


class AcceptedPredecessorBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / OWNER / (JOB + '.goalstate.json')
        self.path.parent.mkdir(parents=True)
        state = goal_state.new(
            owner=OWNER, job_id=JOB, goal='Compare two reports',
            authority='canonical',
        )
        self.plan = {'plan_version': 1, 'nodes': [
            node('left'), node('right'),
            node('child', ('left', 'right')),
            node('grandchild', ('child',)),
        ]}
        state = core_state_reducer.apply(state, {
            'op': 'set_goal_plan', 'plan': self.plan,
            'reason_code': 'TEST_PLAN',
            'expected_version': state['version'],
        })
        goal_state_store.create(self.path, state)
        from modules import goal_executor
        p = patch.object(goal_executor, 'STORE', self.root)
        p.start()
        self.addCleanup(p.stop)
        self.outputs = {}

    def state(self):
        return goal_state_store.load(self.path)

    def selection(self, step='child'):
        return goal_plan_gate.candidate(
            self.state(), owner=OWNER, job_id=JOB, node_id=step,
        )

    def make(self, step, *, attempt=1, status='done'):
        output = {
            'state': status, 'text': 'synthetic report: ' + step,
            'verification': {'fixture': step, 'test_only': True},
        }
        enriched, expected = runtime_worker_result.prepare(
            identity(step, attempt), 'research', DATA,
        )
        wrapped = worker_result_hook.wrap_output(output, enriched)
        return output, wrapped, expected

    def commit(self, step, *, attempt=1, status='done', legacy_proof=False):
        output, wrapped, expected = self.make(
            step, attempt=attempt, status=status,
        )
        if legacy_proof:
            wrapped['_worker_result']['evidence'][0].pop('output_sha256')
        runtime_worker_result.accept_and_commit(wrapped, expected)
        if status == 'done':
            self.outputs[step] = copy.deepcopy(output)
        return wrapped

    def resolve(self):
        return dependency_evidence.bind_predecessor_outputs(
            self.state(), self.selection(), self.outputs,
        )

    def mutate(self, op, *, reason, **rest):
        before = self.state()
        after = core_state_reducer.apply(before, {
            'op': op, 'reason_code': reason,
            'expected_version': before['version'], **rest,
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=before['version'],
            next_state=after,
        )

    def test_successful_roots_bind_exact_journal_outputs_to_current_evidence(self):
        self.commit('left')
        self.commit('right')
        canonical = self.state()
        self.assertEqual(
            [row['step_id'] for row in canonical['evidence']],
            ['left', 'right'],
        )
        for row in canonical['evidence']:
            proof = row['evidence'][0]
            self.assertEqual(
                proof['output_sha256'],
                dependency_evidence.output_sha256(self.outputs[row['step_id']]),
            )
        with patch('modules.goal_tools.verify', return_value=True) as verify:
            selected = self.resolve()
        self.assertEqual(selected, self.outputs)
        self.assertIsNot(selected['left'], self.outputs['left'])
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(
            [c.node_id for c in goal_plan_gate.ready_read_only_candidates(
                canonical, owner=OWNER, job_id=JOB,
            )],
            ['child'],
        )
        # A committed child is still required before its grandchild is ready.
        with self.assertRaises(goal_plan_gate.PlanFenceError):
            dependency_evidence.bind_predecessor_outputs(
                canonical, self.selection('grandchild'), self.outputs,
            )

    def test_tampered_journal_body_fails_even_when_state_says_done(self):
        self.commit('left')
        self.commit('right')
        self.outputs['left']['text'] = 'forged result'
        with patch('modules.goal_tools.verify', return_value=True) as verify:
            with self.assertRaisesRegex(goal_plan_gate.PlanFenceError, 'differs'):
                self.resolve()
        verify.assert_not_called()

    def test_journal_verification_metadata_must_match_accepted_fence(self):
        self.commit('left')
        self.commit('right')
        self.outputs['right']['verification'] = {'fixture': 'something else'}
        with patch('modules.goal_tools.verify', return_value=True) as verify:
            with self.assertRaises(goal_plan_gate.PlanFenceError):
                self.resolve()
        # The other predecessor can be verified before a later one fails;
        # no dependent worker is executed by this projection.
        self.assertEqual(verify.call_count, 1)

    def test_missing_predecessor_journal_or_unsigned_old_success_fails(self):
        self.commit('left')
        self.commit('right')
        self.outputs.pop('right')
        with patch('modules.goal_tools.verify', return_value=True):
            with self.assertRaises(goal_plan_gate.PlanFenceError):
                self.resolve()

        # Older successful evidence remains accepted for topology/readiness,
        # but may never turn into an unproven dependent worker input.
        with self.subTest('older-unbound-output'):
            self.temp.cleanup()
            self.setUp()
            self.commit('left', legacy_proof=True)
            self.commit('right')
            self.assertIn(
                'child', [c.node_id for c in goal_plan_gate.ready_read_only_candidates(
                    self.state(), owner=OWNER, job_id=JOB,
                )],
            )
            with patch('modules.goal_tools.verify', return_value=True):
                with self.assertRaises(goal_plan_gate.PlanFenceError):
                    self.resolve()

    def test_domain_readback_must_pass_again_not_merely_match_digest(self):
        self.commit('left')
        self.commit('right')
        with patch('modules.goal_tools.verify',
                   side_effect=ValueError('source receipt changed')) as verify:
            with self.assertRaisesRegex(goal_plan_gate.PlanFenceError, 'verifiable'):
                self.resolve()
        verify.assert_called_once()

    def test_domain_verifier_false_is_not_success(self):
        self.commit('left')
        self.commit('right')
        with patch('modules.goal_tools.verify', return_value=False):
            with self.assertRaisesRegex(goal_plan_gate.PlanFenceError, 'confirm'):
                self.resolve()

    def test_replan_or_user_correction_cannot_use_old_predecessor_result(self):
        self.commit('left')
        self.commit('right')
        stale = self.selection()
        self.mutate(
            'mutate_goal_intent', reason='USER_CORRECTION',
            operation='revise', text='Read a different source', priority=None,
        )
        with patch('modules.goal_tools.verify', return_value=True):
            with self.assertRaises(goal_plan_gate.PlanFenceError):
                dependency_evidence.bind_predecessor_outputs(
                    self.state(), self.selection(), self.outputs,
                )
        self.mutate(
            'set_goal_plan', reason='USER_REPLAN',
            plan={'plan_version': 2, 'nodes': self.plan['nodes']},
        )
        with patch('modules.goal_tools.verify', return_value=True):
            with self.assertRaises(goal_plan_gate.PlanFenceError):
                dependency_evidence.bind_predecessor_outputs(
                    self.state(), stale, self.outputs,
                )
            with self.assertRaises(goal_plan_gate.PlanFenceError):
                self.resolve()

    def test_paused_goal_cannot_bind_even_with_accepted_output(self):
        self.commit('left')
        self.commit('right')
        self.mutate('set_state', reason='USER_PAUSE', state='paused')
        with patch('modules.goal_tools.verify', return_value=True):
            with self.assertRaises(goal_plan_gate.PlanFenceError):
                self.resolve()

    def test_failed_root_requires_explicit_new_attempt_before_child_can_bind(self):
        self.commit('left', status='failed')
        self.commit('right')
        with patch('modules.goal_tools.verify', return_value=True):
            with self.assertRaises(goal_plan_gate.PlanFenceError):
                self.resolve()
        self.commit('left', attempt=2)
        with patch('modules.goal_tools.verify', return_value=True):
            picked = self.resolve()
        self.assertEqual(set(picked), {'left', 'right'})
        left_rows = [
            row for row in self.state()['evidence']
            if row['step_id'] == 'left'
        ]
        self.assertEqual(
            [r['status'] for r in left_rows], ['failed', 'succeeded'],
        )

    def test_unplanned_result_is_not_upgraded_by_transport_wrapper(self):
        _, _, expected = self.make('left')
        legacy_identity = dict(identity('left'))
        legacy_identity.update({
            k: expected[k] for k in (
                'owner', 'job_id', 'step_id', 'command_id', 'attempt',
                'expected_job_version', 'capability_id',
                'capability_version', 'input_digest',
            )
        })
        wrapped = worker_result_hook.wrap_output(
            {'state': 'done', 'verification': {'fixture': 'legacy'}},
            legacy_identity,
        )
        self.assertNotIn('output_sha256', wrapped['_worker_result']['evidence'][0])
        self.assertNotIn(
            'output_sha256', worker_result_hook.wrap_output(
                {'state': 'failed'}, legacy_identity,
            )['_worker_result']['evidence'][0],
        )

    def test_clean_result_digest_ignores_transport_envelope(self):
        output, wrapped, _ = self.make('left')
        self.assertEqual(
            dependency_evidence.output_sha256(wrapped),
            dependency_evidence.output_sha256(output),
        )


if __name__ == '__main__':
    unittest.main()
