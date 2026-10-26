import hashlib
import hmac
import http.client
import json
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch

from modules import event_fanout, event_hooks, llm, publish_services as services, webhook_server

SECRET = "olay-sirri-yerel-ve-yeterince-uzun-1234"


class EventHookTests(unittest.TestCase):
    def setUp(self):
        token = llm._key_context.set("alice")
        self.addCleanup(llm._key_context.reset, token)
        self.settings = {"enabled": True, "secret": SECRET, "sources": ["github"], "channels": ["ui", "ntfy", "log"]}
        p = patch.object(services, "configuration", side_effect=lambda owner, service: self.settings)
        p.start()
        self.addCleanup(p.stop)

    def signed(self, body, ts=None):
        raw = json.dumps(body).encode()
        ts = str(int(time.time())) if ts is None else ts
        return raw, ts, "sha256=" + hmac.new(SECRET.encode(), ts.encode() + b"." + raw, hashlib.sha256).hexdigest()

    def test_signed_event_parses_with_configured_channels(self):
        raw, ts, sig = self.signed({"kind": "push", "payload": {"text": "main güncellendi"}})
        event, channels = event_hooks.parse("alice", "github", raw, ts, sig)
        self.assertEqual(event, {"source": "hook:github", "kind": "push", "payload": {"text": "main güncellendi"}})
        self.assertEqual(channels, ("ui", "ntfy", "log"))

    def test_bad_signature_old_timestamp_and_unlisted_source_are_refused(self):
        raw, ts, sig = self.signed({"kind": "push"})
        with self.assertRaises(PermissionError):
            event_hooks.parse("alice", "github", raw, ts, "sha256=" + "0" * 64)
        old, old_ts, old_sig = self.signed({"kind": "push"}, ts=str(int(time.time()) - 3600))
        with self.assertRaises(PermissionError):
            event_hooks.parse("alice", "github", old, old_ts, old_sig)
        with self.assertRaises(PermissionError):
            event_hooks.parse("alice", "gitlab", raw, ts, sig)
        self.settings["enabled"] = False
        with self.assertRaises(PermissionError):
            event_hooks.parse("alice", "github", raw, ts, sig)

    def test_bad_channel_config_falls_back_to_default(self):
        self.assertEqual(event_hooks.channels({"channels": ["shell"]}), event_hooks.DEFAULT_CHANNELS)
        self.assertEqual(event_hooks.channels({"channels": ["ui", "ui"]}), event_hooks.DEFAULT_CHANNELS)

    def test_sinks_send_one_event_to_chat_phone_and_log(self):
        emit, log = Mock(), Mock()
        send = Mock(return_value=True)
        event = {"source": "hook:github", "kind": "push", "payload": {"text": "yeni sürüm"}}
        result = event_fanout.dispatch(event, event_hooks.sinks(emit, "jarvis-topic", send, log), ("ui", "ntfy", "log"))
        self.assertEqual(result, {"ui": "delivered", "ntfy": "delivered", "log": "delivered"})
        self.assertIn("yeni sürüm", emit.call_args.args[0])
        self.assertEqual(send.call_args.args[0], "jarvis-topic")
        send.return_value = False
        result = event_fanout.dispatch(event, event_hooks.sinks(emit, "jarvis-topic", send, log), ("ntfy", "ui"))
        self.assertEqual(result, {"ntfy": "failed:ConnectionError", "ui": "delivered"})
        self.assertEqual(event_fanout.dispatch(event, event_hooks.sinks(emit, None, send, log), ("ntfy",)), {"ntfy": "unavailable"})

    def test_http_hook_route_delivers_to_event_notify(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), webhook_server.Handler)
        server.allowed_owners = {"alice"}
        server.notify = Mock()
        server.event_notify = Mock()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def post(path, raw, headers):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            connection.request("POST", path, raw, headers)
            response = connection.getresponse()
            response.read()
            connection.close()
            return response.status

        try:
            raw, ts, sig = self.signed({"kind": "push", "payload": {"text": "merhaba"}})
            self.assertEqual(post("/hook/alice/github", raw, {"X-Jarvis-Timestamp": ts, "X-Jarvis-Signature": sig}), 200)
            self.assertEqual(post("/hook/alice/github", raw, {"X-Jarvis-Timestamp": ts, "X-Jarvis-Signature": "sha256=" + "0" * 64}), 403)
            # Path refusals answer before reading the body; an empty body avoids a Windows connection reset.
            self.assertEqual(post("/hook/bob/github", b"", {"X-Jarvis-Timestamp": ts, "X-Jarvis-Signature": sig}), 403)
            self.assertEqual(post("/hook/alice/Bad!", b"", {"X-Jarvis-Timestamp": ts, "X-Jarvis-Signature": sig}), 400)
            server.event_notify.assert_called_once()
            owner, event, channels = server.event_notify.call_args.args
            self.assertEqual((owner, event["source"], channels), ("alice", "hook:github", ("ui", "ntfy", "log")))
            server.notify.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
