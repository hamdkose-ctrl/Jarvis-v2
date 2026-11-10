"""BRAIN-06C: result fences against canonical plan version and node digest.

These use the *actual* GoalState CAS store with a mock worker output. They do
not execute an external effect, prove completion, or claim DAG Scheduler wiring.
"""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import (
    core_state_reducer, goal_state, goal_state_store, runtime_worker_result,
    worker_result, worker_result_hook,
)


OWNER = "alice"
JOB = "0123456789abcdef"
DATA = {"url": "https://example.test", "question": "x"}


def node(name="s1", deps=(), *, capability="task.research", data=None):
    return {
        "id": name, "depends_on": list(deps),
        "capability_id": capability,
        "input": copy.deepcopy(DATA if data is None else data),
        "expected_output": "source report",
        "acceptance": "verified source evidence",
    }


def plan(version=1, nodes=None):
    return {"plan_version": version,
            "nodes": nodes if nodes is not None else [node(), node("s2", ("s1",))]}


def identity(step="s1"):
    return {"version": 1, "owner": OWNER, "job_id": JOB, "task_id": step,
            "attempt": 1, "request": "örnek"}


class PlannedWorkerResultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        path = self.root / OWNER / (JOB + ".goalstate.json")
        path.parent.mkdir(parents=True)
        self.path = path
        start = goal_state.new(owner=OWNER, job_id=JOB, goal="Araştır",
                               authority="canonical")
        snapshot = core_state_reducer.apply(start, {
            "op": "set_goal_plan", "plan": plan(),
            "reason_code": "TEST_PLAN", "expected_version": start["version"],
        })
        goal_state_store.create(path, snapshot)
        from modules import goal_executor
        patcher = patch.object(goal_executor, "STORE", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _prepared(self, step="s1"):
        enriched, expected = runtime_worker_result.prepare(
            identity(step), "research", DATA,
        )
        result = worker_result_hook.wrap_output(
            {"state": "done", "verification": {"source": "example.test"}}, enriched,
        )
        return enriched, expected, result

    def test_root_result_uses_explicit_plan_schema_and_persists_one_evidence(self):
        enriched, expected, output = self._prepared()
        self.assertEqual(expected["plan_version"], 1)
        self.assertEqual(enriched["node_digest"], expected["node_digest"])
        self.assertEqual(len(expected["node_digest"]), 64)
        self.assertEqual(expected["command_id"], "s1:1:p1")
        self.assertEqual(output["_worker_result"]["schema"], worker_result.PLAN_SCHEMA)
        self.assertEqual(worker_result.accept(output["_worker_result"], expected)["status"],
                         "succeeded")
        clean = runtime_worker_result.accept_and_commit(output, expected)
        self.assertEqual(clean["state"], "done")
        self.assertNotIn("_worker_result", clean)
        saved = goal_state_store.load(self.path)
        self.assertEqual(saved["version"], 2)
        self.assertEqual(saved["evidence"][0]["kind"], "worker_result")
        self.assertEqual(saved["evidence"][0]["plan_version"], 1)
        self.assertEqual(saved["evidence"][0]["node_digest"], expected["node_digest"])
        self.assertEqual(saved["evidence"][0]["command_id"], "s1:1:p1")

    def test_identical_result_replay_is_idempotent_not_double_committed(self):
        _, expected, output = self._prepared()
        runtime_worker_result.accept_and_commit(output, expected)
        runtime_worker_result.accept_and_commit(output, expected)
        saved = goal_state_store.load(self.path)
        self.assertEqual(saved["version"], 2)
        self.assertEqual(len(saved["evidence"]), 1)

    def test_plan_revision_rejects_late_result_before_writing(self):
        _, expected, output = self._prepared()
        current = goal_state_store.load(self.path)
        updated = core_state_reducer.apply(current, {
            "op": "set_goal_plan", "plan": plan(2),
            "expected_version": current["version"], "reason_code": "TEST_REVISION",
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=current["version"], next_state=updated,
        )
        with self.assertRaises(ValueError):
            runtime_worker_result.accept_and_commit(output, expected)
        self.assertEqual(goal_state_store.load(self.path), updated)

    def test_old_worker_version_rejected_after_unrelated_state_write(self):
        _, expected, output = self._prepared()
        current = goal_state_store.load(self.path)
        updated = core_state_reducer.apply(current, {
            "op": "append_evidence", "evidence": {"other": True},
            "reason_code": "TEST_OTHER_WRITER", "expected_version": current["version"],
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=current["version"], next_state=updated,
        )
        with self.assertRaises(ValueError):
            runtime_worker_result.accept_and_commit(output, expected)
        self.assertEqual(goal_state_store.load(self.path), updated)

    def test_unknown_dependent_or_effectful_nodes_are_never_dispatched(self):
        with self.assertRaisesRegex(ValueError, "Bağımlı"):
            self._prepared("s2")
        with self.assertRaises(ValueError):
            runtime_worker_result.prepare(identity("wrong"), "research", DATA)
        with self.assertRaises(ValueError):
            runtime_worker_result.prepare(identity("s1"), "writer", DATA)
        self.assertEqual(goal_state_store.load(self.path)["evidence"], [])

    def test_legacy_v1_result_cannot_commit_to_canonical_plan(self):
        enriched, expected = runtime_worker_result.prepare(
            identity(), "research", DATA, expected_job_version=1,
        )
        self.assertNotIn("plan_version", expected)
        output = worker_result_hook.wrap_output(
            {"state": "done", "verification": {"ok": True}}, enriched,
        )
        self.assertEqual(output["_worker_result"]["schema"], worker_result.SCHEMA)
        with self.assertRaisesRegex(ValueError, "legacy WorkerResult"):
            runtime_worker_result.accept_and_commit(output, expected)
        self.assertEqual(goal_state_store.load(self.path)["evidence"], [])

    def test_corrupted_plan_fence_fails_before_mutation(self):
        _, expected, output = self._prepared()
        invalid = [
            ("plan_version", 7), ("node_digest", "f" * 64),
            ("node_digest", "not-a-digest"), ("command_id", "s1:1"),
            ("owner", "mallory"),
        ]
        for field, forged in invalid:
            with self.subTest(field=field, value=forged):
                row = copy.deepcopy(output)
                row["_worker_result"][field] = forged
                with self.assertRaises(ValueError):
                    runtime_worker_result.accept_and_commit(row, expected)
        self.assertEqual(goal_state_store.load(self.path)["evidence"], [])

    def test_incomplete_plan_fields_never_downgrade_to_v1(self):
        enriched, expected, output = self._prepared()
        for field in ("node_digest", "plan_version"):
            with self.subTest(field=field):
                bad = copy.deepcopy(enriched)
                bad.pop(field)
                with self.assertRaises(ValueError):
                    worker_result_hook.wrap_output({"state": "done"}, bad)
        self.assertEqual(goal_state_store.load(self.path)["evidence"], [])

    def test_planned_recovery_without_prior_committed_fence_cannot_claim_current_plan(self):
        from modules import reconcile_worker_result
        output = {"state": "done", "verification": {"source": "example.test"}}
        with self.assertRaisesRegex(ValueError, "önceden kabul edilmiş"):
            reconcile_worker_result.accept_and_commit(output, identity(), "research", DATA)
        self.assertEqual(goal_state_store.load(self.path)["evidence"], [])

    def test_read_only_reconcile_reuses_exact_accepted_plan_result_without_second_write(self):
        from modules import reconcile_worker_result
        _, expected, output = self._prepared()
        runtime_worker_result.accept_and_commit(output, expected)
        # Synthetic fixture intentionally lacks real task_result sealing;
        # this test measures exact-fence reconcile, not domain verification.
        with patch("modules.goal_tools.verify", return_value=True) as verified:
            result = reconcile_worker_result.accept_and_commit(
                {"state": "done", "verification": {"source": "example.test"}},
                identity(), "research", DATA,
            )
        verified.assert_called_once()
        self.assertEqual(result["state"], "done")
        self.assertEqual(goal_state_store.load(self.path)["version"], 2)
        self.assertEqual(len(goal_state_store.load(self.path)["evidence"]), 1)

    def test_old_read_only_reconcile_cannot_mint_new_version_after_plan_revision(self):
        from modules import reconcile_worker_result
        _, expected, output = self._prepared()
        runtime_worker_result.accept_and_commit(output, expected)
        before = goal_state_store.load(self.path)
        after = core_state_reducer.apply(before, {
            "op": "set_goal_plan", "plan": plan(2),
            "expected_version": before["version"], "reason_code": "TEST_REVISION",
        })
        goal_state_store.compare_and_swap(
            self.path, expected_version=before["version"], next_state=after,
        )
        with self.assertRaises(ValueError):
            reconcile_worker_result.accept_and_commit(
                {"state": "done", "verification": {"source": "example.test"}},
                identity(), "research", DATA,
            )
        self.assertEqual(goal_state_store.load(self.path), after)

    def test_existing_v1_unplanned_protocol_remains_supported(self):
        result = {
            "schema": worker_result.SCHEMA, "status": "succeeded", "evidence": [],
            "owner": OWNER, "job_id": JOB, "step_id": "s1", "command_id": "s1:1",
            "attempt": 1, "expected_job_version": 1, "capability_id": "task.research",
            "capability_version": "1", "input_digest": "f"*64,
        }
        expected = {k: v for k, v in result.items() if k not in
                    {"schema", "status", "evidence"}}
        self.assertEqual(worker_result.accept(result, expected), result)


if __name__ == "__main__":
    unittest.main()
