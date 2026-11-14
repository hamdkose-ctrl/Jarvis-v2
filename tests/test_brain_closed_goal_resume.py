"""Terminal resume is a bounded read, never permission to run a changed goal."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from modules import brain_gates, goal_executor
from test_brain_gates import OWNER, RID, ctx, ref


class ClosedGoalResumeTests(unittest.TestCase):
    def gate(self, *, state='done', context=None, extra=(), text='devam'):
        terminal = ref('a' * 16, kind='goal', source='goal_state', state=state)
        return brain_gates.exact_state_gate(
            owner=OWNER, request_id=RID, text=text, active_context=context or ctx(),
            state_references=(terminal,) + tuple(extra))

    def test_terminal_goal_is_a_bounded_read_with_observed_identity(self):
        for state in ('done', 'cancelled'):
            result = self.gate(state=state)
            self.assertTrue(result.matched)
            self.assertEqual(result.protocol, 'goal.closed_resume')
            self.assertEqual(result.selection, 'a' * 16)
        self.assertFalse(self.gate(text='devam edince ne olur?').matched)

    def test_terminal_goal_does_not_steal_pending_or_other_open_goal(self):
        for context in (
            ctx(pending=(ref('pending_msg', value={'stage': 'text'}),)),
            replace(ctx(), goal_candidates=(ref('other', kind='goal', source='goal_state', state='paused'),)),
        ):
            self.assertFalse(self.gate(context=context).matched)
        for other in (
            ref('native', source='desktop_agent', status='question'),
            ref('job', kind='task_job', source='task_agents', state='running'),
            ref('open', kind='goal', source='goal_state', state='paused'),
        ):
            self.assertNotEqual(self.gate(extra=(other,)).protocol, 'goal.closed_resume')

    def test_foreign_terminal_reference_is_rejected(self):
        with self.assertRaises(ValueError):
            self.gate(extra=(ref('foreign', kind='goal', source='goal_state', owner='other', state='done'),))

    def test_terminal_read_never_runs_or_saves_changed_target(self):
        original = {'owner': OWNER, 'id': 'a' * 16, 'state': 'done'}
        for job in (None, original, {**original, 'state': 'running'},
                    {**original, 'owner': 'other'}, {**original, 'id': 'b' * 16}):
            with self.subTest(job=job), patch.object(goal_executor, 'latest', return_value=job), \
                    patch.object(goal_executor, 'run') as run, patch.object(goal_executor, '_save') as save:
                reply = goal_executor.closed_resume_status(OWNER, original['id'])
                self.assertIn('tamamlandı' if job == original else 'hiçbir hedef sürdürülmedi', reply)
                run.assert_not_called()
                save.assert_not_called()


if __name__ == '__main__':
    unittest.main()
