import unittest

from modules.research_providers import compare_sources, verify_conflict


def source(name, *, value, subject="faiz oranı", claim_type="rate",
           unit="percent", observed_at="2026-10-27", scope="Türkiye"):
    return {
        "url": "https://" + name + ".test/article",
        "source": name,
        "subject": subject,
        "claim_type": claim_type,
        "value": value,
        "unit": unit,
        "observed_at": observed_at,
        "scope": scope,
        "source_kind": "official",
    }


class ResearchConflictVerificationTests(unittest.TestCase):
    def test_semantic_agreement_is_not_a_conflict_or_a_verification_request(self):
        first = source("a", value=10, claim_type="revenue_change", unit="percent",
                       subject="Şirket geliri")
        first["claim"] = "Şirket geliri yüzde 10 arttı."
        second = source("b", value=10, claim_type="revenue_change", unit="percent",
                        subject="şirket geliri")
        second["claim"] = "Gelir geçen yıla göre yaklaşık %10 yükseldi."

        called = []
        result = verify_conflict([first, second], verifier=lambda conflict: called.append(conflict))

        self.assertEqual(result["status"], "consistent")
        self.assertFalse(result["verification_attempted"])
        self.assertEqual(called, [])

    def test_numeric_and_categorical_conflicts_request_one_bounded_verification(self):
        numeric = verify_conflict([
            source("a", value=40), source("b", value=45),
        ], verifier=lambda conflict: [])
        categorical = verify_conflict([
            source("a", value="approved", subject="izin", claim_type="decision", unit="state"),
            source("b", value="rejected", subject="izin", claim_type="decision", unit="state"),
        ], verifier=lambda conflict: [])

        self.assertEqual(numeric["status"], "unresolved_conflict")
        self.assertEqual(categorical["status"], "unresolved_conflict")
        self.assertTrue(numeric["verification_attempted"])
        self.assertEqual(numeric["reason_code"], "NUMERIC_CONFLICT")
        self.assertEqual(categorical["reason_code"], "CATEGORICAL_CONFLICT")
        self.assertIn("çelişiyor", numeric["uncertainty"])

    def test_time_and_scope_differences_are_not_conflicts(self):
        newer = source("new", value=45)
        older = source("old", value=40, observed_at="2026-09-27")
        other_scope = source("global", value=50, scope="global")

        self.assertEqual(compare_sources([newer, older])["status"], "consistent")
        self.assertEqual(compare_sources([newer, other_scope])["status"], "consistent")

    def test_third_source_resolves_only_when_it_supports_one_existing_claim(self):
        result = verify_conflict(
            [source("a", value=40), source("b", value=45)],
            verifier=lambda conflict: [source("official", value=45)],
        )

        self.assertEqual(result["status"], "resolved_conflict")
        self.assertEqual(result["resolved_value"], 45)
        self.assertEqual(result["resolved_by"]["source"], "official")
        self.assertEqual(len(result["sources"]), 3)

    def test_third_source_that_does_not_break_the_tie_stays_unresolved_and_deterministic(self):
        sources = [source("a", value=40), source("b", value=45)]
        result = verify_conflict(sources, verifier=lambda conflict: [source("third", value=42)])

        self.assertEqual(result["status"], "unresolved_conflict")
        self.assertNotIn("resolved_value", result)
        self.assertEqual(result, verify_conflict(sources, verifier=lambda conflict: [source("third", value=42)]))


if __name__ == "__main__":
    unittest.main()
