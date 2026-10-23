import copy
import unittest


class CoreStateReducerTests(unittest.TestCase):
    def setUp(self):
        from modules import core_state_reducer, goal_state
        self.reducer = core_state_reducer
        self.goal_state = goal_state

    def state(self):
        return self.goal_state.new(
            owner='alice', job_id='0123456789abcdef', goal='Raporu hazırla',
            execution_mode='agent',
        )

    def test_new_goal_state_is_versioned_json_only_snapshot(self):
        state = self.state()
        self.assertEqual(state['schema'], 'goal_state.v1')
        self.assertEqual(state['owner'], 'alice')
        self.assertEqual(state['job_id'], '0123456789abcdef')
        self.assertEqual(state['version'], 0)
        self.assertEqual(state['state'], 'pending')
        self.assertEqual(state['evidence'], [])
        self.assertEqual(state['audit'][0]['reason_code'], 'CREATED')

    def test_reducer_is_pure_cas_and_increments_exactly_one_version(self):
        before = self.state()
        frozen = copy.deepcopy(before)
        after = self.reducer.apply(before, {
            'expected_version': 0,
            'op': 'set_state',
            'state': 'running',
            'reason_code': 'WORK_STARTED',
        })
        self.assertEqual(before, frozen)
        self.assertIsNot(after, before)
        self.assertEqual(after['version'], 1)
        self.assertEqual(after['state'], 'running')
        self.assertEqual(after['audit'][-1]['version'], 1)
        self.assertEqual(after['audit'][-1]['reason_code'], 'WORK_STARTED')

    def test_stale_expected_version_fails_without_mutating_state(self):
        before = self.state()
        frozen = copy.deepcopy(before)
        with self.assertRaises(self.reducer.StaleStateError):
            self.reducer.apply(before, {
                'expected_version': 7,
                'op': 'set_state',
                'state': 'running',
                'reason_code': 'STALE',
            })
        self.assertEqual(before, frozen)

    def test_done_and_cancelled_are_terminal(self):
        for terminal in ('done', 'cancelled'):
            with self.subTest(terminal=terminal):
                state = self.reducer.apply(self.state(), {
                    'expected_version': 0,
                    'op': 'set_state',
                    'state': terminal,
                    'reason_code': 'TERMINAL',
                })
                with self.assertRaises(self.reducer.TerminalStateError):
                    self.reducer.apply(state, {
                        'expected_version': 1,
                        'op': 'set_state',
                        'state': 'running',
                        'reason_code': 'REOPEN',
                    })

    def test_invalid_transition_and_unknown_operation_fail_closed(self):
        state = self.state()
        with self.assertRaises(self.reducer.InvalidTransitionError):
            self.reducer.apply(state, {
                'expected_version': 0,
                'op': 'set_state',
                'state': 'done',
                'reason_code': '',
            })
        with self.assertRaises(ValueError):
            self.reducer.apply(state, {
                'expected_version': 0,
                'op': 'invented',
                'reason_code': 'UNKNOWN',
            })

    def test_evidence_and_blocker_are_changed_only_by_explicit_reducer_ops(self):
        state = self.reducer.apply(self.state(), {
            'expected_version': 0,
            'op': 'append_evidence',
            'evidence': {'kind': 'receipt', 'ref': 's1'},
            'reason_code': 'EVIDENCE_VERIFIED',
        })
        self.assertEqual(state['evidence'], [{'kind': 'receipt', 'ref': 's1'}])
        state = self.reducer.apply(state, {
            'expected_version': 1,
            'op': 'set_blocker',
            'blocker': {'code': 'PERMISSION_REQUIRED'},
            'reason_code': 'WAIT_PERMISSION',
        })
        self.assertEqual(state['blocker'], {'code': 'PERMISSION_REQUIRED'})
        state = self.reducer.apply(state, {
            'expected_version': 2,
            'op': 'clear_blocker',
            'reason_code': 'PERMISSION_RESOLVED',
        })
        self.assertIsNone(state['blocker'])
        self.assertEqual(state['version'], 3)

    def test_identity_and_goal_are_not_patchable_through_reducer(self):
        state = self.state()
        with self.assertRaises(ValueError):
            self.reducer.apply(state, {
                'expected_version': 0,
                'op': 'patch',
                'owner': 'mallory',
                'reason_code': 'NOPE',
            })


if __name__ == '__main__':
    unittest.main()
