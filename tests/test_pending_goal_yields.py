"""Explicit model relation plus an actual persisted pending goal; no live model.

An unrelated typed request must not answer a question. Only a model-selected,
Core-offered goal with ANSWER_TO_PENDING receives the original user answer.
"""
from dataclasses import replace
from unittest.mock import patch
import unittest

from modules import brain_entry, goal_executor
from modules.brain_contracts import ConversationRelation, GoalOperation, RequestKind
from test_brain_pr3_raw_text_authority import _CanonicalAuthorityHarness
from test_brain_b5_goal_resolver import job_row


class PendingGoalTests(_CanonicalAuthorityHarness):
    def _ask(self, text, *, answer=False):
        job = job_row('haber raporu', self.owner, state='question')
        job['question'] = 'Hangi tarih ve kaynaklar?'
        goal_executor._save(job, move_pointer=True)
        def model(current, utterance, *, active_context=None):
            self.assertIn(job['id'], [ref.id for ref in active_context.goal_candidates])
            return replace(current,
                request_kind=RequestKind.GOAL_CONTROL if answer else RequestKind.CHAT,
                goal_operation=GoalOperation.CONTINUE if answer else None,
                goal_target_ids=(job['id'],) if answer else (),
                conversation_relation=ConversationRelation.ANSWER_TO_PENDING if answer else ConversationRelation.NEW_REQUEST)
        with patch.object(brain_entry, 'apply_model_understanding', side_effect=model):
            self.turn_real(text, model_understanding=True)
        return job

    def test_new_plan_and_mail_commands_are_not_answers_to_the_pending_question(self):
        for text in ('bugünün planı', 'günümü planla', 'önemli maillerim', 'cevap vermediğim mailler'):
            with self.subTest(text=text):
                self._ask(text)
                self.run_goal.assert_not_called()

    def test_real_answers_still_reach_the_pending_goal(self):
        for text in ('son 7 gün', 'evet resmi kaynaklardan', 'Ankara'):
            with self.subTest(text=text):
                self.run_goal.reset_mock()
                job = self._ask(text, answer=True)
                self.assertEqual(self.run_goal.call_args.args[1], text)
                self.assertEqual(self.run_goal.call_args.kwargs['job_id'], job['id'])
                self.assertEqual(self.run_goal.call_args.kwargs['expected_control'], goal_executor.control_key(job))


if __name__ == '__main__':
    unittest.main()
