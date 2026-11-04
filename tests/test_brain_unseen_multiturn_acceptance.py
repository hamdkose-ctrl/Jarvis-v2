from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts import brain_acceptance as harness


POOL = Path(__file__).parent / "data" / "brain_unseen_multiturn_100.json"


class UnseenTurkishMultiturnContextTests(unittest.TestCase):
    def test_one_hundred_unseen_multiturn_context_and_owner_boundary_cases(self):
        rows = json.loads(POOL.read_text(encoding="utf-8"))["senaryolar"]
        self.assertEqual(len(rows), 100)
        self.assertEqual(len({row["id"] for row in rows}), 100)
        correct = 0
        errors = []
        critical = []
        for row in rows:
            result = harness.run_scenario(row)
            decision = result["decision"]
            mismatches = {
                key: (decision.get(key), expected)
                for key, expected in row["expect"].items()
                if decision.get(key) != expected
            }
            if mismatches:
                errors.append((row["id"], row["text"], mismatches))
            else:
                correct += 1
            expected_outcome = row["expect"].get("outcome")
            if expected_outcome == "clarify" and decision.get("outcome") == "action":
                critical.append((row["id"], row["text"], decision))
            expected_protocol = row["expect"].get("protocol")
            if expected_protocol and decision.get("protocol") != expected_protocol:
                critical.append((row["id"], row["text"], decision))
        accuracy = correct / len(rows)
        self.assertGreaterEqual(accuracy, 0.95, f"accuracy={accuracy:.1%}; failures={errors[:20]}")
        self.assertEqual(critical, [], f"critical context/owner routing errors: {critical[:20]}")


if __name__ == "__main__":
    unittest.main()
