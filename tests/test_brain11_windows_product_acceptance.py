"""BRAIN-11 operator acceptance gates: never make a CI/mock-only success."""
import unittest
from scripts import brain11_windows_product_acceptance as b11


class Brain11AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.sha = "a" * 40
        self.records = [
            dict(id=identifier, status="passed", operator_observed=True,
                 real_jarvis=True, critical_wrong_effect=False)
            for identifier, _instruction, _expected in b11.SCENARIOS
        ]
        self.holdout = dict(
            state="passed", scope="holdout", head=self.sha,
            semantic_acceptance=True, cases=20, model_responses=20,
            accuracy=.95, incorrect_action_proposals=0, attempted_effects=0,
            corpus_sha256="f" * 64,
        )

    def test_twenty_distinct_multi_domain_operator_cases(self):
        self.assertEqual(len(b11.SCENARIOS), 20)
        self.assertEqual(len(set(x[0] for x in b11.SCENARIOS)), 20)
        self.assertTrue({"cancel_long_running", "restart_recovery", "approval_stale",
                         "owner_privacy", "voice_interrupt", "persona_and_final"} <=
                        {x[0] for x in b11.SCENARIOS})

    def test_pass_is_only_a_candidate_for_independent_acceptance(self):
        self.assertTrue(b11.verify_holdout(self.holdout, self.sha))
        self.assertEqual(b11.assess(self.records, True), "candidate")
        self.assertEqual(b11.assess(self.records, False), "unmeasured")

    def test_missing_duplicate_or_mocked_workflow_rejected(self):
        self.assertEqual(b11.assess(self.records[:-1], True), "unmeasured")
        self.assertEqual(b11.assess(self.records[:-1] + self.records[:1], True), "unmeasured")
        self.records[0]["real_jarvis"] = False
        self.assertEqual(b11.assess(self.records, True), "failed")

    def test_one_wrong_effect_fails_even_if_every_other_check_passes(self):
        self.records[12]["critical_wrong_effect"] = True
        self.assertEqual(b11.assess(self.records, True), "failed")

    def test_operator_skip_cannot_be_counted_as_pass(self):
        self.records[1]["status"] = "unmeasured"
        self.assertEqual(b11.assess(self.records, True), "unmeasured")

    def test_stale_or_synthetic_holdout_never_qualifies(self):
        self.assertFalse(b11.verify_holdout(dict(self.holdout, head="b"*40), self.sha))
        self.assertFalse(b11.verify_holdout(dict(self.holdout, scope="connection"), self.sha))
        self.assertFalse(b11.verify_holdout(dict(self.holdout, state="unmeasured"), self.sha))
        self.assertFalse(b11.verify_holdout(dict(self.holdout, model_responses=19), self.sha))
        self.assertFalse(b11.verify_holdout(dict(self.holdout, cases=True), self.sha))
        self.assertFalse(b11.verify_holdout(dict(self.holdout, corpus_sha256=""), self.sha))

    def test_semantic_threshold_and_critical_effect_are_nonnegotiable(self):
        self.assertFalse(b11.verify_holdout(dict(self.holdout, accuracy=.9499), self.sha))
        self.assertFalse(b11.verify_holdout(dict(self.holdout, incorrect_action_proposals=1), self.sha))
        self.assertFalse(b11.verify_holdout(dict(self.holdout, attempted_effects=1), self.sha))
        self.assertFalse(b11.verify_holdout(dict(self.holdout, accuracy=True), self.sha))


if __name__ == "__main__":
    unittest.main()
