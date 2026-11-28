import contextvars
import queue
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import web
from modules import mascot_dock, mascot_window


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

    def test_native_card_opens_and_renders_reply(self):
        if not mascot_window.available():
            self.skipTest("Tk/Pillow yok")
        import tkinter as tk

        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
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
                self.runtime.bridge.listen_once.assert_called_once()
                observations.put(None)
            except BaseException as exc:
                observations.put(exc)
            finally:
                root.quit()

        def observe():
            try:
                dock = mascot.dock
                dock.next_jobs = float("inf")
                dock.open(focus=True)
                dock.listen()
                dock.entry.insert(0, "Bugün ne var?")
                self.runtime.bridge.send.return_value = True
                dock.send()
                root.after(180, verify_send)
            except BaseException as exc:
                observations.put(exc)
                root.quit()

        root.after(250, observe)
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
