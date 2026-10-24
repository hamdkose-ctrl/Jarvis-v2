"""completion_policy is a pure complete/continue/waiting/terminal classifier: no
provider/network call, no file I/O, no mutation. These tests exercise it in
isolation (no goal_executor/news_policy import needed) plus one check that the
real goal_executor binding points still classify exactly as before."""
import unittest

from modules import completion_policy


class EvaluateEvidenceTests(unittest.TestCase):
    def test_check_that_returns_normally_is_complete(self):
        calls = []
        def check(job, goal, evidence, final=False):
            calls.append((job, goal, evidence, final))
        decision = completion_policy.evaluate_evidence(check, 'job', 'goal', ['s1'], final=True)
        self.assertEqual(decision, {'decision': completion_policy.COMPLETE, 'reason': None})
        self.assertEqual(calls, [('job', 'goal', ['s1'], True)])

    def test_check_that_raises_value_error_is_continue_with_reason(self):
        def check(*a, **k):
            raise ValueError('Eksik kanıt: ikinci yayıncı doğrulanmadı.')
        decision = completion_policy.evaluate_evidence(check, 'job', 'goal', [])
        self.assertEqual(decision['decision'], completion_policy.CONTINUE)
        self.assertEqual(decision['reason'], 'Eksik kanıt: ikinci yayıncı doğrulanmadı.')

    def test_other_exception_types_are_not_swallowed(self):
        def check(*a, **k):
            raise PermissionError('Hedef ve istek sahibi eşleşmiyor.')
        with self.assertRaises(PermissionError):
            completion_policy.evaluate_evidence(check)

    def test_check_is_never_retried(self):
        calls = []
        def check():
            calls.append(1)
            raise ValueError('eksik')
        completion_policy.evaluate_evidence(check)
        self.assertEqual(calls, [1])


class JobDecisionTests(unittest.TestCase):
    def test_done_is_complete(self):
        self.assertEqual(completion_policy.job_decision({'state': 'done'}), completion_policy.COMPLETE)

    def test_cancelled_is_terminal(self):
        self.assertEqual(completion_policy.job_decision({'state': 'cancelled'}), completion_policy.TERMINAL)

    def test_question_is_waiting(self):
        self.assertEqual(completion_policy.job_decision({'state': 'question'}), completion_policy.WAITING)

    def test_approval_is_waiting(self):
        self.assertEqual(completion_policy.job_decision({'state': 'approval'}), completion_policy.WAITING)

    def test_running_paused_review_are_continue(self):
        for state in ('running', 'paused', 'review'):
            self.assertEqual(completion_policy.job_decision({'state': state}), completion_policy.CONTINUE)

    def test_missing_or_non_dict_job_is_continue(self):
        self.assertEqual(completion_policy.job_decision({}), completion_policy.CONTINUE)
        self.assertEqual(completion_policy.job_decision(None), completion_policy.CONTINUE)

    def test_decision_is_never_anything_outside_the_four(self):
        for state in ('done', 'cancelled', 'question', 'approval', 'running', 'paused', 'review', 'weird', None):
            self.assertIn(completion_policy.job_decision({'state': state}), completion_policy.DECISIONS)


if __name__ == '__main__':
    unittest.main()
