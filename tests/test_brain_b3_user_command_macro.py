"""BRAIN-03 slice 7: model proposal -> Core shape -> single typed executor."""
from __future__ import annotations
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from modules import brain_core_map, user_command_domain


class UserAndMacroCoreTests(unittest.TestCase):
    def test_core_rejects_unknown_operations_and_unbounded_macro_shape(self):
        self.assertIsNone(brain_core_map.core_plan("user.manage", {"operation": "guess"}))
        self.assertIsNone(brain_core_map.core_plan("macro.teach", {"trigger": "x", "actions": []}))
        self.assertIsNone(brain_core_map.core_plan("macro.manage", {"operation": "delete"}))

    def test_user_goal_and_macro_are_written_only_from_typed_arguments(self):
        profile = SimpleNamespace(name="Ada", data={"goals": [], "macros": {}}, add_goal=Mock(), save=Mock())
        runtime = SimpleNamespace(profile=profile, _macro_key=lambda text: text.casefold())
        plan = brain_core_map.core_plan("user.manage", {"operation": "goal_add", "text": "İngilizce çalışmak"})
        self.assertEqual(plan, ("user_manage", {"operation": "goal_add", "text": "İngilizce çalışmak"}))
        self.assertIn("hedefini kaydettim", user_command_domain.user_manage(runtime, plan[1]))
        profile.add_goal.assert_called_once_with("İngilizce çalışmak")
        macro = brain_core_map.core_plan("macro.teach", {"trigger": "çalışma modu", "actions": ["chrome aç"]})
        self.assertEqual(macro, ("macro_teach", {"trigger": "çalışma modu", "actions": ["chrome aç"]}))
        self.assertIn("Kısayolu kaydettim", user_command_domain.macro_teach(runtime, macro[1]))
        self.assertEqual(profile.data["macros"]["çalışma modu"]["actions"], ["chrome aç"])


if __name__ == "__main__":
    unittest.main()
