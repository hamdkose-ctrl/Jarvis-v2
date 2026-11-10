"""BRAIN-06A canonical plan shape and reducer fence; no model or external effect."""
import copy
import unittest
from modules import core_state_reducer as reducer, goal_state


def node(identity, deps=()):
    return {
        'id': identity, 'depends_on': list(deps),
        'capability_id': 'research.read',
        'input': {'topic': identity}, 'expected_output': 'Source report',
        'acceptance': 'Verified source evidence',
    }


def plan(version=1, nodes=None):
    return {'plan_version': version, 'nodes': nodes or [node('a'), node('b', ('a',))]}


class CanonicalPlanFoundationTests(unittest.TestCase):
    def state(self, authority='canonical'):
        return goal_state.new(owner='alice', job_id='0123456789abcdef',
                              goal='Araştır ve raporla', authority=authority)

    def apply(self, state, proposal):
        return reducer.apply(state, {
            'expected_version': state['version'], 'op': 'set_goal_plan',
            'plan': proposal, 'reason_code': 'CORE_PLAN_ACCEPTED',
        })

    def test_plan_is_optional_for_existing_snapshots(self):
        self.assertNotIn('goal_plan', goal_state.validate(self.state()))

    def test_first_plan_and_revision_increment_both_versions(self):
        original = self.state()
        first = self.apply(original, plan())
        self.assertNotIn('goal_plan', original)
        self.assertEqual(first['version'], 1)
        self.assertEqual(first['goal_plan']['plan_version'], 1)
        revised = self.apply(first, plan(2, [node('a'), node('c', ('a',))]))
        self.assertEqual(revised['version'], 2)
        self.assertEqual(revised['goal_plan']['plan_version'], 2)
        self.assertEqual(revised['audit'][-1]['op'], 'set_goal_plan')
        with self.assertRaises(reducer.StaleStateError):
            self.apply(revised, plan(2))

    def test_rejects_legacy_and_terminal_without_modification(self):
        old = self.state('legacy')
        with self.assertRaises(reducer.InvalidTransitionError):
            self.apply(old, plan())
        terminal = reducer.apply(self.state(), {
            'expected_version': 0, 'op': 'set_state', 'state': 'done',
            'reason_code': 'FINISHED',
        })
        with self.assertRaises(reducer.TerminalStateError):
            self.apply(terminal, plan())
        self.assertNotIn('goal_plan', old)

    def test_rejects_cycles_forward_dependencies_and_invalid_fields(self):
        bad = [
            plan(1, [node('a', ('b',)), node('b')]),
            plan(1, [node('a', ('a',))]),
            plan(1, [node('a'), node('a')]),
            plan(1, [node('a', ('missing',))]),
            plan(1, [node('a', ('a', 'a'))]),
            plan(1, [dict(node('a'), input={'bad': float('nan')})]),
            plan(1, [dict(node('a'), acceptance='')]),
            plan(1, [node(str(i)) for i in range(9)]),
        ]
        state = self.state()
        frozen = copy.deepcopy(state)
        for item in bad:
            with self.subTest(item=item), self.assertRaises(ValueError):
                self.apply(state, item)
        self.assertEqual(state, frozen)

    def test_rejects_stale_canonical_version_and_invalid_plan_number(self):
        state = self.apply(self.state(), plan())
        with self.assertRaises(reducer.StaleStateError):
            reducer.apply(state, {
                'expected_version': 0, 'op': 'set_goal_plan',
                'plan': plan(2), 'reason_code': 'STALE',
            })
        for version in (0, 3, True):
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.apply(state, plan(version))


if __name__ == '__main__':
    unittest.main()
