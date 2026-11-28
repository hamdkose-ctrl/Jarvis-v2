"""Finans alarmı teslim başlığı: telefon bildiriminde ayrı görünür (Faz 3, 3-D)."""
import os
import unittest
from unittest.mock import patch

from modules import notify, watcher


class _Owner:
    def __init__(self, slug="hamdi"):
        self.slug = slug
        self.data = {"prefs": {}}


class _Runtime:
    def __init__(self):
        self.events = []
        self.sent = []
        self.notify = self

    def _emit_for(self, owner, kind, text, source):
        self.events.append((owner.slug, kind, text, source))

    def send(self, topic, title, message):
        self.sent.append((topic, title, message))
        return True


class FinanceNotificationTitleTests(unittest.TestCase):
    def test_finance_and_watch_titles_are_different(self):
        rt = _Runtime()
        watch, finance = watcher.emitters(rt, _Owner(), "konu-1")
        watch("Yeni dosya: rapor.pdf")
        finance("USD/TRY 41,20 · alarm eşiği 40,00 üstünde")
        self.assertEqual([s[1] for s in rt.sent],
                         ["Jarvis klasör izleme", "Jarvis finans alarmı"])
        self.assertEqual([s[0] for s in rt.sent], ["konu-1", "konu-1"])

    def test_phone_message_is_the_first_line_shortened(self):
        rt = _Runtime()
        _, finance = watcher.emitters(rt, _Owner(), "konu-1")
        finance("ilk satır\n" + "x" * 400)
        self.assertEqual(rt.sent[0][2], "ilk satır")

    def test_without_a_topic_the_chat_still_gets_the_alert(self):
        rt = _Runtime()
        _, finance = watcher.emitters(rt, _Owner(), None)
        finance("USD/TRY 41,20 · alarm")
        self.assertEqual(rt.sent, [])
        self.assertEqual(rt.events, [("hamdi", "assistant", "USD/TRY 41,20 · alarm", "izleme")])

    def test_a_broken_phone_transport_does_not_swallow_the_chat_alert(self):
        rt = _Runtime()

        def patla(*a, **k):
            raise OSError("ağ yok")
        rt.send = patla
        _, finance = watcher.emitters(rt, _Owner(), "konu-1")
        with self.assertRaises(OSError):
            finance("USD/TRY 41,20 · alarm")
        self.assertEqual(len(rt.events), 1)


class NotifyServerTests(unittest.TestCase):
    def test_default_server_is_public_ntfy(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JARVIS_NTFY_SERVER", None)
            import importlib
            self.assertEqual(importlib.reload(notify).SERVER, "https://ntfy.sh")

    def test_env_can_point_to_a_local_receiver(self):
        with patch.dict(os.environ, {"JARVIS_NTFY_SERVER": "http://127.0.0.1:8799/"}):
            import importlib
            self.assertEqual(importlib.reload(notify).SERVER, "http://127.0.0.1:8799")
        import importlib
        os.environ.pop("JARVIS_NTFY_SERVER", None)
        importlib.reload(notify)


if __name__ == "__main__":
    unittest.main()
