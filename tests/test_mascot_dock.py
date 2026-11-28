import contextvars
import queue
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import web
from modules import mascot_bubble, mascot_dock, mascot_window


def _windows_station_visible():
    """Return True/False only with a successful Win32 station flags query."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class Flags(ctypes.Structure):
        _fields_ = [("inherit", wintypes.BOOL), ("reserved", wintypes.BOOL),
                    ("flags", wintypes.DWORD)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetProcessWindowStation.argtypes = []
    user32.GetProcessWindowStation.restype = wintypes.HANDLE
    user32.GetUserObjectInformationW.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    user32.GetUserObjectInformationW.restype = wintypes.BOOL
    station = user32.GetProcessWindowStation()
    info, needed = Flags(), wintypes.DWORD()
    if not station or not user32.GetUserObjectInformationW(
            station, 1, ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(needed)):
        return None
    return bool(info.flags & 1)  # UOI_FLAGS / WSF_VISIBLE


class MascotDockTests(unittest.TestCase):
    def setUp(self):
        self.profile = SimpleNamespace(slug="hamdi")
        self.runtime = SimpleNamespace(
            _p=lambda: self.profile,
            _bridge_profile=contextvars.ContextVar("test_mascot_profile"),
            _mascot=None,
            _tray=object(),
            _main_window_open=lambda: False,
            _show_main=Mock(),
            engine=SimpleNamespace(pc_profile=lambda: self.profile, flags={"mic": True}, stop_event=threading.Event()),
            config=SimpleNamespace(load_settings=lambda: {}, save_settings=Mock()),
            hub=web.Hub(),
            bridge=Mock(),
        )

    def test_desktop_subscription_is_not_browser_presence(self):
        hub = self.runtime.hub
        with patch.object(web.engine, "pc_profile", return_value=self.profile):
            desktop = hub.subscribe(desktop=True)
            hub.publish("assistant", "Yanıt", metadata={"rid": "same-turn"})
            self.assertEqual(desktop.get_nowait()["rid"], "same-turn")
            self.assertFalse(hub.clients)
            self.assertFalse(hub.ever)
            hub.unsubscribe(desktop, desktop=True)
            hub.publish("assistant", "Başka")
            self.assertTrue(desktop.empty())

    def test_sources_and_compose_paths_are_bounded(self):
        result = mascot_dock.reply_links("[haber](https://www.example.org/haber) https://www.example.org/haber. http://example.org https://u:pw@private.test")
        self.assertEqual(result, ["https://www.example.org/haber"])
        self.assertEqual(mascot_dock.file_command("", ["C:/Test File.pdf"]), '"C:/Test File.pdf" dosyasını özetle')
        with self.assertRaises(ValueError):
            mascot_dock.file_command("özetle", ['bad"file.txt'])

    def test_shortcut_has_no_key_repeat_or_ambiguous_modifiers(self):
        self.assertEqual(mascot_dock.parse_hotkey("Ctrl+Alt+J"), (0x4003, ord("J")))
        for value in ("J", "Win+J", "Ctrl+Ctrl+J", "Ctrl+F11"):
            self.assertIsNone(mascot_dock.parse_hotkey(value))

    def test_scoped_buttons_match_the_selected_job(self):
        self.assertEqual(mascot_dock.eligible_job_actions({"kind": "goal", "record_state": "approval",
                                                           "approval": "Belgeyi seçilen yere taşı"}), ("approve", "cancel"))
        self.assertEqual(mascot_dock.eligible_job_actions({"record_state": "approval", "approval": ""}), ())
        self.assertEqual(mascot_dock.eligible_job_actions({"state": "done"}), ())
        self.assertEqual(mascot_dock.eligible_job_actions({"kind": "goal", "state": "question"}), ("answer", "cancel"))

    def test_owner_change_discards_pending_card_and_worker_results(self):
        mascot = mascot_window.MascotWindow(self.runtime)
        dock = mascot_dock.MascotDock(mascot)
        dock.next_jobs = float("inf")
        try:
            dock._event({"user": "somebody_else", "k": "assistant", "t": "Other person's reply"})
            self.assertEqual(dock.last_reply, "")
            callback = Mock()
            dock.local.put(("send", "hamdi", 0, callback, True, None))
            dock.last_reply = "Eski yanıt"
            self.profile = SimpleNamespace(slug="yeni")
            dock.tick()
            callback.assert_not_called()
            self.assertEqual(dock.last_reply, "")
            self.assertEqual(dock.owner, "yeni")
        finally:
            dock.close()

    def test_bubble_places_its_light_trail_towards_the_hood(self):
        monitor = [(0, 0, 1300, 740)]
        x, y, trail, anchor = mascot_bubble.place((1000, 520, 160, 206), 260, 90, monitor)
        self.assertEqual(trail, "down")
        self.assertLess(y + 115, 540)
        self.assertEqual(x + anchor, 1088)
        x, y, trail, anchor = mascot_bubble.place((10, 0, 160, 206), 260, 90, monitor)
        self.assertEqual(trail, "left")
        image, inset = mascot_bubble.artwork(260, 90, trail, anchor)
        self.assertEqual((image.size, inset), ((285, 90), 25))
        self.assertEqual(image.getpixel((0, 0)), mascot_window.KEY_RGB)
        self.assertEqual(image.getpixel((130, 45)), mascot_window.KEY_RGB)
        trail_area = image.crop((0, 0, inset, 90))
        self.assertGreater(len(trail_area.getcolors(inset * 90)), 1)

    def test_caption_dispatch_preserves_owner_and_state(self):
        dock = mascot_dock.MascotDock(mascot_window.MascotWindow(self.runtime))
        try:
            with patch.object(dock, "show_bubble") as show:
                dock._event({"user": "another-owner", "k": "state", "t": "listening"})
                show.assert_not_called()
                dock._event({"user": "hamdi", "k": "state", "t": "listening"})
                show.assert_called_once_with("Dinliyorum…", seconds=5, view=None)
                dock._event({"user": "hamdi", "k": "state", "t": "listening"})
                self.assertEqual(show.call_count, 1)
                dock._event({"user": "hamdi", "k": "assistant", "t": "Sesli yanıt"})
                show.assert_called_with("Sesli yanıt")
                self.assertEqual(dock.last_reply, "Sesli yanıt")
        finally:
            dock.close()

    def test_native_card_opens_and_renders_reply(self):
        if not mascot_window.available():
            self.skipTest("Tk/Pillow yok")
        import tkinter as tk

        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        # Independent control: a plain Tk window, before any mascot code.
        # A service window station may not map even a stock Tk window.
        # Only an independently confirmed non-visible station permits skipping.
        station_visible = _windows_station_visible()
        root.geometry("120x80+20+20")
        root.deiconify()
        deadline = time.monotonic() + 2.0
        while not root.winfo_viewable() and time.monotonic() < deadline:
            root.update()
            time.sleep(.02)
        plain_mapped = bool(root.winfo_viewable())
        if not plain_mapped:
            evidence = (f"plain Tk mapped={root.winfo_ismapped()}, state={root.state()}, "
                        f"Win32 station visible={station_visible}")
            root.destroy()
            if station_visible is False:
                self.skipTest("Physical desktop unavailable; " + evidence)
            self.fail("Independent Tk control did not map; " + evidence)
        root.withdraw()
        mascot = mascot_window.MascotWindow(self.runtime)
        mascot_window._STOP.clear()
        observations = queue.SimpleQueue()

        def verify_send():
            try:
                dock = mascot.dock
                dock.tick()
                self.runtime.bridge.send.assert_called_once()
                text, rid = self.runtime.bridge.send.call_args.args
                self.assertEqual(text, "Bugün ne var?")
                self.assertEqual(dock.active_rid, rid)
                dock._event({"user": "hamdi", "k": "assistant", "t": "Gerçek kart yanıtı", "rid": rid})
                self.assertTrue(dock.panel.winfo_exists())
                self.assertEqual(dock.last_reply, "Gerçek kart yanıtı")
                self.assertEqual(dock.active_rid, "")
                dock.open_console()
                self.runtime._show_main.assert_called_once()
                self.runtime.bridge.listen_once.assert_not_called()
                observations.put(None)
            except BaseException as exc:
                observations.put(exc)
            finally:
                root.quit()

        def guarded(callback):
            def run():
                try:
                    callback()
                except BaseException as exc:
                    observations.put(exc)
                    root.quit()
            return run

        def after_visibility(window, visible, then, label):
            # Tk's idle queue is not its native Windows event queue. Wait for
            # actual map/unmap notifications on the live event loop, not sleeps
            # or a simulated boolean; fail on a bounded real deadline.
            deadline = time.monotonic() + 2.0

            def poll():
                if bool(window.winfo_viewable()) == visible:
                    then()
                    return
                if time.monotonic() >= deadline:
                    self.fail(f"{label}: expected viewable={visible}, "
                              f"state={window.state()}, mapped={window.winfo_ismapped()}, "
                              f"mascot_mapped={mascot.window.winfo_ismapped()}, "
                              f"root_state={root.state()}")
                root.after(20, guarded(poll))

            root.after(0, guarded(poll))

        def observe():
            dock = mascot.dock
            dock.next_jobs = float("inf")
            after_visibility(mascot.window, True, mascot_visible, "main mascot")

        def mascot_visible():
            dock = mascot.dock
            mascot._welcome()
            self.assertIsNone(dock.bubble_view)
            after_visibility(dock.bubble, True, welcome_visible, "welcome caption")

        def welcome_visible():
            dock = mascot.dock
            contents = [dock.bubble_canvas.itemcget(item, "text")
                        for item in dock.bubble_canvas.find_withtag("message")]
            self.assertEqual(contents, ["Merhaba, hoş geldin."])
            dock.open_bubble()
            after_visibility(dock.bubble, False, welcome_hidden, "dismissed welcome")

        def welcome_hidden():
            dock = mascot.dock
            mascot.label.event_generate("<ButtonPress-1>", x=70, y=60)
            mascot.label.event_generate("<ButtonRelease-1>", x=70, y=60)
            self.assertIsNone(dock.panel)
            self.runtime.bridge.listen_once.assert_not_called()
            with patch.object(dock, "show_bubble", wraps=dock.show_bubble) as show:
                dock._event({"user": "hamdi", "k": "state", "t": "listening"})
                show.assert_called_once_with("Dinliyorum…", seconds=5, view=None)
            self.assertEqual(dock.shown_state, "listening")
            after_visibility(dock.bubble, True, listening_visible, "listening caption")

        def listening_visible():
            dock = mascot.dock
            self.assertEqual([dock.bubble_canvas.itemcget(item, "text")
                              for item in dock.bubble_canvas.find_withtag("message")],
                             ["Dinliyorum…"])
            self.assertIsNone(dock.panel)
            dock._event({"user": "hamdi", "k": "assistant", "t": "Sesli yanıt"})
            after_visibility(dock.bubble, True, reply_visible, "reply caption")

        def reply_visible():
            dock = mascot.dock
            self.assertIsNone(dock.panel)
            self.assertEqual(dock.badge, "")
            self.assertEqual([dock.bubble_canvas.itemcget(item, "text")
                              for item in dock.bubble_canvas.find_withtag("message")],
                             ["Sesli yanıt"])
            dock.open_bubble()
            after_visibility(dock.bubble, False, reply_hidden, "reply caption dismissed")

        def reply_hidden():
            dock = mascot.dock
            after_visibility(dock.panel, True, compose_visible, "reply card")

        def compose_visible():
            dock = mascot.dock
            dock.entry.insert(0, "Bugün ne var?")
            self.runtime.bridge.send.return_value = True
            dock.send()
            root.after(180, verify_send)

        root.after(250, guarded(observe))
        try:
            with patch.object(tk, "Tk", return_value=root):
                self.assertTrue(mascot.open())
            result = observations.get_nowait()
            if result:
                raise result
        finally:
            mascot.close()


if __name__ == "__main__":
    unittest.main()
