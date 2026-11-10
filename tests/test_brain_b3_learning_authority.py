"""BRAIN-03 dilim6: typed learning and bounded State selection regressions (no live model)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import brain_core_map, brain_entry, brain_model_understanding, learning
from modules.personalization import Profile


class LearningAuthorityTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.profile = Profile.__new__(Profile)
        self.profile.slug = "alice"
        self.profile.path = Path(tmp.name) / "user.json"
        self.profile.data = {"name": "Alice", "prefs": {}, "facts": [], "rules": [],
                             "items": [], "goals": [], "pending_facts": []}

    def test_model_cannot_request_bulk_pending_approval(self):
        self.assertIsNone(brain_core_map.core_plan(
            "learning.manage", {"operation": "pending.approve"}))
        self.assertIsNone(brain_core_map.core_plan(
            "learning.manage", {"operation": "pending.reject", "index": None}))
        self.assertIsNone(brain_core_map.core_plan(
            "learning.manage", {"operation": "pending.approve", "_state_selection": "approve:all"}))
        self.assertEqual(brain_core_map.core_plan(
            "learning.manage", {"operation": "pending.approve", "index": 1})[0],
            "learning_manage")

    def test_model_index_must_be_grounded_to_user_text(self):
        supplied = {"operation": "pending.reject", "index": 2}
        check = brain_model_understanding._arguments_are_grounded
        self.assertTrue(check(capability_id="learning.manage", supplied=supplied,
                              sources={"index": "2"}, text="öğrendiğin 2. bilgiyi sil"))
        self.assertFalse(check(capability_id="learning.manage", supplied=supplied,
                               sources={"index": "3"}, text="öğrendiğin 3. bilgiyi sil"))
        self.assertFalse(check(capability_id="learning.manage", supplied=supplied,
                               sources=None, text="öğrendiklerinin hepsini sil"))

    def test_fact_edit_and_forget_require_exact_old_text(self):
        self.profile.add_fact("A17 sensörü X200")
        self.profile.add_fact("B18 sensörü X500")
        reply = learning.execute_typed(self.profile, {
            "operation": "fact.edit", "old": "A17 sensörü X200", "text": "A17 sensörü X300"})
        self.assertIn("düzelttim", reply)
        self.assertEqual(self.profile.data["facts"], ["A17 sensörü X300", "B18 sensörü X500"])
        reply = learning.execute_typed(self.profile, {"operation": "fact.forget", "old": "X300"})
        self.assertIn("Kesin ve tek", reply)
        self.assertEqual(len(self.profile.data["facts"]), 2)
        learning.execute_typed(self.profile, {"operation": "fact.forget", "old": "A17 sensörü X300"})
        self.assertEqual(self.profile.data["facts"], ["B18 sensörü X500"])

    def test_state_all_uses_exact_selection_and_snapshot(self):
        self.profile.data["pending_facts"] = ["aday A", "aday B"]
        plan = brain_core_map.state_plan("learning.pending_facts.select",
                                         "approve:all", None, ["aday A", "aday B"])
        self.assertIsNotNone(plan)
        with patch.object(brain_entry, "matched_protocol", return_value=True), \
                patch.object(brain_entry, "protocol_selection", return_value="approve:all"):
            text = learning.execute_typed(self.profile, plan[1])
        self.assertIn("2 bilgiyi", text)
        self.assertEqual(self.profile.data["facts"], ["aday A", "aday B"])
        self.assertEqual(self.profile.data["pending_facts"], [])

    def test_stale_state_selection_mutates_nothing(self):
        self.profile.data["pending_facts"] = ["aday A", "aday B"]
        plan = brain_core_map.state_plan("learning.pending_facts.select",
                                         "reject:1", None, ["aday A", "aday B"])
        self.profile.data["pending_facts"].append("aday C")
        with patch.object(brain_entry, "matched_protocol", return_value=True), \
                patch.object(brain_entry, "protocol_selection", return_value="reject:1"):
            text = learning.execute_typed(self.profile, plan[1])
        self.assertIn("learning_pending_stale", text)
        self.assertEqual(self.profile.data["pending_facts"], ["aday A", "aday B", "aday C"])

    def test_state_bulk_without_matching_protocol_is_rejected(self):
        self.profile.data["pending_facts"] = ["aday A", "aday B"]
        plan = brain_core_map.state_plan("learning.pending_facts.select",
                                         "reject:all", None, ["aday A", "aday B"])
        with patch.object(brain_entry, "matched_protocol", return_value=False):
            text = learning.execute_typed(self.profile, plan[1])
        self.assertIn("geçerli değil", text)
        self.assertEqual(self.profile.data["pending_facts"], ["aday A", "aday B"])


if __name__ == "__main__":
    unittest.main()
