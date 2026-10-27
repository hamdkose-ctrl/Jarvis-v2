from __future__ import annotations

import unittest

from scripts.roadmap_completion_evidence_check import check_completion_evidence


class RoadmapCompletionEvidenceTests(unittest.TestCase):
    def test_new_completed_item_without_evidence_fails(self):
        base = "- 🟡 Faz 4A araştırma worker\n"
        current = "- ✅ Faz 4A araştırma worker\n"
        result = check_completion_evidence(base, current)
        self.assertFalse(result["pass"])
        self.assertEqual(1, len(result["missing_evidence"]))

    def test_new_completed_item_with_full_evidence_passes(self):
        base = "- 🟡 Faz 4A araştırma worker\n"
        current = (
            "- ✅ Faz 4A araştırma worker\n"
            "  Kanıt: PR=#410; SHA=abcdef123456; Contract=#372; "
            "Migration=n/a; Wiring=#400; Acceptance=watcher-pass@abcdef123456; "
            "Cleanup=verified\n"
        )
        result = check_completion_evidence(base, current)
        self.assertTrue(result["pass"])

    def test_acceptance_sha_must_match_evidence_sha(self):
        base = "- 🟡 Faz 4A araştırma worker\n"
        current = (
            "- ✅ Faz 4A araştırma worker\n"
            "  Kanıt: PR=#410; SHA=abcdef123456; Contract=#372; "
            "Migration=n/a; Wiring=#400; Acceptance=watcher-pass@123456abcdef; "
            "Cleanup=verified\n"
        )
        result = check_completion_evidence(base, current)
        self.assertFalse(result["pass"])
        self.assertTrue(result["invalid_evidence"])

    def test_cleanup_cannot_be_missing(self):
        base = "- 🟡 Faz 1 provider dayanıklılığı\n"
        current = (
            "- ✅ Faz 1 provider dayanıklılığı\n"
            "  Kanıt: PR=#411; SHA=abcdef123456; Contract=#350; "
            "Migration=#411; Wiring=#411; Acceptance=watcher-pass@abcdef123456\n"
        )
        result = check_completion_evidence(base, current)
        self.assertFalse(result["pass"])

    def test_na_is_allowed_for_migration_or_cleanup_when_not_applicable(self):
        base = "- Yeni yetenek\n"
        current = (
            "- ✅ Yeni yetenek\n"
            "  Kanıt: PR=#412; SHA=abcdef123456; Contract=#412; "
            "Migration=n/a; Wiring=#412; Acceptance=watcher-pass@abcdef123456; "
            "Cleanup=n/a\n"
        )
        self.assertTrue(check_completion_evidence(base, current)["pass"])

    def test_existing_completed_item_is_not_retroactively_blocked(self):
        base = "- ✅ Eski tamamlanmış madde\n"
        current = "- ✅ Eski tamamlanmış madde\n"
        result = check_completion_evidence(base, current)
        self.assertTrue(result["pass"])
        self.assertFalse(result["new_completions"])

    def test_partial_item_does_not_require_completion_evidence(self):
        base = "- 🟡 Kısmi madde\n"
        current = "- 🟡 Kısmi madde güncellendi\n"
        self.assertTrue(check_completion_evidence(base, current)["pass"])

    def test_phase_status_completed_also_requires_evidence(self):
        base = "**Durum: 🟡 kısmi**\n"
        current = (
            "**Durum: ✅ tamamlandı**\n"
            "Kanıt: PR=#413; SHA=abcdef123456; Contract=#413; "
            "Migration=#413; Wiring=#413; Acceptance=watcher-pass@abcdef123456; "
            "Cleanup=verified\n"
        )
        self.assertTrue(check_completion_evidence(base, current)["pass"])


if __name__ == "__main__":
    unittest.main()
