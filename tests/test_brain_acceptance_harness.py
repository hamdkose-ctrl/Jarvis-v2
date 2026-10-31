"""PR7 Closeout-B kabul harness'i (scripts/brain_acceptance.py) için sözleşme testleri.

Harness yalnız ölçer: canonical Brain kararını yalıtılmış sahte runtime ile kaydeder ve
"aynı veya daha iyi" kapısını uygular. Bu testler kaydedilen baseline'ın içeriğini
(yani bugünkü Brain davranışını) sabitlemez; Closeout-A/B davranışı değiştirdiğinde
baseline CLI ile yeniden alınır.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import brain_acceptance as harness

_RESERVED = {
    "allowed", "permission", "permission_granted", "approved", "authorized",
    "completed", "done", "effect_allowed", "execute",
}


def _result(**decision):
    row = {key: None for key in harness.DECISION_KEYS}
    row.update(decision)
    return {"decision": row, "info": {}}


class PoolTests(unittest.TestCase):
    def test_pool_combines_curated_and_existing_corpora_with_unique_ids(self):
        pool = harness.load_pool()
        ids = [row["id"] for row in pool]
        self.assertEqual(len(ids), len(set(ids)))
        groups = {row.get("group") for row in pool}
        for group in ("last_property", "pending", "clarification", "typo", "referans",
                      "fast", "capability", "adversarial", "yonlendirme", "enjeksiyon",
                      "matris_m160", "matris_p10"):
            self.assertIn(group, groups)
        routing = json.loads(harness.ROUTING_CORPUS.read_text(encoding="utf-8"))["cumleler"]
        self.assertEqual(sum(1 for row in pool if row["group"] == "yonlendirme"), len(routing))

    def test_seventy_acceptance_matrix_is_in_pool(self):
        pool = {row["id"]: row for row in harness.load_pool(include_corpora=False, matrices={})}
        self.assertEqual(pool["k-70-bos"]["expect"], {"outcome": "clarify"})
        self.assertEqual(pool["k-70-volume"]["expect"], {"outcome": "action"})
        self.assertEqual(pool["k-70-brightness"]["expect"], {"outcome": "action"})
        self.assertEqual(pool["k-70-baska-owner"]["expect"], {"outcome": "clarify"})
        self.assertEqual(pool["k-70-bayat"]["expect"], {"outcome": "clarify"})

    def test_routing_ids_are_stable_and_disputed_rows_have_no_expectation(self):
        rows = harness._routing_scenarios()
        self.assertEqual([r["id"] for r in rows], [r["id"] for r in harness._routing_scenarios()])
        for row in rows:
            if row["meta"].get("tartismali"):
                self.assertNotIn("expect", row)

    def test_extra_pool_file_is_appended_and_duplicate_ids_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ek.json"
            path.write_text(json.dumps({"senaryolar": [{"id": "ek-1", "text": "merhaba"}]}), encoding="utf-8")
            pool = harness.load_pool([path], include_corpora=False, matrices={})
            self.assertEqual(pool[-1]["id"], "ek-1")
            path.write_text(json.dumps({"senaryolar": [{"id": "k-70-bos", "text": "x"}]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "tekrarlanıyor"):
                harness.load_pool([path], include_corpora=False, matrices={})

    def test_unknown_criteria_field_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "bilinmeyen kriter"):
            harness._validate_scenario({"id": "x", "text": "y", "expect": {"permission": True}})


class RunTests(unittest.TestCase):
    def test_run_records_decision_without_authority_fields(self):
        result = harness.run_scenario({"id": "t-saat", "text": "saat kaç"})
        self.assertEqual(set(result["decision"]), set(harness.DECISION_KEYS))
        self.assertEqual(result["decision"]["stage"], "fast")
        self.assertEqual(result["decision"]["protocol"], "fast.time.read")
        self.assertFalse(_RESERVED.intersection(result["decision"]))
        self.assertFalse(_RESERVED.intersection(result["info"]))

    def test_run_never_reads_real_user_state(self):
        from modules import brain_candidates, brain_context
        boom = AssertionError("gerçek kullanıcı durumu okunmamalı")
        with patch.object(brain_context, "_default_history_reader", side_effect=boom), \
             patch.object(brain_context, "_default_goal_reader", side_effect=boom), \
             patch.object(brain_candidates, "_default_file_reader", side_effect=boom), \
             patch.object(brain_candidates, "_cached_file_reader", side_effect=boom), \
             patch("modules.task_agents.recent", side_effect=boom):
            result = harness.run_scenario({"id": "t-dosya", "text": "rapor.pdf dosyasını aç"})
        self.assertEqual(result["info"]["failures"], [])

    def test_run_never_executes_core_handler_or_installs_guards(self):
        from modules import brain_entry, command_manager
        original = command_manager.engine_control
        result = harness.run_scenario({"id": "t-kapat", "text": "Jarvis kapat"})
        self.assertEqual(result["decision"]["handoff_path"], "existing_handler")
        self.assertIs(command_manager.engine_control, original)
        self.assertFalse(getattr(command_manager, "_brain_engine_control_guard_installed", False))
        self.assertIsNone(brain_entry.current())

    def test_setup_session_reaches_state_gate(self):
        result = harness.run_scenario({
            "id": "t-level", "text": "ses", "setup": {"session": {"pending_level": 70}},
        })
        self.assertEqual(result["decision"]["protocol"], "session.pending_level.select")
        self.assertEqual(result["info"]["selection"], "volume")

    def test_last_property_setup_reaches_active_context_with_owner_and_ttl_rules(self):
        def seen(setup):
            return harness.run_scenario({"id": "t-lp", "text": "70 yap", "setup": setup})["info"]["context_last_property"]
        self.assertEqual(seen({"session": {"last_property": "volume", "last_property_age_seconds": 30}}), "volume")
        self.assertIsNone(seen({}))
        self.assertIsNone(seen({"session": {"last_property": "volume", "last_property_age_seconds": 3600}}))
        self.assertIsNone(seen({"session": {"last_property": "sicaklik", "last_property_age_seconds": 5}}))
        self.assertIsNone(seen({"foreign_sessions": {"hasan": {"last_property": "volume", "last_property_age_seconds": 5}}}))

    def test_capture_is_deterministic_and_keeps_errors_per_scenario(self):
        pool = [{"id": "a", "text": "saat kaç"}, {"id": "b", "text": "notlarımı göster"}]
        first = harness.capture(pool)["results"]
        second = harness.capture(pool)["results"]
        self.assertEqual(first, second)

        def runner(scenario):
            if scenario["id"] == "b":
                raise RuntimeError("bozuk")
            return harness.run_scenario(scenario)
        broken = harness.capture(pool, runner=runner)["results"]
        self.assertIn("decision", broken["a"])
        self.assertTrue(broken["b"]["error"].startswith("RuntimeError"))


class CompareTests(unittest.TestCase):
    scenario = {"id": "s", "text": "70 yap", "expect": {"outcome": "action"}, "forbid": {"stage": ["fast"]}}

    def test_identical_decision_is_same(self):
        row = _result(outcome="chat", stage="understanding")
        self.assertEqual(harness.verdict(self.scenario, row, row)["verdict"], "same")

    def test_gaining_criterion_without_loss_is_better(self):
        base = _result(outcome="chat", stage="understanding")
        cur = _result(outcome="action", stage="understanding")
        row = harness.verdict(self.scenario, base, cur)
        self.assertEqual(row["verdict"], "better")
        self.assertEqual(row["gained"], ["expect:outcome"])

    def test_losing_any_criterion_is_regression_even_with_gain(self):
        base = _result(outcome="chat", stage="understanding")
        cur = _result(outcome="action", stage="fast")
        row = harness.verdict(self.scenario, base, cur)
        self.assertEqual(row["verdict"], "regression")
        self.assertEqual(row["lost"], ["forbid:stage"])

    def test_difference_without_criteria_needs_review(self):
        scenario = {"id": "s", "text": "x"}
        row = harness.verdict(scenario, _result(outcome="chat"), _result(outcome="action"))
        self.assertEqual(row["verdict"], "changed")
        self.assertEqual(row["diff"]["outcome"], {"baseline": "chat", "current": "action"})

    def test_errors_new_and_missing(self):
        self.assertEqual(harness.verdict(self.scenario, _result(), {"error": "X: y"})["verdict"], "error")
        self.assertEqual(harness.verdict(self.scenario, {"error": "X: y"}, {"error": "X: y"})["verdict"], "same")
        self.assertEqual(harness.verdict(self.scenario, None, _result())["verdict"], "new")

    def test_gate_fails_on_changed_unless_accepted_and_on_missing(self):
        pool = [{"id": "a", "text": "x"}]
        baseline = {"results": {"a": _result(outcome="chat"), "gone": _result()}}
        current = {"results": {"a": _result(outcome="action")}}
        report = harness.compare(pool, baseline, current)
        self.assertFalse(report["passed"])
        self.assertEqual(report["failing"], ["a", "gone"])
        report = harness.compare(pool, {"results": {"a": _result(outcome="chat")}}, current, {"a": "bilinçli"})
        self.assertTrue(report["passed"])
        self.assertEqual(report["rows"]["a"]["verdict"], "accepted")

    def test_expectation_counts_track_improvement(self):
        pool = [self.scenario]
        report = harness.compare(
            pool,
            {"results": {"s": _result(outcome="chat", stage="understanding")}},
            {"results": {"s": _result(outcome="action", stage="understanding")}},
        )
        self.assertTrue(report["passed"])
        self.assertEqual(report["expectations_met"], {"baseline": 0, "current": 1, "with_criteria": 1})


class MatrixImportTests(unittest.TestCase):
    audit = (
        "# 12. ADVERSARIAL\n\n## C — BRAIN / ROUTING — 31–32\n\n"
        "| # | Senaryo | Beklenen | Eşleme |\n|---:|---|---|---|\n"
        "| 31 | “merhaba” | router semantic model yok | PR6/7 |\n"
        "| 32 | exact state reply | PR6 gate | PR6 |\n\n"
        "## D — CANDIDATE — 41–42\n\n| # | Senaryo | Beklenen |\n|---:|---|---|\n"
        "| 41 | default context build | history max12 |\n| 42 | history_limit=0 | reject |\n\n"
        "Eşleme: Brain PR7/Faz5.\n\n# 13. SONRAKİ\n| 99 | dışarıda | x |\n"
    )
    pr10 = (
        "# FINAL MATRIX\n### Fast Gate — 67–68\n67. exact sleep.\n68. wake only when sleeping.\n"
        "\n# CUTOVER\n1. bu liste dışı.\n"
    )

    def test_audit_table_keeps_text_and_section_mapping_verbatim(self):
        rows = harness.parse_audit_matrix(self.audit)
        self.assertEqual([r["no"] for r in rows], [31, 32, 41, 42])
        self.assertEqual(rows[0], {"no": 31, "kategori": "C — BRAIN / ROUTING", "senaryo": "“merhaba”",
                                   "beklenen": "router semantic model yok", "esleme": "PR6/7"})
        self.assertEqual(rows[3]["esleme"], "Brain PR7/Faz5")

    def test_pr10_numbered_list_only_reads_items_inside_section_range(self):
        rows = harness.parse_numbered_matrix(self.pr10)
        self.assertEqual(rows, [
            {"no": 67, "kategori": "Fast Gate", "senaryo": "exact sleep."},
            {"no": 68, "kategori": "Fast Gate", "senaryo": "wake only when sleeping."},
        ])

    def test_reimport_preserves_manual_instantiation(self):
        existing = {"senaryolar": [{"no": 67, "senaryo": "eski", "girdi": "uyu",
                                    "expect": {"protocol": "fast.engine.sleep"}, "katman": "brain_harness"}]}
        merged = harness.merge_matrix(harness.parse_numbered_matrix(self.pr10), existing, kind="pr10")
        first = merged["senaryolar"][0]
        self.assertEqual(first["senaryo"], "exact sleep.")
        self.assertEqual(first["girdi"], "uyu")
        self.assertNotIn("girdi", merged["senaryolar"][1])

    def test_only_rows_with_input_run_in_brain_harness(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.json"
            source = Path(tmp) / "pr10.txt"
            source.write_text(self.pr10, encoding="utf-8")
            path.write_text(json.dumps({"senaryolar": [
                {"no": 67, "senaryo": "exact sleep.", "girdi": "uyu", "expect": {"protocol": "fast.engine.sleep"}},
            ]}), encoding="utf-8")
            self.assertEqual(harness.main(["import", str(source), "--format", "pr10", "--out", str(path)]), 0)
            runnable, outside = harness.matrix_scenarios(path, "p10-")
        self.assertEqual([r["id"] for r in runnable], ["p10-067"])
        self.assertEqual([r["no"] for r in outside], [68])
        result = harness.run_scenario(runnable[0])
        self.assertTrue(all(harness.criteria_status(runnable[0], result["decision"]).values()))

    def test_committed_matrices_have_all_160_rows_and_valid_instances(self):
        for path, prefix in harness.MATRICES.items():
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual([r["no"] for r in data["senaryolar"]], list(range(1, 161)), path.name)
            for row in data["senaryolar"]:
                self.assertTrue(row.get("senaryo"))
            runnable, _ = harness.matrix_scenarios(path, prefix)
            for scenario in runnable:
                harness._validate_scenario(scenario)


class BaselineFileTests(unittest.TestCase):
    def test_committed_baseline_is_well_formed(self):
        data = json.loads(harness.DEFAULT_BASELINE.read_text(encoding="utf-8"))
        self.assertEqual(data["format_version"], harness.FORMAT_VERSION)
        self.assertEqual(data["scenario_count"], len(data["results"]))
        for row in data["results"].values():
            self.assertTrue("decision" in row or "error" in row)

    def test_default_compare_passes_without_arguments(self):
        """The canonical gate: argümansız `compare` current main'de GEÇTİ demeli (accept dosyası yok)."""
        pool = harness.load_pool()
        baseline = json.loads(harness.DEFAULT_BASELINE.read_text(encoding="utf-8"))
        report = harness.compare(pool, baseline, harness.capture(pool))
        self.assertTrue(report["passed"], report["counts"])
        self.assertEqual(report["counts"], {"same": len(pool)})

    def test_baseline_writer_roundtrips(self):
        data = harness.capture([{"id": "a", "text": "saat kaç"}])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "b.json"
            harness._write_baseline(path, data)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), data)


