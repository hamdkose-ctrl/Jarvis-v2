from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts import brain_acceptance as harness


POOL = Path(__file__).parent / "data" / "brain_multiturn_context_100.json"


class UnseenTurkishMultiTurnContextTests(unittest.TestCase):
    def test_one_hundred_unseen_contextual_turns_preserve_relation_and_effect_boundaries(self):
        rows = json.loads(POOL.read_text(encoding="utf-8"))["senaryolar"]
        self.assertEqual(len(rows), 100)
        self.assertEqual(len({row["id"] for row in rows}), 100)
        self.assertTrue(all(len(row.get("setup", {}).get("history", [])) >= 2 for row in rows))

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
            if row["group"] in {"s5_multiturn_chat", "s5_multiturn_supersede_chat"}:
                if decision.get("outcome") == "action" or decision.get("capability_hint") is not None:
                    critical.append((row["id"], row["text"], decision))

        accuracy = correct / len(rows)
        self.assertGreaterEqual(accuracy, 0.95, f"accuracy={accuracy:.1%}; failures={errors[:20]}")
        self.assertEqual(critical, [], f"critical false execution/target errors: {critical[:20]}")


if __name__ == "__main__":
    unittest.main()
