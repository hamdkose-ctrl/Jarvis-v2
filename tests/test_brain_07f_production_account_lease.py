"""BRAIN-07F: existing durable account-read worker owns a live ResourceLease.

Real canonical GoalState and WorkerResult CAS; synthetic account results only.
No Gmail/network, model, login, effect, new Scheduler or desktop automation.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from modules import (
    core_state_reducer, goal_executor, goal_state, goal_state_store,
    goal_tools, resource_leases, runtime_worker_result,
    scheduler_resource_gate, specialist_orchestrator, worker_result_hook,
)

OWNER = 'alice'
JOB = '0123456789abcdef'
DATA = {'service': 'gmail', 'operation': 'list_unread', 'limit': 3}


def identity(attempt=1):
    return {'version': 1, 'owner': OWNER, 'job_id': JOB, 'task_id': 'mail',
            'attempt': attempt, 'request': 'Read unread mail'}


class LiveCanonicalAccountLeaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / OWNER / (JOB + '.goalstate.json')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        init = goal_state.new(
            owner=OWNER, job_id=JOB, goal='Read mail metadata',
            authority='canonical',
        )
        self.plan = {'plan_version': 1, 'nodes': [{
            'id': 'mail', 'depends_on': [], 'capability_id': 'task.account',
            'input': dict(DATA), 'expected_output': 'Verified account metadata',
            'acceptance': 'Verified immutable account response',
        }]}
        planned = core_state_reducer.apply(init, {
            'op': 'set_goal_plan', 'plan': self.plan, 'expected_version': 0,
            'reason_code': 'TEST_PLAN',
        })
        goal_state_store.create(self.path, planned)
        self.now = [100.0]
        self.table = resource_leases.LeaseTable(clock=lambda: self.now[0])
        for module, attr, value in (
            (goal_executor, 'STORE', self.root),
            (goal_executor, '_RESOURCE_LEASES', self.table),
        ):
            p = patch.object(module, attr, value)
            p.start()
            self.addCleanup(p.stop)
        self.runtime = SimpleNamespace(profile=SimpleNamespace(slug=OWNER))
        self.job = {
            'id': JOB, 'owner': OWNER, 'request': 'Read unread mail',
            'state': 'running', 'outputs': {},
        }
        self.step = {
            'id': 'mail', 'tool': 'account', 'input': dict(DATA),
            'depends': [], 'state': 'running',
        }

    def mutate(self, op, *, reason, **kwargs):
        old = goal_state_store.load(self.path)
        changed = core_state_reducer.apply(old, {
            'op': op, 'expected_version': old['version'],
            'reason_code': reason, **kwargs,
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=old['version'], next_state=changed,
        )

    def run_worker(self, output=None, *, attempt=1, callback=None):
        if output is None:
            output = {'state': 'done', 'text': 'fake account read',
                      'verification': {'source': 'test fixture'}}
        def worker(*args, **kwargs):
            if callback is not None:
                callback()
            return output
        with (patch('modules.runtime_execution_gate.plan_task',
                    return_value={'phase': 'execute'}),
              patch('modules.effect_recovery_runtime.required', return_value=False),
              patch.object(goal_tools, 'verify', return_value=True),
              patch.object(goal_tools, 'execute', side_effect=worker) as execute):
            result = specialist_orchestrator._execute_step(
                self.runtime, self.job, self.step, identity(attempt),
            )
        return result, execute

    def test_account_read_claim_is_held_through_cas_and_released(self):
        result, execute = self.run_worker(callback=lambda: self.assertEqual(
            sum(self.table.occupied(k) for k in list(self.table._holders)), 1,
        ))
        self.assertEqual(result['state'], 'done')
        execute.assert_called_once()
        state = goal_state_store.load(self.path)
        self.assertEqual(state['version'], 2)
        self.assertEqual(len(state['evidence']), 1)
        self.assertEqual(state['evidence'][0]['capability_id'], 'task.account')
        self.assertEqual(state['evidence'][0]['status'], 'succeeded')
        self.assertEqual(self.table._holders, {})
        self.assertEqual(self.table._commands, {})

    def test_duplicate_worker_cannot_acquire_second_live_ticket(self):
        def competing_dispatch():
            with self.assertRaises(resource_leases.LeaseConflict):
                # The second dispatch must fail before goal_tools.execute.
                specialist_orchestrator._execute_step(
                    self.runtime, self.job, self.step, identity(),
                )
        result, worker = self.run_worker(callback=competing_dispatch)
        self.assertEqual(result['state'], 'done')
        worker.assert_called_once()
        self.assertEqual(len(goal_state_store.load(self.path)['evidence']), 1)
        self.assertEqual(self.table._holders, {})

    def test_user_intent_change_during_account_read_fails_before_cas(self):
        def change_intent():
            self.mutate(
                'mutate_goal_intent', reason='USER_CORRECTION',
                operation='revise', text='Do not read this account',
                priority=None,
            )
        with self.assertRaises(ValueError):
            self.run_worker(callback=change_intent)
        self.assertEqual(goal_state_store.load(self.path)['evidence'], [])
        self.assertEqual(self.table._holders, {})

    def test_expired_or_stolen_ticket_does_not_commit_worker_claim(self):
        with self.assertRaises(scheduler_resource_gate.ReadOnlyAdmissionError):
            self.run_worker(callback=lambda: self.now.__setitem__(0, 200.0))
        self.assertEqual(goal_state_store.load(self.path)['evidence'], [])
        self.assertEqual(self.table._holders, {})

    def test_failed_account_read_may_be_explicitly_retried_with_new_attempt(self):
        failed, first = self.run_worker(
            {'state': 'failed', 'text': 'unavailable'},
        )
        self.assertEqual(failed['state'], 'failed')
        first.assert_called_once()
        self.assertEqual(
            goal_state_store.load(self.path)['evidence'][0]['status'], 'failed',
        )
        completed, second = self.run_worker(attempt=2)
        self.assertEqual(completed['state'], 'done')
        second.assert_called_once()
        self.assertEqual(
            [row['status'] for row in goal_state_store.load(self.path)['evidence']],
            ['failed', 'succeeded'],
        )
        self.assertEqual(self.table._holders, {})

    def test_worker_result_cannot_commit_account_success_without_core_lease(self):
        enriched, expected = runtime_worker_result.prepare(
            identity(), 'account', dict(DATA),
        )
        output = worker_result_hook.wrap_output(
            {'state': 'done', 'verification': {'fixture': True}}, enriched,
        )
        with self.assertRaises(scheduler_resource_gate.ReadOnlyAdmissionError):
            runtime_worker_result.accept_and_commit(output, expected)
        self.assertEqual(goal_state_store.load(self.path)['evidence'], [])

    def test_revised_plan_invalidates_live_ticket_before_result_cas(self):
        def replan():
            self.mutate(
                'set_goal_plan', reason='USER_REPLAN',
                plan={'plan_version': 2, 'nodes': self.plan['nodes']},
            )
        with self.assertRaises(ValueError):
            self.run_worker(callback=replan)
        self.assertEqual(goal_state_store.load(self.path)['evidence'], [])
        self.assertEqual(self.table._holders, {})


if __name__ == '__main__':
    unittest.main()
