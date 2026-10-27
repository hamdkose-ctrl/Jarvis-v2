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


    def test_promoted_save_hook_cannot_change_canonical_lifecycle(self):
        plan = runner.plan(self.owner_dir)
        runner.promote(
            self.owner_dir, approved_fingerprint=plan["fingerprint"],
            approved_job_ids=[self.job["id"]],
        )
        before = goal_state_store.load(self.canonical)
        goal_state_save_hook._atomic(
            self.legacy, json.dumps({**self.job, "state": "running"}).encode("utf-8"),
        )
        self.assertEqual(goal_state_store.load(self.canonical), before)

    def test_execution_record_write_failure_does_not_promote_authority(self):
        from unittest.mock import patch
        plan = runner.plan(self.owner_dir)
        original_atomic = runner.release_guard.atomic

        def fail_execution_record(path, data):
            if str(path).endswith(".execution.json"):
                raise OSError("simulated execution record write failure")
            return original_atomic(path, data)

        with patch.object(runner.release_guard, "atomic", side_effect=fail_execution_record):
            with self.assertRaises(OSError):
                runner.promote(
                    self.owner_dir, approved_fingerprint=plan["fingerprint"],
                    approved_job_ids=[self.job["id"]],
                )
        self.assertEqual(goal_state.authority(goal_state_store.load(self.canonical)), "legacy")
        self.assertFalse((self.owner_dir / (self.job["id"] + ".execution.json")).exists())

    def test_canonical_cas_failure_restores_execution_record(self):
        from unittest.mock import patch
        plan = runner.plan(self.owner_dir)
        record = self.owner_dir / (self.job["id"] + ".execution.json")
        original = b'{"preexisting":"record"}'
        record.write_bytes(original)
        with patch.object(
            goal_state_compat, "operator_promote_legacy_authority_once",
            side_effect=goal_state_store.PersistedStateConflict("simulated CAS conflict"),
        ):
            with self.assertRaises(goal_state_store.PersistedStateConflict):
                runner.promote(
                    self.owner_dir, approved_fingerprint=plan["fingerprint"],
                    approved_job_ids=[self.job["id"]],
                )
        self.assertEqual(record.read_bytes(), original)
        self.assertEqual(goal_state.authority(goal_state_store.load(self.canonical)), "legacy")


    def test_post_promotion_verification_failure_restores_both_records(self):
        from unittest.mock import patch
        plan = runner.plan(self.owner_dir)
        record = self.owner_dir / (self.job["id"] + ".execution.json")
        original = b'{"preexisting":"record"}'
        record.write_bytes(original)
        with patch.object(runner, "_verify_promotion", side_effect=runner.CutoverVerificationFailed("simulated")):
            with self.assertRaises(runner.CutoverVerificationFailed):
                runner.promote(
                    self.owner_dir, approved_fingerprint=plan["fingerprint"],
                    approved_job_ids=[self.job["id"]],
                )
        self.assertEqual(record.read_bytes(), original)
        self.assertEqual(goal_state.authority(goal_state_store.load(self.canonical)), "legacy")


if __name__ == "__main__":
    unittest.main()
