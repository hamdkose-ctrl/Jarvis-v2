import unittest
from unittest.mock import Mock, patch


class TypedUiCommandsTests(unittest.TestCase):
    def test_theme_is_persisted_and_updates_desktop(self):
        from modules import selfctl, nxapi
        emit = Mock()
        with patch.object(nxapi, "ui_set") as update:
            selfctl.execute({"kind": "ui", "key": "nx_theme", "value": "dark"}, emit)
        update.assert_called_once_with("nx_theme", "dark")
        emit.assert_called_once_with("action", "nx_set")

    def test_retired_view_is_absent_from_the_model_and_adapter(self):
        from modules import selfctl, brain_core_map
        for key in ("hologram_tone", "hologram_background", "replay", "home_animation"):
            emit = Mock()
            action = {"kind": "ui", "key": key, "value": True}
            self.assertIsNone(brain_core_map.core_plan("jarvis.selfctl", {"action": action}))
            self.assertIn("doğrulanmadı", selfctl.execute(action, emit))
            emit.assert_not_called()

    def test_unknown_action_is_not_an_implicit_text_fallback(self):
        from modules import selfctl
        emit = Mock()
        reply = selfctl.execute({"kind": "ui", "key": "sentence", "value": "hologramı sarı yap"}, emit)
        self.assertIn("doğrulanmadı", reply)
        emit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
