"""BRAIN-03 slice 7: model proposal -> Core shape -> single typed executor."""
from __future__ import annotations
from provider_fixture import routed_response
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import brain_core_map, user_command_domain
import test_brain_pr3_raw_text_authority as harness
from test_brain_b3_message_and_contacts_authority import _envelope
from test_brain_primary_understanding import eligible


class UserAndMacroCoreTests(unittest.TestCase):
    def test_core_rejects_unknown_operations_and_unbounded_macro_shape(self):
        self.assertIsNone(brain_core_map.core_plan("user.manage", {"operation": "guess"}))
        self.assertIsNone(brain_core_map.core_plan("macro.teach", {"trigger": "x", "actions": []}))
        self.assertIsNone(brain_core_map.core_plan("macro.manage", {"operation": "delete"}))
        self.assertIsNone(brain_core_map.core_plan("user.manage", {"operation": []}))
        self.assertIsNone(brain_core_map.core_plan("macro.manage", {"operation": []}))

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

    def test_active_user_alias_cannot_delete_own_profile(self):
        runtime = SimpleNamespace(profile=SimpleNamespace(name="Şeyma", slug="seyma"),
                                  slugify=lambda name: "seyma", delete_user=Mock())
        self.assertIn("Aktif kullanıcıyı silemem", user_command_domain.user_manage(
            runtime, {"operation": "delete", "name": "Seyma"}))
        runtime.delete_user.assert_not_called()

    def test_same_slug_rename_does_not_delete_api_key(self):
        runtime = SimpleNamespace(profile=SimpleNamespace(name="Şeyma", slug="seyma"),
                                  slugify=lambda name: "seyma", rename_user=Mock(return_value=None),
                                  _llm=Mock(), _profiles={}, _get_profile=Mock(), _sessions=Mock())
        runtime._llm.user_key.return_value = "secret"
        user_command_domain.user_manage(runtime, {"operation": "rename", "name": "Seyma"})
        runtime._llm.set_user_key.assert_not_called()


class UserAndMacroProductionTests(harness._CanonicalAuthorityHarness):
    def _model_turn(self, text, capability, arguments, sources):
        raw = _envelope(capability, arguments, sources)
        p1, p2, p3, p4 = eligible()
        with p1, p2, p3, p4, patch("modules.llm.current_user", return_value=self.owner), \
                routed_response(raw):
            return self.turn_real(text, model_understanding=True)

    def test_model_macro_steps_reach_owner_store(self):
        entry, out, _, feedback = self._model_turn(
            "çalışma modu dersem chrome aç", "macro.teach",
            {"trigger": "çalışma modu", "actions": ["chrome aç"]}, {"trigger": "çalışma modu"})
        self.assertEqual(self.ctx.profile.data.get("macros", {}).get("çalışma modu", {}).get("actions"), ["chrome aç"], (entry.understanding, out))
        self.assertEqual(feedback.result_status, "handled")

    def test_invented_macro_step_is_rejected_before_storage(self):
        entry, _, _, _ = self._model_turn(
            "çalışma modu dersem chrome aç", "macro.teach",
            {"trigger": "çalışma modu", "actions": ["dosyaları sil"]}, {"trigger": "çalışma modu"})
        self.assertNotEqual(entry.understanding.capability_hint, "macro.teach")
        self.assertFalse(self.ctx.profile.data.get("macros"))

    def test_model_goal_goes_to_active_profile(self):
        entry, out, _, feedback = self._model_turn(
            "hedefim İngilizce çalışmak", "user.manage",
            {"operation": "goal_add", "text": "İngilizce çalışmak"}, {"text": "İngilizce çalışmak"})
        self.assertIn("İngilizce çalışmak", self.ctx.profile.data["goals"])
        self.assertEqual(feedback.result_status, "handled")

    def test_model_delete_targets_only_current_users_macro_store(self):
        other = self.ctx._get_profile("Other")
        other.data["macros"] = {"çalışma modu": {"title": "çalışma modu", "actions": ["chrome aç"]}}
        self.ctx.profile.data["macros"] = {"çalışma modu": {"title": "çalışma modu", "actions": ["chrome aç"]}}
        _, _, _, feedback = self._model_turn("çalışma modu kısayolunu sil", "macro.manage",
                                              {"operation": "delete", "trigger": "çalışma modu"},
                                              {"trigger": "çalışma modu"})
        self.assertEqual(self.ctx.profile.data["macros"], {})
        self.assertIn("çalışma modu", other.data["macros"])
        self.assertEqual(feedback.result_status, "handled")


if __name__ == "__main__":
    unittest.main()
