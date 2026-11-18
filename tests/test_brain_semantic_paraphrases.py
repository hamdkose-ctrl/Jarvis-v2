"""Offline scoring checks for the existing live semantic holdout; no model or effects."""
from __future__ import annotations

from contextlib import redirect_stdout
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

    def test_full_corpus_scoring_with_simulated_provider_never_counts_as_live(self):
        """Exercise the real CLI/scorer, but fake only the provider; not a product PASS."""
        def fake_ask(owner, text, index):
            row = self.rows[index - 1]
            expected = row["beklenen"]
            if expected["kind"] == "no_effect":
                return proposal(), None
            return proposal(expected["capability"], expected["slotlar"]), None
        with TemporaryDirectory() as folder:
            output = Path(folder) / "report.json"
            with patch.object(holdout, "_preflight", return_value=("test", True, "hazır")), \
                 patch.object(holdout, "_instrument_effects", return_value={"send_whatsapp": 0, "dispatch": 0}), \
                 patch.object(holdout, "_ask", side_effect=fake_ask), \
                 redirect_stdout(StringIO()):
                code = holdout.main(["--run", "--corpus", str(CORPUS), "--json", str(output)])
            self.assertEqual(code, 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(report["summary"]["equivalence"]["passed"])
            self.assertEqual(report["summary"]["kritik_yanlis_etki"], 0)
            self.assertEqual(len(report["results"]), len(self.rows))

    def test_malformed_groups_rejected_before_preflight(self):
        with TemporaryDirectory() as folder:
            invalid = Path(folder) / "bad.json"
            invalid.write_text(json.dumps({"cumleler": [self.rows[0]]}), encoding="utf-8")
            with patch.object(holdout, "_preflight", side_effect=AssertionError("never call provider")), \
                 redirect_stdout(StringIO()):
                self.assertEqual(holdout.main(["--run", "--corpus", str(invalid)]), 2)


if __name__ == "__main__":
    unittest.main()
