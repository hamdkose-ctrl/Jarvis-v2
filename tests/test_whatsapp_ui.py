"""WhatsApp arayüz araması: kişi seçmez, onaysız mesaj göndermez."""
import sys
import types
import unittest
from unittest import mock

from modules import whatsapp_ui


def _win32gui():
    fake = types.SimpleNamespace()
    fake.EnumWindows = lambda visit, param: (
        visit(11, None),                      # WhatsApp penceresi
        visit(12, None),                      # ilgisiz pencere
    )
    fake.GetWindowText = lambda handle: "WhatsApp" if handle == 11 else "Not Defteri"
    fake.GetClassName = lambda handle: "WinUIDesktopWin32WindowClass" if handle == 11 else "Notepad"
    fake.IsWindowVisible = lambda handle: handle == 11
    fake.ShowWindow = lambda handle, how: None
    fake.SetForegroundWindow = lambda handle: 1
    return fake


class Window(unittest.TestCase):
    def test_finds_whatsapp_window(self):
        with mock.patch.dict(sys.modules, {"win32gui": _win32gui()}):
            self.assertEqual(whatsapp_ui.window(), {"handle": 11, "title": "WhatsApp"})

    def test_missing_window_is_reported(self):
        fake = _win32gui()
        fake.GetWindowText = lambda handle: "Not Defteri"
        fake.GetClassName = lambda handle: "Notepad"
        with mock.patch.dict(sys.modules, {"win32gui": fake}):
            self.assertIsNone(whatsapp_ui.window())
            self.assertEqual(whatsapp_ui.show()["status"], "no_window")


class Safety(unittest.TestCase):
    def test_send_without_confirm_only_asks(self):
        result = whatsapp_ui.send_text("merhaba")
        self.assertEqual(result["status"], "needs_confirm")
        self.assertIn("Onay", result["text"])

    def test_empty_query_is_refused(self):
        self.assertEqual(whatsapp_ui.open_search("  ")["status"], "empty")

    def test_empty_message_is_refused(self):
        self.assertEqual(whatsapp_ui.send_text("", confirm=True)["status"], "empty")


class Search(unittest.TestCase):
    def test_search_types_name_but_sends_nothing(self):
        gui = mock.MagicMock()
        pressed = []
        gui.hotkey = lambda *keys: pressed.append(keys)
        gui.press = lambda key: pressed.append((key,))
        with mock.patch.dict(sys.modules, {"win32gui": _win32gui(),
                                           "pyautogui": gui}), \
             mock.patch.object(whatsapp_ui, "show", return_value={"status": "done", "text": ""}), \
             mock.patch.object(whatsapp_ui.time, "sleep", lambda *_: None), \
             mock.patch("modules.pc_hands.write_clipboard", lambda text: True):
            result = whatsapp_ui.open_search("bitanem")
        self.assertEqual(result["status"], "done")
        self.assertNotIn(("enter",), pressed)          # gönderme yok


class Wiring(unittest.TestCase):
    """Rehberde numara yoksa WhatsApp arayüzünde aranır; onay iki adımlı."""

    def test_missing_phone_searches_whatsapp_instead_of_giving_up(self):
        from modules import messaging
        with mock.patch.object(whatsapp_ui, "open_search", return_value={"status": "done"}) as search,              mock.patch.object(whatsapp_ui, "remember_pending") as remember:
            answer = messaging.send_whatsapp("bitanem", "merhaba")
        self.assertTrue(search.called)
        self.assertTrue(remember.called)
        self.assertIn("gönder", answer)

    def test_confirm_command_is_recognised(self):
        from modules import fast_commands
        for phrase in ("gönder", "onaylıyorum"):
            self.assertEqual(fast_commands.resolve(phrase), ("whatsapp_send", {}))

    def test_other_commands_are_not_hijacked(self):
        from modules import fast_commands
        self.assertNotEqual(fast_commands.resolve("youtube aç"), ("whatsapp_send", {}))

    def test_pending_round_trip_and_send_needs_confirm(self):
        whatsapp_ui.remember_pending("bitanem", "merhaba")
        try:
            self.assertEqual(whatsapp_ui.pending()["text"], "merhaba")
            self.assertEqual(whatsapp_ui.send_pending()["status"], "needs_confirm")
        finally:
            whatsapp_ui.clear_pending()
        self.assertIsNone(whatsapp_ui.pending())


if __name__ == "__main__":
    unittest.main()