class VerdictEdgeTests(unittest.TestCase):
    """Reviewer-added: list-valued criteria, baseline-error recovery, unmet-criteria accounting."""

    def test_list_valued_criteria_gain_and_regress(self):
        scenario = {"id": "s", "text": "x", "forbid": {"protocol": ["a", "b"]}, "expect": {"stage": ["state", "fast"]}}
        worse = _result(protocol="a", stage="understanding")
        better = _result(protocol=None, stage="fast")
        up = harness.verdict(scenario, worse, better)
        self.assertEqual((up["verdict"], sorted(up["gained"])), ("better", ["expect:stage", "forbid:protocol"]))
        self.assertEqual(harness.verdict(scenario, better, worse)["verdict"], "regression")

    def test_baseline_error_then_decision_needs_review_not_silent_pass(self):
        row = harness.verdict({"id": "s", "text": "x"}, {"error": "X: y"}, _result(outcome="chat"))
        self.assertEqual(row["verdict"], "changed")

    def test_missing_decision_fails_every_criterion(self):
        scenario = {"id": "s", "text": "x", "expect": {"outcome": "chat"}, "forbid": {"stage": ["fast"]}}
        self.assertEqual(harness.criteria_status(scenario, None), {"expect:outcome": False, "forbid:stage": False})

    def test_unmet_expectation_is_not_counted_as_met(self):
        pool = [{"id": "a", "text": "70 yap", "expect": {"outcome": "action"}}]
        res = {"results": {"a": _result(outcome="chat")}}
        report = harness.compare(pool, res, res)
        self.assertEqual(report["expectations_met"], {"baseline": 0, "current": 0, "with_criteria": 1})
        self.assertTrue(report["passed"])

    def test_foreign_owner_property_not_visible_to_main_owner(self):
        from modules import session_state
        runtime = harness._runtime(
            {"foreign_sessions": {"hasan": {"last_property": "volume", "last_property_age_seconds": 30}}}, "hamdi")
        self.assertIsNone(session_state.fresh_property(runtime._session()))
        self.assertEqual(session_state.fresh_property(runtime._sessions._states["hasan"]), "volume")


if __name__ == "__main__":
    unittest.main()
