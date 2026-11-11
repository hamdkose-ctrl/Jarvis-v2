"""BRAIN-07K: actual durable goal/specialist predecessor pre-dispatch fence.

All workers and external effects are mocked. Tests use real canonical
GoalState/WorkerResult CAS and real on-disk ExecutionRecord bytes. A successful
proof does NOT execute a dependent node: BRAIN-06C still explicitly denies it.
"""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import release_guard
from modules import (
    core_state_reducer, dependency_evidence, execution_record,
    goal_executor, goal_plan_gate, goal_state, goal_state_store, goal_tools,
    runtime_worker_result, specialist_orchestrator, worker_result_hook,
)

OWNER = 'alice'
JOB = '0123456789abcdef'
DATA = {'url': 'https://example.test/source', 'question': 'compare'}


def node(step, deps=()):
    return {
        'id': step, 'depends_on': list(deps),
        'capability_id': 'task.research', 'input': copy.deepcopy(DATA),
        'expected_output': 'verified report', 'acceptance': 'verified source',
    }


def identity(step):
    return {
        'version': 1, 'owner': OWNER, 'job_id': JOB,
        'task_id': step, 'attempt': 1, 'request': 'Compare reports',
    }


class DurableSpecialistDependencyGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.owner_root = self.root / OWNER
        self.owner_root.mkdir(parents=True)
        self.canonical_path = self.owner_root / (JOB + '.goalstate.json')
        self.record_path = execution_record.path_for(self.owner_root, JOB)
        initial = goal_state.new(
            owner=OWNER, job_id=JOB, goal='Compare reports',
            authority='canonical',
        )
        self.plan = {'plan_version': 1, 'nodes': [
            node('left'), node('right'), node('child', ('left', 'right')),
        ]}
        planned = core_state_reducer.apply(initial, {
            'op': 'set_goal_plan', 'reason_code': 'TEST_PLAN',
            'plan': self.plan, 'expected_version': initial['version'],
        })
        goal_state_store.create(self.canonical_path, planned)
        st = patch.object(goal_executor, 'STORE', self.root)
        st.start()
        self.addCleanup(st.stop)
        self.job = {
            'id': JOB, 'owner': OWNER, 'request': 'Compare reports',
            'state': 'running', 'goals': [], 'steps': [], 'outputs': {},
            'feedback': [], '_canonical_version': planned['version'],
        }
        self.step = {
            'id': 'child', 'tool': 'research', 'input': copy.deepcopy(DATA),
            'depends': ['left', 'right'], 'state': 'running',
        }
        self.runtime = SimpleNamespace(
            profile=SimpleNamespace(slug=OWNER),
        )
        self.persist()

    def persist(self):
        release_guard.atomic(
            self.record_path, execution_record.encode(self.job),
        )

    def complete(self, name):
        enriched, expected = runtime_worker_result.prepare(
            identity(name), 'research', DATA,
        )
        output = {
            'state': 'done', 'text': 'synthetic verified source ' + name,
            'verification': {'fixture': name, 'test_only': True},
        }
        fenced = worker_result_hook.wrap_output(output, enriched)
        runtime_worker_result.accept_and_commit(fenced, expected)
        self.job['outputs'][name] = copy.deepcopy(output)
        self.persist()

    def both(self):
        self.complete('left')
        self.complete('right')

    def attempt(self, *, step=None, identity_override=None):
        return specialist_orchestrator._execute_step(
            self.runtime, self.job, step if step is not None else self.step,
            identity_override if identity_override is not None
            else identity(self.step['id']),
        )

    def test_valid_persisted_parents_are_verified_then_dispatch_still_denied(self):
        self.both()
        with (patch.object(goal_tools, 'verify', return_value=True) as verify,
              patch('modules.runtime_execution_gate.plan_task',
                    return_value={'phase': 'execute'}) as decision,
              patch.object(goal_tools, 'execute') as worker):
            with self.assertRaisesRegex(ValueError, 'Bağımlı'):
                self.attempt()
        self.assertEqual(verify.call_count, 2)
        decision.assert_called_once()
        worker.assert_not_called()
        self.assertEqual(len(goal_state_store.load(self.canonical_path)['evidence']), 2)

    def test_good_preflight_returns_only_defensive_journal_copies(self):
        self.both()
        with patch.object(goal_tools, 'verify', return_value=True) as verify:
            proof = dependency_evidence.preflight_durable_step(
                identity('child'), self.step, self.job['outputs'],
                owner=OWNER, job_id=JOB,
            )
        self.assertEqual(proof, self.job['outputs'])
        self.assertIsNot(proof['left'], self.job['outputs']['left'])
        proof['left']['text'] = 'tampered returned copy'
        self.assertNotEqual(proof['left'], self.job['outputs']['left'])
        self.assertEqual(
            execution_record.load(self.owner_root, OWNER, JOB)['outputs'],
            self.job['outputs'],
        )
        self.assertEqual(verify.call_count, 2)

    def test_old_success_without_accepted_output_commitment_cannot_handoff(self):
        enriched, expected = runtime_worker_result.prepare(
            identity('left'), 'research', DATA,
        )
        output = {
            'state': 'done', 'text': 'pre-digest legacy success',
            'verification': {'fixture': 'old', 'test_only': True},
        }
        wrapped = worker_result_hook.wrap_output(output, enriched)
        wrapped['_worker_result']['evidence'][0].pop('output_sha256')
        runtime_worker_result.accept_and_commit(wrapped, expected)
        self.job['outputs']['left'] = copy.deepcopy(output)
        self.persist()
        self.complete('right')
        with (patch.object(goal_tools, 'verify') as verify,
              patch('modules.runtime_execution_gate.plan_task') as decision,
              patch.object(goal_tools, 'execute') as worker):
            with self.assertRaises(goal_plan_gate.PlanFenceError):
                self.attempt()
        verify.assert_not_called()
        decision.assert_not_called()
        worker.assert_not_called()

    def test_unaccepted_predecessor_fails_before_any_decision_or_worker(self):
        self.complete('left')
        with (patch.object(goal_tools, 'verify', return_value=True) as verify,
              patch('modules.runtime_execution_gate.plan_task') as decision,
              patch.object(goal_tools, 'execute') as worker):
            with self.assertRaises(goal_plan_gate.PlanFenceError):
                self.attempt()
        verify.assert_not_called()
        decision.assert_not_called()
        worker.assert_not_called()

    def test_mutated_in_memory_output_fails_before_worker(self):
        self.both()
        self.job['outputs']['left']['text'] = 'unpersisted forged report'
        with (patch.object(goal_tools, 'verify') as verify,
              patch('modules.runtime_execution_gate.plan_task') as decision,
              patch.object(goal_tools, 'execute') as worker):
            with self.assertRaisesRegex(goal_plan_gate.PlanFenceError, 'In-memory'):
                self.attempt()
        verify.assert_not_called()
        decision.assert_not_called()
        worker.assert_not_called()

    def test_mutated_persisted_output_fails_before_worker(self):
        self.both()
        edited = execution_record.load(self.owner_root, OWNER, JOB)
        edited['outputs']['left']['text'] = 'tampered disk journal'
        release_guard.atomic(self.record_path, execution_record.encode(edited))
        with (patch.object(goal_tools, 'verify') as verify,
              patch('modules.runtime_execution_gate.plan_task') as decision,
              patch.object(goal_tools, 'execute') as worker):
            with self.assertRaises(goal_plan_gate.PlanFenceError):
                self.attempt()
        verify.assert_not_called()
        decision.assert_not_called()
        worker.assert_not_called()

    def test_joint_tampering_cannot_bypass_canonical_output_digest(self):
        self.both()
        self.job['outputs']['left']['text'] = 'forged same output on disk'
        self.persist()
        with (patch.object(goal_tools, 'verify') as verify,
              patch('modules.runtime_execution_gate.plan_task') as decision,
              patch.object(goal_tools, 'execute') as worker):
            with self.assertRaisesRegex(goal_plan_gate.PlanFenceError, 'differs'):
                self.attempt()
        verify.assert_not_called()
        decision.assert_not_called()
        worker.assert_not_called()

    def test_missing_durable_journal_is_not_a_source_of_proof(self):
        self.both()
        self.record_path.unlink()
        with (patch.object(goal_tools, 'verify') as verify,
              patch('modules.runtime_execution_gate.plan_task') as decision,
              patch.object(goal_tools, 'execute') as worker):
            with self.assertRaisesRegex(goal_plan_gate.PlanFenceError, 'persisted'):
                self.attempt()
        verify.assert_not_called()
        decision.assert_not_called()
        worker.assert_not_called()

    def test_wrong_dependency_order_or_tool_or_input_is_blocked(self):
        self.both()
        for change in (
            {'depends': ['right', 'left']},
            {'depends': ['left']},
            {'input': {'url': 'https://different.test', 'question': 'compare'}},
            {'tool': 'account'},
            {'id': 'different'},
        ):
            with self.subTest(change=change):
                step = {**self.step, **change}
                with (patch.object(goal_tools, 'verify') as verify,
                      patch('modules.runtime_execution_gate.plan_task') as decision,
                      patch.object(goal_tools, 'execute') as worker):
                    with self.assertRaises(goal_plan_gate.PlanFenceError):
                        self.attempt(step=step)
                verify.assert_not_called()
                decision.assert_not_called()
                worker.assert_not_called()

    def test_legacy_identity_cannot_bypass_a_canonical_dependent(self):
        self.both()
        legacy = {'owner': OWNER, 'job_id': JOB, 'task_id': 'child'}
        with (patch.object(goal_tools, 'verify') as verify,
              patch('modules.runtime_execution_gate.plan_task') as decision,
              patch.object(goal_tools, 'execute') as worker):
            with self.assertRaisesRegex(goal_plan_gate.PlanFenceError,
                                         'requires durable'):
                self.attempt(identity_override=legacy)
        verify.assert_not_called()
        decision.assert_not_called()
        worker.assert_not_called()

    def test_foreign_owner_execution_identity_is_blocked(self):
        self.both()
        forged = dict(identity('child'), owner='mallory')
        with (patch.object(goal_tools, 'verify') as verify,
              patch('modules.runtime_execution_gate.plan_task') as decision,
              patch.object(goal_tools, 'execute') as worker):
            with self.assertRaisesRegex(goal_plan_gate.PlanFenceError,
                                         'identity differs'):
                self.attempt(identity_override=forged)
        verify.assert_not_called()
        decision.assert_not_called()
        worker.assert_not_called()

    def test_explicit_user_correction_blocks_preflight(self):
        self.both()
        state = goal_state_store.load(self.canonical_path)
        revised = core_state_reducer.apply(state, {
            'op': 'mutate_goal_intent', 'operation': 'revise',
            'text': 'Use another source', 'priority': None,
            'reason_code': 'USER_CORRECTION',
            'expected_version': state['version'],
        })
        goal_state_store.compare_and_swap(
            self.canonical_path,
            expected_version=state['version'], next_state=revised,
        )
        with (patch.object(goal_tools, 'verify') as verify,
              patch('modules.runtime_execution_gate.plan_task') as decision,
              patch.object(goal_tools, 'execute') as worker):
            with self.assertRaises(goal_plan_gate.PlanFenceError):
                self.attempt()
        verify.assert_not_called()
        decision.assert_not_called()
        worker.assert_not_called()

    def test_record_preflight_rejects_bad_inputs_before_running_checkpoint(self):
        self.both()
        self.job['outputs']['right']['text'] = 'fake last-minute result'
        self.step['state'] = 'pending'
        with (patch.object(goal_executor, '_save') as save,
              patch.object(goal_tools, 'checkpoint') as checkpoint,
              patch('modules.specialist_orchestrator.execute_step') as worker,
              patch.object(goal_tools, 'verify') as verify):
            with self.assertRaises(goal_plan_gate.PlanFenceError):
                goal_executor._record(self.runtime, self.job, self.step)
        save.assert_not_called()
        checkpoint.assert_not_called()
        worker.assert_not_called()
        verify.assert_not_called()
        self.assertEqual(self.step['state'], 'pending')

    def test_planned_dependency_requires_actual_domain_readback(self):
        self.both()
        with (patch.object(goal_tools, 'verify',
                           side_effect=ValueError('stale artifact')) as verify,
              patch('modules.runtime_execution_gate.plan_task') as decision,
              patch.object(goal_tools, 'execute') as worker):
            with self.assertRaisesRegex(goal_plan_gate.PlanFenceError, 'verifiable'):
                self.attempt()
        verify.assert_called_once()
        decision.assert_not_called()
        worker.assert_not_called()

    def test_dependency_stripping_cannot_skip_specialist_preflight(self):
        self.both()
        for claimed in ([], None, ()):
            with self.subTest(depends=claimed):
                altered = {**self.step, 'depends': claimed}
                with (patch.object(goal_tools, 'verify') as verify,
                      patch('modules.runtime_execution_gate.plan_task') as decision,
                      patch.object(goal_tools, 'execute') as worker):
                    with self.assertRaises(goal_plan_gate.PlanFenceError):
                        self.attempt(step=altered)
                verify.assert_not_called()
                decision.assert_not_called()
                worker.assert_not_called()

    def test_dependency_stripping_and_legacy_identity_cannot_downgrade(self):
        self.both()
        old_identity = {'owner': OWNER, 'job_id': JOB, 'task_id': 'child'}
        altered = {**self.step, 'depends': []}
        with (patch('modules.runtime_execution_gate.plan_task') as decision,
              patch.object(goal_tools, 'execute') as worker):
            with self.assertRaisesRegex(goal_plan_gate.PlanFenceError, 'requires durable'):
                self.attempt(step=altered, identity_override=old_identity)
        decision.assert_not_called()
        worker.assert_not_called()

    def test_record_cannot_checkpoint_when_dependency_list_is_stripped(self):
        self.both()
        for claimed in ([], None):
            with self.subTest(depends=claimed):
                altered = {**self.step, 'depends': claimed, 'state': 'pending'}
                with (patch.object(goal_executor, '_save') as save,
                      patch.object(goal_tools, 'checkpoint') as checkpoint,
                      patch('modules.specialist_orchestrator.execute_step') as worker):
                    with self.assertRaises(goal_plan_gate.PlanFenceError):
                        goal_executor._record(self.runtime, self.job, altered)
                save.assert_not_called()
                checkpoint.assert_not_called()
                worker.assert_not_called()
                self.assertEqual(altered['state'], 'pending')

    def test_record_preflight_does_not_depend_on_transient_version_marker(self):
        self.both()
        self.job.pop('_canonical_version')
        altered = {**self.step, 'depends': [], 'state': 'pending'}
        with (patch.object(dependency_evidence, 'preflight_durable_step',
                           wraps=dependency_evidence.preflight_durable_step) as preflight,
              patch.object(goal_executor, '_save') as save,
              patch.object(goal_tools, 'checkpoint') as checkpoint,
              patch('modules.specialist_orchestrator.execute_step') as worker):
            with self.assertRaises(goal_plan_gate.PlanFenceError):
                goal_executor._record(self.runtime, self.job, altered)
        preflight.assert_called_once()
        save.assert_not_called()
        checkpoint.assert_not_called()
        worker.assert_not_called()
        self.assertEqual(altered['state'], 'pending')

    def test_missing_canonical_record_fails_closed_for_bound_specialist(self):
        self.both()
        self.canonical_path.unlink()
        with (patch('modules.runtime_execution_gate.plan_task') as decision,
              patch.object(goal_tools, 'execute') as worker):
            with self.assertRaisesRegex(goal_plan_gate.PlanFenceError,
                                         'canonical GoalState'):
                self.attempt()
        decision.assert_not_called()
        worker.assert_not_called()

    def test_explicit_plan_identity_cannot_downgrade_when_state_missing(self):
        self.both()
        self.canonical_path.unlink()
        hinted = {**identity('child'), 'plan_version': 1}
        with patch('modules.runtime_execution_gate.plan_task') as decision:
            with self.assertRaisesRegex(goal_plan_gate.PlanFenceError,
                                         'canonical GoalState'):
                self.attempt(identity_override=hinted)
        decision.assert_not_called()

    def test_partial_plan_identity_cannot_use_legacy_fallback(self):
        self.both()
        self.canonical_path.unlink()
        downgraded_job = {key: value for key, value in self.job.items()
                          if key != '_canonical_version'}
        for hint in ('plan_version', 'node_digest'):
            with self.subTest(hint=hint):
                downgraded_identity = dict(identity('child'))
                downgraded_identity.pop('version')
                downgraded_identity[hint] = (
                    1 if hint == 'plan_version' else 'a' * 64
                )
                with (patch('modules.runtime_execution_gate.plan_task') as decision,
                      patch.object(goal_tools, 'execute') as worker):
                    with self.assertRaisesRegex(goal_plan_gate.PlanFenceError,
                                                 'plan fence requires durable'):
                        specialist_orchestrator._execute_step(
                            self.runtime, downgraded_job, self.step,
                            downgraded_identity,
                        )
                decision.assert_not_called()
                worker.assert_not_called()

    def test_legacy_versioned_identity_without_canonical_sidecar_is_unplanned(self):
        legacy_identity = {'version': 1, 'owner': OWNER,
                           'job_id': 'job-1', 'task_id': 'root'}
        self.assertIsNone(dependency_evidence.preflight_durable_step(
            legacy_identity,
            {'id': 'root', 'tool': 'research', 'input': DATA, 'depends': []},
            {}, owner=OWNER, job_id='job-1',
        ))

    def test_canonical_step_rejects_missing_execution_job_id(self):
        self.both()
        missing = {key:value for key,value in self.job.items() if key != 'id'}
        with patch('modules.runtime_execution_gate.plan_task') as decision:
            with self.assertRaisesRegex(goal_plan_gate.PlanFenceError,
                                         'ExecutionRecord job ID'):
                specialist_orchestrator._execute_step(
                    self.runtime, missing, self.step, identity('child'),
                )
        decision.assert_not_called()

    def test_unplanned_legacy_dependency_behavior_is_unchanged(self):
        state = goal_state_store.load(self.canonical_path)
        # Replace test fixture with a standalone canonical snapshot without
        # a plan, to represent legacy compatibility execution.
        from modules import goal_state
        no_plan = goal_state.new(
            owner=OWNER, job_id=JOB, goal='Compare reports',
            authority='canonical',
        )
        self.canonical_path.unlink()
        goal_state_store.create(self.canonical_path, no_plan)
        self.job['outputs'] = {
            'left': {'state': 'done', 'text': 'legacy journal output'},
        }
        self.step['depends'] = ['left']
        self.persist()
        with (patch('modules.runtime_execution_gate.plan_task',
                    return_value={'phase': 'execute'}),
              patch.object(goal_tools, 'execute',
                           return_value={'state': 'done', 'text': 'legacy worker output'}) as worker):
            # Unplanned durable execution still has WorkerResult.v1 handling.
            # Its domain verifier and exact CAS remains the existing path.
            with patch.object(goal_tools, 'verify', return_value=True):
                result = self.attempt()
        self.assertEqual(result['state'], 'done')
        worker.assert_called_once()
        self.assertEqual(worker.call_args.args[3]['left']['text'],
                         'legacy journal output')


if __name__ == '__main__':
    unittest.main()
