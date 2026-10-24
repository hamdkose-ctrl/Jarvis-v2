import unittest


class EffectJournalTests(unittest.TestCase):
    def setUp(self):
        from modules import effect_journal
        self.journal = effect_journal

    def intent(self):
        return {
            'schema': 'effect_intent.v1', 'effect_id': 'effect-1', 'owner': 'alice',
            'job_id': 'job-1', 'command_id': 'cmd-1', 'capability_id': 'mail.send',
            'capability_version': '1', 'input_digest': 'a' * 64,
        }

    def receipt(self):
        return {
            'schema': 'effect_receipt.v1', 'effect_id': 'effect-1',
            'provider_receipt_ref': 'provider-1', 'verified': True,
        }

    def test_intent_then_verified_receipt_is_append_only(self):
        journal = self.journal.Journal()
        journal.record_intent(self.intent())
        journal.record_receipt(self.receipt())
        self.assertEqual(journal.status('effect-1'), 'succeeded')

    def test_receipt_without_durable_intent_is_contract_violation(self):
        with self.assertRaises(self.journal.ContractViolation):
            self.journal.Journal().record_receipt(self.receipt())

    def test_duplicate_or_unverified_receipts_fail_closed(self):
        journal = self.journal.Journal(); journal.record_intent(self.intent())
        with self.assertRaises(ValueError):
            journal.record_receipt({**self.receipt(), 'verified': False})
        journal.record_receipt(self.receipt())
        with self.assertRaises(ValueError):
            journal.record_receipt(self.receipt())

    def test_manifest_marks_only_conditional_reconcilable_task_capabilities(self):
        from modules import effect_recovery_runtime
        self.assertTrue(effect_recovery_runtime.required('publish'))
        self.assertTrue(effect_recovery_runtime.required('browser'))
        self.assertTrue(effect_recovery_runtime.required('coder'))
        self.assertFalse(effect_recovery_runtime.required('writer'))
