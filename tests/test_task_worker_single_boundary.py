"""PR-4: the two task worker wrappers execute one shared boundary body.

`task_worker_adapter.run` is the single body (deepcopy + validate_input +
tool hooks + seal). The legacy lane (`task_agents.worker`) keeps its
injectable `_worker` seam and the canonical lane (`task_worker_adapter.worker`)
keeps `task_workers.run` as the default executor. These tests pin the parity:
identical hook pairs, sealing, failure semantics and pre-execution validation.
"""
import unittest
from unittest.mock import patch

from modules import hooks, task_agents, task_worker_adapter


LANE_MODULES = ("legacy", "canonical")


def _task():
    return {"id": "t1", "agent": "verify", "input": {}, "execution": {"note": "kaydırma"}}


class SingleBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.owner = "worker-boundary-tests"
        self.events = []
        hooks.register("tool", lambda event: self.events.append(event), owner=self.owner)
        self.addCleanup(hooks.clear, owner=self.owner)
        # The seal contract itself is tested in the results suites; the
        # boundary here is pinned with a pass-through seal.
        seal_pass = patch.object(task_agents.task_results, "seal",
                                 side_effect=lambda kind, output: output)
        seal_pass.start()
        self.addCleanup(seal_pass.stop)

    # ---- lane plumbing -------------------------------------------------

    def test_legacy_lane_uses_its_injectable_worker_seam(self):
        seen = []

        def seam(owner, task, dependencies):
            seen.append((owner, task["id"], task["agent"], dependencies))
            return {"state": "done", "text": "tamam"}

        with patch.object(task_agents, "_worker", side_effect=seam), \
                patch.object(task_agents.task_results, "seal", side_effect=lambda kind, o: o), \
                patch.object(task_worker_adapter.task_workers, "run",
                             side_effect=AssertionError("legacy lane task_workers.run çağırmamalı")):
            output = task_agents.worker(self.owner, _task(), {"d": 1})
        self.assertEqual(seen, [(self.owner, "t1", "verify", {"d": 1})])
        self.assertEqual(output["state"], "done")

    def test_canonical_lane_executes_through_task_workers_run(self):
        seen = []

        def real_runner(owner, task, dependencies):
            seen.append((owner, task["id"], dependencies))
            return {"state": "done", "text": "tamam"}

        with patch.object(task_worker_adapter.task_workers, "run", side_effect=real_runner), \
                patch.object(task_agents.task_results, "seal", side_effect=lambda kind, o: o):
            output = task_worker_adapter.worker(self.owner, _task(), {})
        self.assertEqual(seen, [(self.owner, "t1", {})])
        self.assertEqual(output["state"], "done")

    # ---- parity --------------------------------------------------------

    def _lane_call(self, lane, owner, task, dependencies):
        if lane == "legacy":
            return task_agents.worker(owner, task, dependencies)
        return task_worker_adapter.worker(owner, task, dependencies)

    def _fake_execute(self, lane, result):
        # The legacy lane resolves the seam at call time; the canonical lane
        # resolves task_workers.run at call time. Both route into one fake so
        # the shared body receives identical inputs per lane.
        if lane == "legacy":
            return patch.object(task_agents, "_worker", side_effect=lambda *a: dict(result))
        return patch.object(task_worker_adapter.task_workers, "run",
                            side_effect=lambda *a: dict(result))

    def test_both_lanes_emit_identical_tool_hook_pairs(self):
        recorded = {}
        for lane in LANE_MODULES:
            self.events.clear()
            ctx = self._fake_execute(lane, {"state": "done", "text": "tamam"})
            with ctx:
                self._lane_call(lane, self.owner, _task(), {})
            recorded[lane] = [(e["owner"], e["payload"]["phase"], e["payload"]["tool"],
                               e["payload"]["task_id"], e["payload"].get("state"))
                              for e in self.events]
        self.assertEqual(recorded["legacy"], recorded["canonical"])
        self.assertEqual([row[1] for row in recorded["legacy"]], ["start", "end"])
        self.assertEqual(recorded["legacy"][1][4], "done")

    def test_both_lanes_seal_the_executor_output_with_the_agent_kind(self):
        seals = {}
        for lane in LANE_MODULES:
            ctx = self._fake_execute(lane, {"state": "done", "text": "ham"})
            calls = []

            def fake_seal(kind, output, _calls=calls):
                _calls.append((kind, dict(output)))
                return {"sealed": True, "state": "done", "agent": kind, "body": output}

            with ctx, patch.object(task_agents.task_results, "seal", side_effect=fake_seal):
                output = self._lane_call(lane, self.owner, _task(), {})
            seals[lane] = (calls, output)
        self.assertEqual(seals["legacy"][0], seals["canonical"][0])
        self.assertEqual(seals["legacy"][0], [("verify", {"state": "done", "text": "ham"})])
        self.assertEqual(seals["legacy"][1], seals["canonical"][1])
        self.assertTrue(seals["legacy"][1]["sealed"])

    def test_invalid_capability_fails_before_hooks_or_execution_in_both_lanes(self):
        for lane in LANE_MODULES:
            self.events.clear()
            executor = patch.object(task_agents, "_worker",
                                    side_effect=AssertionError("çalıştırıcı çağrılmamalı")) \
                if lane == "legacy" else \
                patch.object(task_worker_adapter.task_workers, "run",
                             side_effect=AssertionError("çalıştırıcı çağrılmamalı"))
            task = {"id": "t1", "agent": "olmayan-yetenek", "input": {}}
            with executor:
                with self.assertRaises(ValueError):
                    self._lane_call(lane, self.owner, task, {})
            self.assertEqual(self.events, [])

    def test_both_lanes_deep_copy_the_task_before_execution(self):
        original = _task()
        for lane in LANE_MODULES:
            def mutate(owner, task, dependencies):
                task["input"] = {"enjekte": True}
                task["execution"] = {"note": "bozuldu"}
                task["yeni_anahtar"] = 1
                return {"state": "done", "text": "tamam"}

            if lane == "legacy":
                ctx = patch.object(task_agents, "_worker", side_effect=mutate)
            else:
                ctx = patch.object(task_worker_adapter.task_workers, "run", side_effect=mutate)
            with ctx:
                self._lane_call(lane, self.owner, original, {})
            self.assertEqual(original["input"], {})
            self.assertEqual(original["execution"], {"note": "kaydırma"})
            self.assertNotIn("yeni_anahtar", original)

    # ---- failure semantics ---------------------------------------------

    def test_executor_exception_still_emits_failed_end_hook_in_both_lanes(self):
        for lane in LANE_MODULES:
            self.events.clear()
            if lane == "legacy":
                ctx = patch.object(task_agents, "_worker", side_effect=RuntimeError("işçi patladı"))
            else:
                ctx = patch.object(task_worker_adapter.task_workers, "run",
                                   side_effect=RuntimeError("işçi patladı"))
            with ctx:
                with self.assertRaises(RuntimeError):
                    self._lane_call(lane, self.owner, _task(), {})
            phases = [e["payload"]["phase"] for e in self.events]
            self.assertEqual(phases, ["start", "end"])
            self.assertEqual(self.events[-1]["payload"]["state"], "failed")

    def test_seal_failure_keeps_failed_end_hook_in_both_lanes(self):
        for lane in LANE_MODULES:
            self.events.clear()
            ctx = self._fake_execute(lane, {"state": "done", "text": "tamam"})
            with ctx, patch.object(task_agents.task_results, "seal",
                                   side_effect=RuntimeError("mühür bozuk")):
                with self.assertRaises(RuntimeError):
                    self._lane_call(lane, self.owner, _task(), {})
            self.assertEqual([e["payload"]["phase"] for e in self.events], ["start", "end"])
            self.assertEqual(self.events[-1]["payload"]["state"], "failed")

    def test_state_variants_report_end_hook_identically_in_both_lanes(self):
        variants = [
            {"state": "waiting", "question": "?"},
            {"text": "state yok"},
            "sözlük-dışı",
        ]
        for index, result in enumerate(variants):
            for lane in LANE_MODULES:
                self.events.clear()
                if lane == "legacy":
                    ctx = patch.object(task_agents, "_worker", return_value=result)
                else:
                    ctx = patch.object(task_worker_adapter.task_workers, "run",
                                       return_value=result)
                with ctx, patch.object(task_agents.task_results, "seal",
                                       side_effect=lambda kind, output: output):
                    self._lane_call(lane, self.owner, _task(), {})
                expected = result.get("state", "failed") if isinstance(result, dict) else "failed"
                self.assertEqual(self.events[-1]["payload"]["state"], expected,
                                 f"varyant {index} lane {lane}")

    def test_owner_identity_reaches_tool_hooks_on_both_lanes(self):
        probe_owner = self.owner + "-probe"
        probe_events = []
        hooks.register("tool", lambda event: probe_events.append(event), owner=probe_owner)
        self.addCleanup(hooks.clear, owner=probe_owner)
        for lane in LANE_MODULES:
            probe_events.clear()
            ctx = self._fake_execute(lane, {"state": "done", "text": "tamam"})
            with ctx:
                self._lane_call(lane, probe_owner, _task(), {})
            self.assertEqual([e["owner"] for e in probe_events], [probe_owner, probe_owner])
            self.assertEqual([e["payload"]["phase"] for e in probe_events], ["start", "end"])


if __name__ == "__main__":
    unittest.main()
