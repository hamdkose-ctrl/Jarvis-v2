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


class SearchQuery(unittest.TestCase):
    """Yeni sözleşme (T1): tam ad korunur; ek atması aday doğrulamasıyla yapılır."""

    def test_first_candidate_is_the_full_name(self):
        self.assertEqual(whatsapp_ui.search_query("bitaneme"), "bitaneme")
        self.assertEqual(whatsapp_ui.search_query("Fatma"), "fatma")
        self.assertEqual(whatsapp_ui.search_query("Mehmet Ali Yılmaz"), "mehmet ali yilmaz")

    def test_suffix_variant_exists_for_fallback(self):
        self.assertIn("bitanem", whatsapp_ui.search_variants("bitaneme"))
        self.assertIn("tanem", whatsapp_ui.search_variants("bir taneme"))

    def test_apostrophe_is_a_suffix_boundary(self):
        self.assertEqual(whatsapp_ui.search_variants("Zeynep'e"), ["zeynep"])

    def test_short_names(self):
        self.assertEqual(whatsapp_ui.search_variants("Ay"), ["ay"])
        self.assertEqual(whatsapp_ui.open_search("a")["status"], "empty")


class Raising(unittest.TestCase):
    """Öne alma: SetForegroundWindow sessizce engellense de pencere gerçekten öne gelir."""

    def _fake(self, succeed_on=None):
        state = {"fg": 99, "calls": []}
        fake = types.SimpleNamespace()
        fake.GetWindowText = lambda h: "WhatsApp"
        fake.GetClassName = lambda h: "WinUIDesktopWin32WindowClass"
        fake.IsWindowVisible = lambda h: True
        fake.EnumWindows = lambda visit, param: (visit(11, None), True)[1]
        fake.ShowWindow = lambda h, how: state["calls"].append("show")
        fake.BringWindowToTop = lambda h: state["calls"].append("bring")
        fake.SwitchToThisWindow = lambda h, top: state["calls"].append("switch")
        fake.GetForegroundWindow = lambda: state["fg"]

        def setfg(handle):
            state["calls"].append("setfg")
            if succeed_on == "switch" and "switch" not in state["calls"]:
                raise OSError("engellendi")
            state["fg"] = handle if succeed_on in ("setfg", "bring", "switch") else 99
        fake.SetForegroundWindow = setfg
        return fake, state

    def test_show_reports_failure_without_typing(self):
        fake, state = self._fake(succeed_on=None)
        with mock.patch.dict(sys.modules, {"win32gui": fake, "win32con": types.SimpleNamespace(SW_RESTORE=9),
                                           "win32api": types.SimpleNamespace(GetCurrentThreadId=lambda: 1),
                                           "win32process": types.SimpleNamespace(GetWindowThreadProcessId=lambda h: (2, 0),
                                                                                 AttachThreadInput=lambda *a: None)}),              mock.patch.object(whatsapp_ui.time, "sleep", lambda *_: None):
            result = whatsapp_ui.show()
        self.assertEqual(result["status"], "failed")
        self.assertIn("hiçbir şey yazmadım", result["text"])

    def test_show_succeeds_when_raising_works(self):
        fake, state = self._fake(succeed_on="setfg")
        with mock.patch.dict(sys.modules, {"win32gui": fake, "win32con": types.SimpleNamespace(SW_RESTORE=9),
                                           "win32api": types.SimpleNamespace(GetCurrentThreadId=lambda: 1),
                                           "win32process": types.SimpleNamespace(GetWindowThreadProcessId=lambda h: (2, 0),
                                                                                 AttachThreadInput=lambda *a: None)}),              mock.patch.object(whatsapp_ui.time, "sleep", lambda *_: None):
            self.assertEqual(whatsapp_ui.show()["status"], "done")


if __name__ == "__main__":
    unittest.main()
