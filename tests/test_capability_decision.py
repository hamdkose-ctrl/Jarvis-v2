import copy
import unittest


class CapabilityDecisionTests(unittest.TestCase):
    def setUp(self):
        from modules import capability_decision, capability_manifest
        self.decision = capability_decision
        self.manifest = capability_manifest

    def test_read_capability_reaches_worker_only_when_all_stages_allow(self):
        row = self.manifest.from_task_tool('research')
        result = self.decision.decide(
            row,
            domain_invariant='pass',
            domain_authority='execute',
            user_authority='execute',
            job_authority='execute',
            action={'class': 'read', 'target': 'https://example.test', 'via': 'browser'},
            effect_state='ready',
        )
        self.assertTrue(result['worker_allowed'])
        self.assertEqual(result['authority'], 'execute')
        self.assertEqual(result['permission']['decision'], 'allow')
        self.assertEqual(result['effect'], 'ready')

    def test_manifest_authority_cannot_be_raised_by_other_inputs(self):
        row = self.manifest.from_task_tool('publish')
        result = self.decision.decide(
            row,
            domain_invariant='pass',
            domain_authority='execute',
            user_authority='execute',
            job_authority='execute',
            action={'class': 'publish', 'target': 'post:42', 'via': 'browser'},
            effect_state='ready',
        )
        self.assertFalse(result['worker_allowed'])
        self.assertEqual(result['authority'], 'ask_required')
        self.assertEqual(result['permission']['decision'], 'ask')

    def test_more_restrictive_authority_wins(self):
        row = self.manifest.from_task_tool('research')
        result = self.decision.decide(
            row,
            domain_invariant='pass',
            domain_authority='suggest_only',
            user_authority='execute',
            job_authority='execute',
            action={'class': 'read', 'target': 'https://example.test', 'via': 'browser'},
            effect_state='ready',
        )
        self.assertFalse(result['worker_allowed'])
        self.assertEqual(result['authority'], 'suggest_only')

    def test_domain_invariant_failure_blocks_before_worker(self):
        row = self.manifest.from_task_tool('research')
        result = self.decision.decide(
            row,
            domain_invariant='block',
            domain_authority='execute',
            user_authority='execute',
            job_authority='execute',
            action={'class': 'read', 'target': 'https://example.test', 'via': 'browser'},
            effect_state='ready',
        )
        self.assertFalse(result['worker_allowed'])
        self.assertEqual(result['authority'], 'forbidden')
        self.assertEqual(result['reason_code'], 'DOMAIN_INVARIANT_BLOCKED')

    def test_permission_class_mismatch_fails_closed(self):
        row = self.manifest.from_task_tool('research')
        result = self.decision.decide(
            row,
            domain_invariant='pass',
            domain_authority='execute',
            user_authority='execute',
            job_authority='execute',
            action={'class': 'local_reversible', 'target': 'demo.txt', 'via': 'file'},
            effect_state='ready',
        )
        self.assertFalse(result['worker_allowed'])
        self.assertEqual(result['permission']['decision'], 'deny')
        self.assertEqual(result['reason_code'], 'PERMISSION_CLASS_MISMATCH')

    def test_effect_reconcile_or_blocked_never_reaches_worker(self):
        row = self.manifest.from_task_tool('research')
        for effect_state in ('reconcile', 'blocked'):
            with self.subTest(effect_state=effect_state):
                result = self.decision.decide(
                    row,
                    domain_invariant='pass',
                    domain_authority='execute',
                    user_authority='execute',
                    job_authority='execute',
                    action={'class': 'read', 'target': 'https://example.test', 'via': 'browser'},
                    effect_state=effect_state,
                )
                self.assertFalse(result['worker_allowed'])
                self.assertEqual(result['effect'], effect_state)

    def test_manifest_accepts_full_authority_vocabulary(self):
        row = self.manifest.from_task_tool('research')
        for authority in ('execute', 'ask_required', 'suggest_only', 'forbidden'):
            with self.subTest(authority=authority):
                candidate = copy.deepcopy(row)
                candidate['decision_authority'] = authority
                accepted = self.manifest.validate_catalog([candidate])
                self.assertEqual(accepted[0]['decision_authority'], authority)


if __name__ == '__main__':
    unittest.main()
