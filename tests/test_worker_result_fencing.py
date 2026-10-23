import hashlib
import unittest


class WorkerResultFencingTests(unittest.TestCase):
    def setUp(self):
        from modules import worker_result
        self.contract = worker_result

    def expected(self):
        return {
            'owner': 'alice', 'job_id': 'job-1', 'step_id': 'step-1',
            'command_id': 'cmd-1', 'attempt': 2, 'expected_job_version': 7,
            'capability_id': 'research', 'capability_version': '1',
            'input_digest': hashlib.sha256(b'input').hexdigest(),
        }

    def result(self):
        row = self.expected()
        row.update({'schema': 'worker_result.v1', 'status': 'succeeded', 'evidence': []})
        return row

    def test_matching_result_is_accepted_without_state_mutation(self):
        result = self.result()
        self.assertEqual(self.contract.accept(result, self.expected())['status'], 'succeeded')

    def test_stale_or_foreign_fence_is_rejected_fail_closed(self):
        for key, value in [('attempt', 1), ('expected_job_version', 6), ('owner', 'mallory'), ('input_digest', 'bad')]:
            with self.subTest(key=key):
                result = self.result(); result[key] = value
                with self.assertRaises(self.contract.FenceError):
                    self.contract.accept(result, self.expected())

    def test_unknown_fields_and_non_json_evidence_are_rejected(self):
        result = self.result(); result['thought'] = 'hidden'
        with self.assertRaises(ValueError):
            self.contract.accept(result, self.expected())
        result = self.result(); result['evidence'] = [object()]
        with self.assertRaises(ValueError):
            self.contract.accept(result, self.expected())
