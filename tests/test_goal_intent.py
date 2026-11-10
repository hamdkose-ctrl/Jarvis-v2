import json
import tempfile
import unittest
from pathlib import Path

from modules import core_state_reducer, goal_state, goal_state_compat, goal_state_store


class GoalIntentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'goal.json'
        self.state = goal_state.new(owner='alice', job_id='abc', goal='original', authority='canonical')
        goal_state_store.create(self.path, self.state)

    def apply(self, version, operation, **kwargs):
        return goal_state_compat.apply_goal_intent(
            self.path, owner='alice', job_id='abc', expected_version=version,
            operation=operation, **kwargs)

    def test_persisted_mutations_preserve_prior_intent_and_advance_same_state(self):
        first = self.apply(0, 'add_task', text=' added ')
        second = self.apply(1, 'revise', text='changed')
        third = self.apply(2, 'prioritize', priority=4)
        self.assertEqual(third['goal_intent'], {'revision': 'changed', 'additions': ['added'], 'priority': 4})
        self.assertEqual(third['goal'], 'original')
        self.assertEqual(third['state'], first['state'])
        self.assertEqual(third['version'], 3)
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), third)
        self.assertEqual(second['audit'][-1]['op'], 'mutate_goal_intent')
        fourth = self.apply(3, 'prioritize', priority=4)
        self.assertEqual(fourth['version'], 4)

    def test_missing_and_empty_are_distinct_and_old_snapshot_reads(self):
        self.assertNotIn('goal_intent', goal_state_store.load(self.path))
        state = self.apply(0, 'prioritize', priority=0)
        self.assertEqual(state['goal_intent'], {'revision': None, 'additions': [], 'priority': 0})

    def test_stale_identity_and_invalid_inputs_leave_bytes_unchanged(self):
        before = self.path.read_bytes()
        cases = [
            {'owner': 'bob', 'job_id': 'abc', 'expected_version': 0, 'operation': 'revise', 'text': 'x'},
            {'owner': 'alice', 'job_id': 'wrong', 'expected_version': 0, 'operation': 'revise', 'text': 'x'},
            {'owner': 'alice', 'job_id': 'abc', 'expected_version': 1, 'operation': 'revise', 'text': 'x'},
            {'owner': 'alice', 'job_id': 'abc', 'expected_version': 0, 'operation': 'add_task', 'text': ' '},
            {'owner': 'alice', 'job_id': 'abc', 'expected_version': 0, 'operation': 'prioritize', 'priority': True},
            {'owner': 'alice', 'job_id': 'abc', 'expected_version': 0, 'operation': 'bad'},
        ]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(ValueError):
                goal_state_compat.apply_goal_intent(self.path, **args)
            self.assertEqual(self.path.read_bytes(), before)

    def test_legacy_missing_and_terminal_do_not_promote(self):
        legacy = goal_state.new(owner='alice', job_id='old', goal='old')
        legacy_path = self.path.with_name('old.json')
        goal_state_store.create(legacy_path, legacy)
        with self.assertRaises(ValueError):
            goal_state_compat.apply_goal_intent(legacy_path, owner='alice', job_id='old', expected_version=0, operation='revise', text='x')
        self.assertEqual(goal_state_store.load(legacy_path), legacy)
        with self.assertRaises(FileNotFoundError):
            goal_state_compat.apply_goal_intent(self.path.with_name('missing'), owner='alice', job_id='abc', expected_version=0, operation='revise', text='x')
        done = core_state_reducer.apply(self.state, {'expected_version': 0, 'op': 'set_state', 'state': 'done', 'reason_code': 'DONE'})
        goal_state_store.compare_and_swap(self.path, expected_version=0, next_state=done)
        with self.assertRaises(core_state_reducer.TerminalStateError):
            self.apply(1, 'revise', text='x')
        self.assertEqual(goal_state_store.load(self.path), done)

    def test_invalid_intent_shape_rejected(self):
        for value in ({}, {'revision': None, 'additions': [], 'priority': True},
                      {'revision': None, 'additions': [''], 'priority': 0}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                goal_state.validate({**self.state, 'goal_intent': value})


if __name__ == '__main__':
    unittest.main()
