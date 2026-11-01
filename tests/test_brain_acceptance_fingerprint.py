import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import brain_acceptance as harness


def _result(outcome):
    row = {key: None for key in harness.DECISION_KEYS}
    row["outcome"] = outcome
    return {"decision": row, "info": {}}


class AcceptedDiffFingerprintTests(unittest.TestCase):
    def test_same_id_with_a_different_diff_changes_the_fingerprint(self):
        first = {"a": {"verdict": "accepted", "diff": {"outcome": {"baseline": "chat", "current": "action"}}}}
        second = {"a": {"verdict": "accepted", "diff": {"outcome": {"baseline": "chat", "current": "clarify"}}}}
        self.assertNotEqual(
            harness._accepted_diff_fingerprint(first, {"a"}),
            harness._accepted_diff_fingerprint(second, {"a"}),
        )

    def test_default_acceptance_pin_rejects_a_drift_under_the_same_id(self):
        pool = [{"id": "a", "text": "x"}]
        baseline = {"results": {"a": _result("chat")}}
        accepted = {"a": "reviewed"}
        current = {"results": {"a": _result("action")}}
        probe = harness.compare(pool, baseline, current, accepted)
        expected = probe["accepted_diff_fingerprint"]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            accepted_path = root / "accepted.json"
            fingerprint_path = root / "fingerprint.txt"
            accepted_path.write_text(json.dumps(accepted), encoding="utf-8")
            fingerprint_path.write_text(expected + "\n", encoding="utf-8")
            with patch.object(harness, "DEFAULT_ACCEPTED", accepted_path), \
                    patch.object(harness, "DEFAULT_ACCEPTED_FINGERPRINT", fingerprint_path):
                stable = harness.compare(pool, baseline, current, accepted)
                self.assertTrue(stable["passed"])
                self.assertTrue(stable["accepted_diff_fingerprint_match"])

                drifted = harness.compare(
                    pool,
                    baseline,
                    {"results": {"a": _result("clarify")}},
                    accepted,
                )
                self.assertFalse(drifted["passed"])
                self.assertFalse(drifted["accepted_diff_fingerprint_match"])
                self.assertNotEqual(drifted["accepted_diff_fingerprint"], expected)

    def test_committed_default_pin_matches_the_current_accepted_diff_set(self):
        pool = harness.load_pool()
        baseline = json.loads(harness.DEFAULT_BASELINE.read_text(encoding="utf-8"))
        accepted = json.loads(harness.DEFAULT_ACCEPTED.read_text(encoding="utf-8"))
        report = harness.compare(pool, baseline, harness.capture(pool), accepted)
        self.assertTrue(
            report["accepted_diff_fingerprint_match"],
            f"expected={report['accepted_diff_fingerprint_expected']} current={report['accepted_diff_fingerprint']}",
        )


if __name__ == "__main__":
    unittest.main()
