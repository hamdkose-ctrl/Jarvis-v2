import unittest
from unittest.mock import Mock, patch


class TypedUiCommandsTests(unittest.TestCase):
    def test_typed_ui_actions_emit_only_allowlisted_events(self):
        from modules import selfctl
        cases = (
            ({"kind": "ui", "key": "hologram_tone", "value": "turquoise"}, "ui", "hologramtone|turquoise"),
            ({"kind": "ui", "key": "hologram_background", "value": "lava"}, "ui", "hologrambg|lava"),
            ({"kind": "ui", "key": "replay", "value": True}, "ui", "bustreplay|"),
            ({"kind": "ui", "key": "home_animation", "value": False}, "ui", "nxbust|0"),
        )
        for action, kind, payload in cases:
            with self.subTest(action=action):
                emit = Mock()
                selfctl.execute(action, emit)
                emit.assert_called_once_with(kind, payload)

    def test_typed_ui_does_not_write_settings(self):
        from modules import selfctl
        with patch.object(selfctl, "save_settings") as save:
            selfctl.execute({"kind": "ui", "key": "hologram_tone", "value": "yellow"}, Mock())
        save.assert_not_called()

    def test_unknown_action_is_not_an_implicit_text_fallback(self):
        from modules import selfctl
        emit = Mock()
        reply = selfctl.execute({"kind": "ui", "key": "sentence", "value": "hologramı sarı yap"}, emit)
        self.assertIn("doğrulanmadı", reply)
        emit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
