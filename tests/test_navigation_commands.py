import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


class TypedNavigationCommandsTests(unittest.TestCase):
    def test_windows_page_is_closed_typed_adapter(self):
        from modules import system_control
        windows_os = SimpleNamespace(**vars(system_control.os)); windows_os.name = "nt"; windows_os.startfile = Mock()
        with patch.object(system_control, "os", windows_os), patch.object(system_control, "_visible_application", return_value=1), patch.object(system_control, "_permission_decision"):
            reply = system_control.open_windows_settings("network-wifi")
        windows_os.startfile.assert_called_once_with("ms-settings:network-wifi")
        self.assertTrue(reply.ok)

    def test_windows_adapter_rejects_unknown_page_without_launch(self):
        from modules import system_control
        with patch.object(system_control.os, "startfile", create=True) as start:
            reply = system_control.open_windows_settings("not-a-page")
        start.assert_not_called()
        self.assertFalse(reply.ok)

    def test_windows_adapter_does_not_claim_success_without_window(self):
        from modules import system_control
        clock = iter([0, 0, 11, 11])
        windows_os = SimpleNamespace(**vars(system_control.os)); windows_os.name = "nt"; windows_os.startfile = Mock()
        with patch.object(system_control, "os", windows_os), patch.object(system_control, "_visible_application", return_value=None), patch.object(system_control, "_permission_decision"), patch.object(system_control.time, "monotonic", side_effect=lambda: next(clock)), patch.object(system_control.time, "sleep"):
            reply = system_control.open_windows_settings("network-wifi")
        self.assertFalse(reply.ok)
        self.assertIn("Açıldı demiyorum", reply)

    def test_selfctl_navigation_only_accepts_typed_page(self):
        from modules import selfctl
        emit = Mock()
        self.assertIn("Notlar", selfctl.execute({"kind": "navigate", "page": "notes"}, emit))
        emit.assert_called_once_with("nav", "tools|takvim")
        self.assertIn("doğrulanmadı", selfctl.execute({"kind": "navigate", "page": "raw text"}, Mock()))


if __name__ == "__main__":
    unittest.main()
