import unittest

from modules.event_fanout import dispatch


class EventFanoutTests(unittest.TestCase):
    def test_one_event_is_delivered_to_multiple_channels(self):
        received = []

        def ui(event):
            received.append(("ui", event["source"]))

        def ntfy(event):
            received.append(("ntfy", event["kind"]))

        result = dispatch(
            {"source": "whatsapp", "kind": "message", "payload": {"text": "merhaba"}},
            {"ui": ui, "ntfy": ntfy},
            ("ui", "ntfy"),
        )
        self.assertEqual(result, {"ui": "delivered", "ntfy": "delivered"})
        self.assertEqual(received, [("ui", "whatsapp"), ("ntfy", "message")])

    def test_one_failed_channel_does_not_block_the_others(self):
        received = []

        def broken(_event):
            raise RuntimeError("kanal kapalı")

        def working(event):
            received.append(event["source"])

        result = dispatch(
            {"source": "source_watch", "kind": "update", "payload": {}},
            {"webhook": broken, "ui": working},
            ("webhook", "ui"),
        )
        self.assertEqual(result["webhook"], "failed:RuntimeError")
        self.assertEqual(result["ui"], "delivered")
        self.assertEqual(received, ["source_watch"])

    def test_unknown_channel_and_invalid_event_fail_closed(self):
        with self.assertRaises(ValueError):
            dispatch({"source": "x", "kind": "y", "payload": {}}, {}, ("shell",))
        with self.assertRaises(ValueError):
            dispatch({"source": "x", "payload": {}}, {}, ("ui",))


if __name__ == "__main__":
    unittest.main()
