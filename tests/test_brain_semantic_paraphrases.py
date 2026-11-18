"""Offline scoring checks for the existing live semantic holdout; no model or effects."""
from __future__ import annotations

from contextlib import nullcontext, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import brain_semantic_holdout as holdout


CORPUS = Path(__file__).resolve().parent / "data" / "brain_semantic_paraphrases.json"


def proposal(capability=None, arguments=None):
    if capability is None:
        return SimpleNamespace(operation="chat", actions=[])
    action = SimpleNamespace(capability_id=capability, arguments=dict(arguments or {}))
    return SimpleNamespace(operation="direct_action", actions=[action])


class ParaphraseScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = json.loads(CORPUS.read_text(encoding="utf-8"))["cumleler"]

    def test_each_group_is_coherent_and_has_multiple_sayings(self):
        holdout._validate_equivalence_corpus(self.rows)
        groups = {}
        for row in self.rows:
            if row.get("equivalence_group"):
                groups.setdefault(row["equivalence_group"], []).append(row)
        self.assertGreaterEqual(len(groups), 5)
        self.assertTrue(all(len(rows) >= 3 for rows in groups.values()))
        self.assertGreaterEqual(sum(row["beklenen"]["kind"] == "no_effect" for row in self.rows), 8)

    def test_unowned_source_annotations_are_inert_and_user_fields_stay_grounded(self):
        # For typed-only capabilities, auxiliary source annotations are
        # nonauthoritative and discarded: the published wire schema permits
        # null or any JSON object. The Core still validates typed arguments.
        from modules import brain_model_understanding as brain
        check = brain._arguments_are_grounded
        args = {"property": "volume", "level": 20}
        self.assertTrue(check(capability_id="pc.level.set", supplied=args,
                              sources=None, text="Sesi yüzde 20 yap."))
        self.assertTrue(check(capability_id="pc.level.set", supplied=args,
                              sources={}, text="Sesi yüzde 20 yap."))
        for source in ({"level": "yüzde 20"}, {"property": "sesi", "level": 20},
                       {"approval": "fabricated"}, {"misc": {"ignored": True}}):
            with self.subTest(source=source):
                self.assertTrue(check(capability_id="pc.level.set", supplied=args,
                                      sources=source, text="Sesi yüzde 20 yap."))
        for source in ([], "20", 20, True):
            with self.subTest(invalid_shape=source):
                self.assertFalse(check(capability_id="pc.level.set", supplied=args,
                                       sources=source, text="Sesi yüzde 20 yap."))
        # With user-owned fields, a source-less populated message remains
        # prohibited even if an empty JSON object is otherwise well formed.
        for source in (None, {}):
            self.assertFalse(check(capability_id="message.send",
                                   supplied={"recipient": "Ayşe", "body": "Merhaba"},
                                   sources=source, text="Ayşe'ye Merhaba yaz."))
        self.assertFalse(check(capability_id="message.send",
                               supplied={"recipient": "Ayşe", "body": "Merhaba"},
                               sources={"recipient": "Ayşe", "body": "Yanlış"},
                               text="Ayşe'ye Merhaba yaz."))

    def test_number_must_be_present_and_an_integer(self):
        row = self.rows[0]
        expected = {"property": "volume", "level": 20}
        for fields, correct in ((expected, True),
                                ({"property": "volume"}, False),
                                ({"property": "volume", "level": "20"}, False),
                                ({"property": "volume", "level": 0}, False),
                                ({"property": "brightness", "level": 20}, False)):
            result = holdout._judge(row, proposal("pc.level.set", fields), None)
            self.assertEqual(result["target_ok"], correct)

    def test_missing_proposal_is_not_successful_no_effect(self):
        row = next(row for row in self.rows if row["id"] == "neg-volume_not")
        self.assertFalse(holdout._judge(row, None, None)["intent_ok"])
        unexpected_envelope = proposal()
        unexpected_envelope.operation = "direct_action"
        self.assertFalse(holdout._judge(row, unexpected_envelope, None)["intent_ok"])

    def test_action_on_negation_is_critical_even_for_pc_or_apps(self):
        row = next(row for row in self.rows if row["id"] == "neg-volume_not")
        result = holdout._judge(row, proposal("pc.level.set",
                                              {"property": "volume", "level": 20}), None)
        self.assertFalse(result["intent_ok"])
        self.assertTrue(result["yanlis_etki"])
        self.assertEqual(holdout._aggregate([result])["kritik_yanlis_etki"], 1)

    def test_second_action_cannot_hide_behind_a_correct_first_action(self):
        row = self.rows[0]
        first = SimpleNamespace(capability_id="pc.level.set",
                                arguments={"property": "volume", "level": 20})
        second = SimpleNamespace(capability_id="app.open", arguments={"app": "chrome"})
        combined = SimpleNamespace(operation="action_batch", actions=[first, second])
        result = holdout._judge(row, combined, None)
        self.assertFalse(result["intent_ok"])
        self.assertEqual(result["action_count"], 2)
        self.assertTrue(result["yanlis_etki"])
        self.assertEqual(holdout._aggregate([result])["kritik_yanlis_etki"], 1)

    def test_wrong_capability_target_or_operation_is_critical(self):
        row = self.rows[0]
        wrong_operation = proposal("pc.level.set", {"property": "volume", "level": 20})
        wrong_operation.operation = "chat"
        variants = (
            proposal("app.open", {"app": "chrome"}),
            proposal("pc.level.set", {"property": "volume", "level": 19}),
            proposal("pc.level.set", {"property": "brightness", "level": 20}),
            wrong_operation,
        )
        for candidate in variants:
            with self.subTest(candidate=(candidate.operation,
                                         candidate.actions[0].capability_id,
                                         candidate.actions[0].arguments)):
                result = holdout._judge(row, candidate, None)
                self.assertFalse(result["intent_ok"] and result["target_ok"])
                self.assertTrue(result["yanlis_etki"])
                self.assertEqual(holdout._aggregate([result])["kritik_yanlis_etki"], 1)

    def test_one_bad_paraphrase_fails_its_whole_group(self):
        sample = [next(row for row in self.rows if row["equivalence_group"] == "volume20") for _ in range(20)]
        good = holdout._judge(sample[0], proposal("pc.level.set",
                                                    {"property": "volume", "level": 20}), None)
        bad = holdout._judge(sample[0], proposal("pc.level.set",
                                                   {"property": "volume", "level": 19}), None)
        report = holdout._aggregate([good] * 19 + [bad])
        self.assertEqual(report["hedef_dogrulugu"], .95)
        self.assertFalse(report["equivalence"]["passed"])
        self.assertEqual(report["kritik_yanlis_etki"], 1)
        self.assertIn(sample[0]["id"], report["equivalence"]["groups"]["volume20"]["failed"])

    def test_original_semantic_corpus_still_works_without_groups(self):
        rows = json.loads(holdout.CORPUS.read_text(encoding="utf-8"))["cumleler"]
        holdout._validate_equivalence_corpus(rows)
        self.assertEqual(holdout._equivalence([]), {"groups": {}, "passed": True})

    def test_simulated_scoring_without_actual_provider_responses_is_unmeasured(self):
        """A fake _ask cannot produce a live acceptance PASS or 8 false negative wins."""
        def fake_ask(owner, text, index):
            row = self.rows[index - 1]
            expected = row["beklenen"]
            if expected["kind"] == "no_effect":
                return proposal(), None
            return proposal(expected["capability"], expected["slotlar"]), None

        fake_candidate = SimpleNamespace(provider="groq", model="test-model", connection_id=None)
        with TemporaryDirectory() as folder:
            output = Path(folder) / "report.json"
            with patch.object(holdout, "_preflight", return_value=("test", True, "hazır")), \
                 patch.object(holdout, "_instrument_effects", return_value={"send_whatsapp": 0, "dispatch": 0}), \
                 patch("modules.smart_router.qualification_candidate", return_value=fake_candidate), \
                 patch("modules.smart_router.qualification_session", return_value=nullcontext()), \
                 patch.object(holdout, "_ask", side_effect=fake_ask) as ask, \
                 patch.object(holdout, "_sleep"), \
                 redirect_stdout(StringIO()):
                code = holdout.main(["--run", "--corpus", str(CORPUS), "--json", str(output)])
            self.assertEqual(code, 2)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["state"], "unmeasured")
            self.assertIsNone(report["summary"]["niyet_dogrulugu"])
            self.assertFalse(report["summary"]["equivalence"]["passed"])
            self.assertEqual(report["summary"]["provider_responses"], 0)
            self.assertEqual(report["summary"]["completed_cases"], 0)
            self.assertEqual(len(report["results"]), 1)
            ask.assert_called_once()

    def test_source_shape_diagnostics_never_publish_quotes_or_values(self):
        private = "never-expose-this-secret-value"
        cases = (
            ({"capability_id": "pc.level.set", "argument_sources": None},
             {"capability": "pc.level.set", "source_type": "null"}),
            ({"capability_id": "pc.level.set", "argument_sources": {}},
             {"capability": "pc.level.set", "source_type": "empty_object"}),
            ({"capability_id": "message.send",
              "argument_sources": {"recipient": private}, "arguments": {"recipient": private}},
             {"capability": "message.send", "source_type": "nonempty_object"}),
        )
        raw = json.dumps({"actions": [case for case, _ in cases]})
        actual = holdout._model_source_shapes(raw)
        self.assertEqual(actual, [expect for _, expect in cases])
        self.assertNotIn(private, json.dumps(actual))
        self.assertEqual(holdout._model_source_shapes("not json"), [])
        self.assertEqual(holdout._model_source_shapes(json.dumps({"actions": "invalid"})), [])
        self.assertEqual(holdout._model_source_shapes(json.dumps({
            "actions": [{"capability_id": private, "argument_sources": private}]})),
            [{"capability": "unknown", "source_type": "wrong_type"}])

    def test_first_invalid_live_response_stops_without_spending_more_calls(self):
        """A provider reply rejected by the Brain contract is FAIL, not unmeasured."""
        from modules import llm
        candidate = SimpleNamespace(provider="gemini", model="fixture", connection_id=None)
        def rejected(owner, text, index):
            llm.dispatch()
            return None, None

        with TemporaryDirectory() as folder:
            output = Path(folder) / "report.json"
            with patch.object(holdout, "_preflight", return_value=("test", True, "hazır")), \
                 patch.object(holdout, "_instrument_effects", return_value={"send_whatsapp": 0, "dispatch": 0}), \
                 patch("modules.smart_router.qualification_candidate", return_value=candidate), \
                 patch("modules.smart_router.qualification_session", return_value=nullcontext()), \
                 patch.object(llm, "dispatch", return_value=SimpleNamespace(text="not-json")), \
                 patch.object(holdout, "_ask", side_effect=rejected) as ask, \
                 patch.object(holdout, "_sleep") as sleep, \
                 redirect_stdout(StringIO()):
                code = holdout.main(["--run", "--corpus", str(CORPUS), "--json", str(output)])
            self.assertEqual(code, 1)
            report = json.loads(output.read_text(encoding="utf-8"))
            summary = report["summary"]
            self.assertEqual(summary["state"], "failed")
            self.assertEqual(summary["stop_reason"], "model_response_invalid")
            self.assertEqual(summary["provider_requests"], 1)
            self.assertEqual(summary["provider_responses"], 1)
            self.assertEqual(summary["planned_cases"], 24)
            self.assertEqual(len(report["results"]), 1)
            self.assertEqual(report["results"][0]["response_shapes"], [{"json_object": False}])
            self.assertFalse(report["results"][0]["intent_ok"])
            ask.assert_called_once()
            sleep.assert_not_called()

    def test_mocked_transport_observation_and_qualification_scope(self):
        """Only fixture responses permit offline scoring; this is not real model evidence."""
        from modules import llm, smart_router
        fake_candidate = SimpleNamespace(provider="groq", model="test-model", connection_id=None)
        def fake_ask(owner, text, index):
            self.assertEqual(smart_router._ROLE_EVALUATION.get(),
                             (owner, "groq", "test-model", None))
            llm.dispatch()  # patched fixture transport, observed by the real runner
            row = self.rows[index - 1]
            expected = row["beklenen"]
            if expected["kind"] == "no_effect":
                return proposal(), None
            return proposal(expected["capability"], expected["slotlar"]), None

        with TemporaryDirectory() as folder:
            output = Path(folder) / "report.json"
            with patch.object(holdout, "_preflight", return_value=("test", True, "hazır")), \
                 patch.object(holdout, "_instrument_effects", return_value={"send_whatsapp": 0, "dispatch": 0}), \
                 patch("modules.smart_router.qualification_candidate", return_value=fake_candidate), \
                 patch.object(llm, "dispatch", return_value=SimpleNamespace(text="fixture")), \
                 patch.object(holdout, "_ask", side_effect=fake_ask), \
                 patch.object(holdout, "_sleep"), \
                 redirect_stdout(StringIO()):
                code = holdout.main(["--run", "--corpus", str(CORPUS), "--json", str(output)])
            self.assertEqual(code, 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["state"], "passed")
            self.assertTrue(report["summary"]["equivalence"]["passed"])
            self.assertEqual(report["summary"]["provider_responses"], len(self.rows))
            self.assertEqual(len(report["results"]), len(self.rows))
        self.assertIsNone(smart_router._ROLE_EVALUATION.get())

    def test_malformed_groups_rejected_before_preflight(self):
        with TemporaryDirectory() as folder:
            invalid = Path(folder) / "bad.json"
            invalid.write_text(json.dumps({"cumleler": [self.rows[0]]}), encoding="utf-8")
            with patch.object(holdout, "_preflight", side_effect=AssertionError("never call provider")), \
                 redirect_stdout(StringIO()):
                self.assertEqual(holdout.main(["--run", "--corpus", str(invalid)]), 2)


if __name__ == "__main__":
    unittest.main()
