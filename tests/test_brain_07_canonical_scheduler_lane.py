"""BRAIN-07 Scheduler readiness offer tests; no real worker or second loop.

Real canonical CAS, exact ExecutionRecord bytes and predecessor-proof
projection are used; external providers and desktop remain untouched.
"""
from __future__ import annotations

import copy
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import release_guard
from modules import (
    canonical_output_projection, canonical_scheduler_dispatch,
    canonical_scheduler_lane, core_state_reducer, execution_record,
    goal_executor, goal_state, goal_state_store, goal_tools,
    runtime_worker_result, task_agents, task_results, untrusted_flow,
    worker_result_hook,
)

OWNER = 'alice'
JOB = '0123456789abcdef'
DATA = {'url': 'https://example.test/article', 'question': 'compare'}


def node(name, depends=(), cap='task.research'):
    return {
        'id': name, 'depends_on': list(depends), 'capability_id': cap,
        'input': dict(DATA), 'expected_output': 'verified result',
        'acceptance': 'source-backed proof',
    }


class SchedulerOfferTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Path(temp.name)
        self.owner_root = self.store / OWNER
        self.owner_root.mkdir()
        self.path = self.owner_root / (JOB + '.goalstate.json')
        self.record_path = execution_record.path_for(self.owner_root, JOB)
        self.nodes = [node('left'), node('right'), node('child', ('left',))]
        state = goal_state.new(
            owner=OWNER, job_id=JOB, goal='Read two sources',
            authority='canonical',
        )
        state = core_state_reducer.apply(state, {
            'op': 'set_goal_plan', 'plan': {'plan_version': 1, 'nodes': self.nodes},
            'expected_version': state['version'], 'reason_code': 'TEST_PLAN',
        })
        goal_state_store.create(self.path, state)
        job = {
            'id': JOB, 'owner': OWNER, 'request': 'Read two sources',
            'state': 'running', 'goals': [],
            'steps': [
                {
                    'id': row['id'], 'tool': 'research',
                    'input': copy.deepcopy(DATA),
                    'depends': list(row['depends_on']), 'state': 'queued',
                }
                for row in self.nodes
            ],
            'outputs': {},
        }
        release_guard.atomic(self.record_path, execution_record.encode(job))
        patch_store = patch.object(goal_executor, 'STORE', self.store)
        patch_store.start()
        self.addCleanup(patch_store.stop)

    def offers(self):
        return canonical_scheduler_lane.ready_offers(OWNER, JOB)

    def accept(self, step, *, state='done'):
        output = {
            'state': state, 'text': 'evidence ' + step,
            'verification': {'test': step},
        }
        identity = {
            'version': 1, 'owner': OWNER, 'job_id': JOB, 'task_id': step,
            'attempt': 1, 'request': 'Read two sources',
        }
        enriched, expected = runtime_worker_result.prepare(
            identity, 'research', dict(DATA),
        )
        wrapped = worker_result_hook.wrap_output(output, enriched)
        runtime_worker_result.accept_and_commit(wrapped, expected)
        return output

    def test_initial_independent_roots_only_and_strict_limit(self):
        self.assertEqual(
            [offer.selection.node_id for offer in self.offers()],
            ['left', 'right'],
        )
        self.assertEqual(len(canonical_scheduler_lane.ready_offers(
            OWNER, JOB, limit=1,
        )), 1)
        with self.assertRaises(canonical_scheduler_lane.DispatchFenceError):
            canonical_scheduler_lane.ready_offers(OWNER, JOB, limit=0)

    def test_offer_rechecks_exact_record_snapshot(self):
        original = self.offers()[0]
        self.assertEqual(canonical_scheduler_lane.revalidate_offer(original), original)
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['feedback'] = ['new task plan or operator input']
        release_guard.atomic(self.record_path, execution_record.encode(job))
        with self.assertRaises(canonical_scheduler_lane.DispatchFenceError):
            canonical_scheduler_lane.revalidate_offer(original)

    def test_accepted_parent_without_projected_output_cannot_wake_child(self):
        result = self.accept('left')
        self.assertEqual([v.selection.node_id for v in self.offers()], ['right'])
        canonical_output_projection.project_accepted(OWNER, JOB, 'left', result)
        with patch.object(goal_tools, 'verify', return_value=True) as verified:
            ready = self.offers()
            self.assertEqual(
                [offer.selection.node_id for offer in ready],
                ['right', 'child'],
            )
            canonical_scheduler_lane.revalidate_offer(ready[-1])
            verified.assert_called()

    def test_user_intent_edit_invalidates_previous_offer(self):
        before = self.offers()[0]
        old = goal_state_store.load(self.path)
        new = core_state_reducer.apply(old, {
            'op': 'mutate_goal_intent', 'operation': 'revise',
            'text': 'Change the research goal', 'priority': None,
            'expected_version': old['version'], 'reason_code': 'USER_CORRECTION',
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=old['version'], next_state=new,
        )
        with self.assertRaises(canonical_scheduler_lane.DispatchFenceError):
            canonical_scheduler_lane.revalidate_offer(before)

    def test_mismatched_published_step_rejected_without_worker(self):
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['steps'][0]['input']['url'] = 'https://foreign.test'
        release_guard.atomic(self.record_path, execution_record.encode(job))
        with self.assertRaises(canonical_scheduler_lane.DispatchFenceError):
            self.offers()

    def test_completed_step_or_started_step_is_never_offered(self):
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['steps'][0]['state'] = 'running'
        job['steps'][0]['attempts'] = 1
        release_guard.atomic(self.record_path, execution_record.encode(job))
        self.assertEqual([v.selection.node_id for v in self.offers()], ['right'])

    def test_failed_result_is_not_automatically_retried(self):
        self.accept('left', state='failed')
        self.assertEqual([v.selection.node_id for v in self.offers()], ['right'])

    def test_missing_or_foreign_execution_record_fails_closed(self):
        with self.assertRaises(canonical_scheduler_lane.DispatchFenceError):
            canonical_scheduler_lane.ready_offers('bob', JOB)
        self.record_path.unlink()
        with self.assertRaises(canonical_scheduler_lane.DispatchFenceError):
            self.offers()

    def test_node_from_old_plan_cannot_be_reoffered(self):
        offer = self.offers()[0]
        old = goal_state_store.load(self.path)
        updated = core_state_reducer.apply(old, {
            'op': 'set_goal_plan', 'reason_code': 'USER_REPLAN',
            'plan': {'plan_version': 2, 'nodes': self.nodes},
            'expected_version': old['version'],
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=old['version'], next_state=updated,
        )
        with self.assertRaises(canonical_scheduler_lane.DispatchFenceError):
            canonical_scheduler_lane.revalidate_offer(offer)

    def test_real_worker_dispatch_projects_two_roots_then_dependent_child(self):
        from types import SimpleNamespace

        # Make the child depend on BOTH roots, using the real Core plan CAS.
        state = goal_state_store.load(self.path)
        nodes = [node('left'), node('right'), node('child', ('left', 'right'))]
        changed = core_state_reducer.apply(state, {
            'op': 'set_goal_plan', 'reason_code': 'TEST_DAG',
            'expected_version': state['version'],
            'plan': {'plan_version': 2, 'nodes': nodes},
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=state['version'], next_state=changed,
        )
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['steps'][-1]['depends'] = ['left', 'right']
        release_guard.atomic(self.record_path, execution_record.encode(job))

        barrier = threading.Barrier(2, timeout=8)
        observed = []
        errors = []
        def safe_worker(owner, task, deps):
            self.assertEqual(owner, OWNER)
            self.assertEqual(task['agent'], 'research')
            if task['id'] in ('left', 'right'):
                barrier.wait()
            else:
                self.assertEqual(set(deps), {'left', 'right'})
            observed.append(task['id'])
            return task_results.seal('research', {
                'state': 'done', 'text': 'Verified ' + task['id'],
                'source': DATA['url'], 'source_chars': 200,
            })

        runtime = SimpleNamespace(slug=OWNER)
        # The first reservation modifies the journal digest, so re-select
        # second root from durable disk rather than replaying an old offer.
        def dispatch(offer):
            try:
                canonical_scheduler_dispatch.execute_offer(runtime, offer)
            except Exception as exc:
                errors.append(exc)

        with patch.object(task_agents, 'worker', side_effect=safe_worker), \
             patch.object(untrusted_flow, 'observe'):
            left = self.offers()[0]
            first = threading.Thread(target=dispatch, args=(left,))
            first.start()
            try:
                for _ in range(300):
                    recorded = execution_record.load(self.owner_root, OWNER, JOB)
                    if recorded['steps'][0]['state'] == 'running':
                        break
                    threading.Event().wait(.01)
                second = next(o for o in self.offers()
                              if o.selection.node_id == 'right')
                other = threading.Thread(target=dispatch, args=(second,))
                other.start()
                other.join(12)
                first.join(12)
                self.assertFalse(other.is_alive())
                self.assertFalse(first.is_alive())
                self.assertFalse(errors, repr(errors))
                self.assertIn('left', observed)
                self.assertIn('right', observed)
                children = self.offers()
                self.assertEqual([o.selection.node_id for o in children], ['child'])
                self.assertTrue(canonical_scheduler_dispatch.execute_offer(
                    runtime, children[0],
                ))
                saved = execution_record.load(self.owner_root, OWNER, JOB)
                self.assertEqual(set(saved['outputs']), {'left', 'right', 'child'})
                self.assertTrue(all(step['state'] == 'done' for step in saved['steps']))
            finally:
                barrier.abort()
                first.join(2)

    def test_foreign_profile_never_claims_node(self):
        from types import SimpleNamespace
        offer = self.offers()[0]
        before = self.record_path.read_bytes()
        with self.assertRaises(PermissionError):
            canonical_scheduler_dispatch.execute_offer(
                SimpleNamespace(slug='bob'), offer,
            )
        self.assertEqual(before, self.record_path.read_bytes())

    def test_discovery_requires_published_running_records(self):
        found = canonical_scheduler_dispatch.discover(OWNER)
        self.assertEqual([o.selection.node_id for o in found], ['left', 'right'])
        job = execution_record.load(self.owner_root, OWNER, JOB)
        job['state'] = 'cancelled'
        release_guard.atomic(self.record_path, execution_record.encode(job))
        self.assertEqual(canonical_scheduler_dispatch.discover(OWNER), ())


if __name__ == '__main__':
    unittest.main()
