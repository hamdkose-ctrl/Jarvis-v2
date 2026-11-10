"""BRAIN-06B structural DAG gate tests: no worker, model, lease or effect."""
from dataclasses import replace
import copy
import unittest

from modules import core_state_reducer, goal_plan_gate, goal_state


def node(identity, deps=(), *, capability='research.read', argument=None,
         output='source report', acceptance='verified sources'):
    return {
        'id': identity, 'depends_on': list(deps),
        'capability_id': capability,
        'input': {'topic': identity if argument is None else argument},
        'expected_output': output, 'acceptance': acceptance,
    }


def graph(version=1, nodes=None):
    return {'plan_version': version, 'nodes': nodes or [
        node('research'), node('mail'),
        node('summary', ('research',)),
        node('delivery', ('summary',)),
    ]}


def state(authority='canonical'):
    return goal_state.new(owner='alice', job_id='job-001',
                          goal='Araştır ve özetle', authority=authority)


def planned(source=None, plan=None):
    source = state() if source is None else source
    proposed = graph() if plan is None else plan
    return core_state_reducer.apply(source, {
        'op': 'set_goal_plan', 'expected_version': source['version'],
        'plan': proposed, 'reason_code': 'TEST_CANONICAL_PLAN',
    })


class GoalPlanGateTests(unittest.TestCase):
    def test_root_nodes_are_only_preparation_candidates(self):
        snapshot = planned()
        frozen = copy.deepcopy(snapshot)
        items = goal_plan_gate.initial_roots(snapshot, owner='alice', job_id='job-001')
        self.assertEqual([item.node_id for item in items], ['research', 'mail'])
        self.assertEqual([item.plan_version for item in items], [1, 1])
        self.assertEqual([item.expected_goal_version for item in items], [1, 1])
        self.assertEqual(snapshot, frozen)
        self.assertEqual(goal_plan_gate.revalidate(snapshot, items[0])['capability_id'], 'research.read')

    def test_wrong_owner_job_missing_node_and_invalid_candidate_fail_closed(self):
        snapshot = planned()
        for owner, job in [('mallory', 'job-001'), ('alice', 'other')]:
            with self.subTest(owner=owner, job=job), self.assertRaises(goal_plan_gate.PlanFenceError):
                goal_plan_gate.candidate(snapshot, owner=owner, job_id=job, node_id='research')
            with self.assertRaises(goal_plan_gate.PlanFenceError):
                goal_plan_gate.initial_roots(snapshot, owner=owner, job_id=job)
        with self.assertRaises(goal_plan_gate.PlanFenceError):
            goal_plan_gate.candidate(snapshot, owner='alice', job_id='job-001', node_id='unknown')
        with self.assertRaises(goal_plan_gate.PlanFenceError):
            goal_plan_gate.revalidate(snapshot, {'node_id': 'research'})

    def test_stale_goalstate_version_rejected_without_dispatch(self):
        snapshot = planned()
        item = goal_plan_gate.candidate(snapshot, owner='alice', job_id='job-001', node_id='research')
        updated = core_state_reducer.apply(snapshot, {
            'expected_version': snapshot['version'], 'op': 'append_evidence',
            'reason_code': 'NEW_EVIDENCE', 'evidence': {'source': 'worker'},
        })
        with self.assertRaisesRegex(goal_plan_gate.PlanFenceError, 'stale'):
            goal_plan_gate.revalidate(updated, item)

    def test_plan_revision_invalidates_old_node_candidate(self):
        snapshot = planned()
        item = goal_plan_gate.candidate(snapshot, owner='alice', job_id='job-001', node_id='mail')
        revised = planned(snapshot, graph(2))
        with self.assertRaises(goal_plan_gate.PlanFenceError):
            goal_plan_gate.revalidate(revised, item)
        self.assertEqual(revised['goal_plan']['plan_version'], 2)

    def test_no_legacy_terminal_paused_or_unplanned_execution_candidates(self):
        for item in [state('legacy'), state('canonical')]:
            with self.assertRaises(goal_plan_gate.PlanFenceError):
                goal_plan_gate.initial_roots(item, owner='alice', job_id='job-001')
        snapshot = planned()
        for target in ['paused', 'waiting', 'failed', 'cancelled', 'done']:
            with self.subTest(target=target):
                changed = core_state_reducer.apply(snapshot, {
                    'expected_version': snapshot['version'], 'op': 'set_state',
                    'state': target, 'reason_code': 'TEST_STOP',
                })
                with self.assertRaises(goal_plan_gate.PlanFenceError):
                    goal_plan_gate.initial_roots(changed, owner='alice', job_id='job-001')

    def test_reusable_structure_follows_transitive_dependencies(self):
        original = planned()
        new = graph(2, [
            node('research', argument='different topic'),
            node('mail'),
            node('summary', ('research',)),
            node('delivery', ('summary',)),
        ])
        self.assertEqual(goal_plan_gate.revision_reuse_candidates(original, new), ('mail',))
        self.assertEqual(original['goal_plan']['nodes'][0]['input']['topic'], 'research')

    def test_identical_nodes_are_only_reuse_candidates_not_completed(self):
        original = planned()
        # Returning structural candidates makes no claim that any node ran.
        self.assertEqual(goal_plan_gate.revision_reuse_candidates(original, graph(2)),
                         ('research', 'mail', 'summary', 'delivery'))

    def test_changed_acceptance_or_dependency_invalidates_downstream(self):
        original = planned()
        revised = graph(2, [
            node('research', acceptance='stronger source proof'),
            node('mail'),
            node('summary', ('research',)),
            node('delivery', ('summary',)),
        ])
        self.assertEqual(goal_plan_gate.revision_reuse_candidates(original, revised), ('mail',))
        dep_change = graph(2, [
            node('research'), node('mail'),
            node('summary', ('research', 'mail')),
            node('delivery', ('summary',)),
        ])
        self.assertEqual(goal_plan_gate.revision_reuse_candidates(original, dep_change),
                         ('research', 'mail'))

    def test_version_schema_and_tampering_fail_closed(self):
        original = planned()
        for version in (0, 1, 3):
            with self.subTest(version=version), self.assertRaises((goal_plan_gate.PlanFenceError, ValueError)):
                goal_plan_gate.revision_reuse_candidates(original, graph(version))
        invalid = graph(2, [node('a', ('b',)), node('b')])
        with self.assertRaises(ValueError):
            goal_plan_gate.revision_reuse_candidates(original, invalid)
        candidate = goal_plan_gate.candidate(original, owner='alice', job_id='job-001', node_id='research')
        for modified in [replace(candidate, node_digest='0'*64),
                         replace(candidate, capability_id='danger.write'),
                         replace(candidate, plan_version=42),
                         replace(candidate, owner='mallory')]:
            with self.assertRaises(goal_plan_gate.PlanFenceError):
                goal_plan_gate.revalidate(original, modified)


if __name__ == '__main__':
    unittest.main()
