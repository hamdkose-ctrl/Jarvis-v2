import json
import tempfile
import unittest
from pathlib import Path

from modules import execution_record, goal_state, goal_state_compat, goal_state_save_hook
from modules import goal_state_store, goalstate_cutover_runner as runner


class GoalStateAuthorityPromotionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.owner_dir = Path(self.tmp.name) / "alice"
        self.owner_dir.mkdir()
        self.job = {
            "id": "0123456789abcdef", "owner": "alice", "request": "Raporu hazırla",
            "state": "paused", "goals": [], "steps": [], "outputs": {},
        }
        self.legacy = self.owner_dir / (self.job["id"] + ".json")
        self.canonical = self.owner_dir / (self.job["id"] + ".goalstate.json")
        self.legacy.write_text(json.dumps(self.job), encoding="utf-8")
        goal_state_compat.operator_backfill_missing_canonical_once(
            self.job, self.canonical, operator_approved=True,
        )

    def test_operator_promotion_migrates_execution_record_then_stops_legacy_writes(self):
        before_legacy = self.legacy.read_bytes()
        plan = runner.plan(self.owner_dir)
        self.assertEqual(plan["promotion_candidates"], [self.job["id"]])

        result = runner.promote(
            self.owner_dir, approved_fingerprint=plan["fingerprint"],
            approved_job_ids=[self.job["id"]],
        )

        self.assertEqual(result["promoted"], [self.job["id"]])
        self.assertEqual(goal_state.authority(goal_state_store.load(self.canonical)), "canonical")
        self.assertEqual(execution_record.load(self.owner_dir, "alice", self.job["id"]), self.job)
        self.assertEqual(self.legacy.read_bytes(), before_legacy)

        updated = {**self.job, "state": "running"}
        goal_state_save_hook._atomic(
            self.legacy, json.dumps(updated, ensure_ascii=False).encode("utf-8"),
        )
        self.assertEqual(self.legacy.read_bytes(), before_legacy)
        self.assertEqual(
            execution_record.load(self.owner_dir, "alice", self.job["id"])["state"], "running",
        )


if __name__ == "__main__":
    unittest.main()
