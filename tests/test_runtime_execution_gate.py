import unittest


class RuntimeExecutionGateTests(unittest.TestCase):
    def setUp(self):
        from modules import capability_decision, capability_manifest, runtime_execution_gate
        self.decision = capability_decision
        self.manifest = capability_manifest
        self.gate = runtime_execution_gate

    def test_verified_approval_satisfies_ask_required_without_bypassing_deny(self):
        row = self.manifest.from_task_tool('publish')
        result = self.decision.decide(
            row,
            domain_invariant='pass',
            domain_authority='execute',
            user_authority='execute',
            job_authority='execute',
            action={'class': 'publish', 'target': 'friend@example.com', 'via': 'outbox'},
            effect_state='ready',
            approval_verified=True,
        )
        self.assertTrue(result['worker_allowed'])
        self.assertEqual(result['authority'], 'execute')
        self.assertEqual(result['permission']['decision'], 'allow')

        denied = self.manifest.from_tool_contract({
            'id': 'money', 'version': 1,
            'actions': [{'id': 'pay', 'class': 'money_credential'}],
        })
        result = self.decision.decide(
            denied,
            domain_invariant='pass',
            domain_authority='execute',
            user_authority='execute',
            job_authority='execute',
            action={'class': 'money_credential', 'target': 'x', 'via': 'browser'},
            effect_state='ready',
            approval_verified=True,
        )
        self.assertFalse(result['worker_allowed'])
        self.assertEqual(result['permission']['decision'], 'deny')

    def test_ask_required_without_approval_is_prepare_only(self):
        plan = self.gate.plan_task(
            'publish',
            {'service': 'gmail', 'destination': 'friend@example.com', 'text': 'merhaba'},
            approval_verified=False,
        )
        self.assertEqual(plan['phase'], 'prepare')
        self.assertFalse(plan['worker_allowed'])
        self.assertEqual(plan['reason_code'], 'DECISION_AUTHORITY_RESTRICTED')

    def test_prepare_phase_accepts_only_explicit_approval_result(self):
        plan = self.gate.plan_task(
            'publish',
            {'service': 'gmail', 'destination': 'friend@example.com', 'text': 'merhaba'},
            approval_verified=False,
        )
        self.assertEqual(self.gate.accept_prepare_result(plan, {'state': 'approval', 'id': 'o1'})['state'], 'approval')
        with self.assertRaises(PermissionError):
            self.gate.accept_prepare_result(plan, {'state': 'done', 'text': 'sent'})

    def test_read_task_reaches_execution_without_approval(self):
        plan = self.gate.plan_task(
            'research',
            {'url': 'https://example.test', 'question': 'x'},
            approval_verified=False,
        )
        self.assertEqual(plan['phase'], 'execute')
        self.assertTrue(plan['worker_allowed'])


if __name__ == '__main__':
    unittest.main()
