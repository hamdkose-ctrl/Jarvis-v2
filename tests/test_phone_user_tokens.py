import engine_source
import json
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch


class _FakeEngine:
    """Telefon sunucusu için en küçük motor: komutu alır, kısa süre sonra kimlikli yanıt yazar."""
    def __init__(self):
        self.event_log, self._log_id, self.calls = [], 0, []

    def match_user(self, name):
        return {"hamdi": "Hamdi", "ebru": "Ebru"}.get((name or "").lower())

    def _emit(self, kind, text, user, rid):
        self._log_id += 1
        self.event_log.append({"id": self._log_id, "kind": kind, "text": text, "user": user, "rid": rid, "source": ""})

    def submit(self, text, source="yazı", user=None, rid=None):
        self.calls.append((text, user, rid))

        def run():
            time.sleep(0.05 if text == "ikinci" else 0.3)     # ikinci soru daha önce cevaplanır
            self._emit("user", text, user or "Hamdi", rid)
            self._emit("assistant", f"cevap:{text}:{user}", user or "Hamdi", rid)
        threading.Thread(target=run, daemon=True).start()


class PhoneUserTokenTests(unittest.TestCase):
    def setUp(self):
        from modules import phone
        self.phone = phone
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.settings = {"phone_scope":"both", "phone_allow_http":True}
        self.patches = [
            patch.object(phone, "TOKEN_FILE", d / "phone_token.txt"),
            patch.object(phone, "USER_TOKENS_FILE", d / "phone_tokens.json"),
            patch.object(phone, "_harden", lambda p: None),
            patch.object(phone, "load_settings", lambda: self.settings),
            patch.object(phone, "tailscale_ip", lambda: None),
            patch("config.save_settings", lambda **kw: self.settings.update(kw)),
            patch("modules.personalization.get_active", lambda: "Hamdi"),
            patch("modules.personalization.list_users", lambda: ["Hamdi", "Ebru"]),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_each_token_belongs_to_one_user(self):
        owner = self.phone.user_token("Hamdi")
        ebru = self.phone.user_token("Ebru")
        self.assertNotEqual(owner, ebru)
        self.assertEqual(self.phone.token_user(owner), "hamdi")
        self.assertEqual(self.phone.token_user(ebru), "ebru")
        self.assertIsNone(self.phone.token_user("yanlis-anahtar-" + "x" * 20))
        self.assertIsNone(self.phone.token_user("geçersiz-anahtar"))
        self.assertIsNone(self.phone.token_user("x" * 257))
        self.assertEqual(self.phone.user_token("Ebru"), ebru)            # kalıcı: aynı anahtar
        self.phone.reset_token()
        self.assertIsNone(self.phone.token_user(ebru))                     # yenileyince eski anahtar geçersiz

    def test_pairing_is_one_time_and_uses_selected_user(self):
        srv = self.phone.PhoneServer(_FakeEngine(), port=0)
        code = srv.pairing_code("Ebru")
        self.assertEqual(srv.pairing_code("Ebru"), code)
        token = srv.redeem_pairing(code)
        self.assertEqual(self.phone.token_user(token), "ebru")
        self.assertIsNone(srv.redeem_pairing(code))
        self.assertNotEqual(srv.pairing_code("Ebru"), code)

    def test_expired_deleted_user_and_cleared_pairings_are_rejected(self):
        srv = self.phone.PhoneServer(_FakeEngine(), port=0)
        code = srv.pairing_code("Ebru")
        now = self.phone.time.monotonic()
        with patch.object(self.phone.time, "monotonic", return_value=now + 91):
            self.assertIsNone(srv.redeem_pairing(code))
        self.assertIsNone(srv.redeem_pairing(srv.pairing_code("silinmis")))
        a, b = srv.pairing_code("Hamdi"), srv.pairing_code("Ebru")
        srv.clear_pairings("Hamdi")
        self.assertIsNone(srv.redeem_pairing(a))
        self.assertIsNotNone(srv.redeem_pairing(b))
        code = srv.pairing_code("Ebru")
        srv.stop()
        self.assertIsNone(srv.redeem_pairing(code))

    def test_pairing_can_only_be_redeemed_once_concurrently(self):
        srv = self.phone.PhoneServer(_FakeEngine(), port=0)
        code = srv.pairing_code("Ebru")
        out = []
        threads = [threading.Thread(target=lambda: out.append(srv.redeem_pairing(code))) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(2)
        self.assertEqual(len([x for x in out if x]), 1)

    def test_http_pairing_manifest_icons_and_connection_status(self):
        srv = self.phone.PhoneServer(_FakeEngine(), port=0)
        srv.start()
        try:
            base = f"http://127.0.0.1:{srv._httpd.server_address[1]}"
            code = srv.pairing_code("Ebru")
            req = urllib.request.Request(base + "/api/pair", method="POST",
                data=json.dumps({"code": code}).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as response:
                result = json.load(response)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(set(result), {"token"})
            self.assertEqual(self.phone.token_user(result["token"]), "ebru")
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(cm.exception.code, 401)
            log = urllib.request.Request(base + "/api/log", headers={"X-Token": result["token"]})
            with urllib.request.urlopen(log, timeout=5) as response:
                self.assertEqual(json.load(response), [])
            self.assertTrue(srv.connected("Ebru"))
            self.assertFalse(srv.connected("Hamdi"))
            now = self.phone.time.monotonic()
            with patch.object(self.phone.time, "monotonic", return_value=now + 21):
                self.assertFalse(srv.connected("Ebru"))
            with urllib.request.urlopen(base + "/manifest.json", timeout=5) as response:
                m = json.load(response)
            self.assertEqual(m["start_url"], "/")
            self.assertEqual([x["sizes"] for x in m["icons"]], ["192x192", "512x512"])
            for path in ("/icon-180.png", "/icon-192.png", "/icon-512.png"):
                with urllib.request.urlopen(base + path, timeout=5) as response:
                    self.assertEqual(response.headers["Content-Type"], "image/png")
                    self.assertTrue(response.read().startswith(b"\x89PNG\r\n\x1a\n"))
            with urllib.request.urlopen(base + "/sw.js", timeout=5) as response:
                self.assertIn(b"startsWith('/api/')", response.read())
        finally:
            srv.stop()

    def test_web_session_restores_selected_user_and_rejects_revoked_token(self):
        srv = self.phone.PhoneServer(_FakeEngine(), port=0)
        srv.start()
        try:
            url = f"http://127.0.0.1:{srv._httpd.server_address[1]}/api/web-session"
            token = self.phone.user_token("Ebru")
            save = urllib.request.Request(url, method="POST", data=b"", headers={"X-Token": token})
            with urllib.request.urlopen(save, timeout=5) as response:
                self.assertEqual(json.load(response), {"ok": True})
                cookie = response.headers["Set-Cookie"]
                for flag in ("Secure", "HttpOnly", "SameSite=Strict", "Path=/api/web-session"):
                    self.assertIn(flag, cookie)
            restore = urllib.request.Request(url, headers={"Cookie": cookie.split(";", 1)[0], "X-Jarvis-Web-Session": "1"})
            with urllib.request.urlopen(restore, timeout=5) as response:
                self.assertEqual(json.load(response), {"token": token})
                self.assertEqual(response.headers["Cache-Control"], "no-store")
            # Cookie alone cannot authorize ordinary APIs or cross-site navigation.
            for path, headers, expected in ((url, {"Cookie": cookie}, 403),
                    (url.replace("web-session", "log"), {"Cookie": cookie}, 401),
                    (url, {"X-Jarvis-Web-Session": "1"}, 401)):
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    urllib.request.urlopen(urllib.request.Request(path, headers=headers), timeout=5)
                self.assertEqual(cm.exception.code, expected)
            self.phone.reset_token()
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(restore, timeout=5)
            self.assertEqual(cm.exception.code, 401)
        finally:
            srv.stop()

    def test_pair_endpoint_limits_bad_json_size_and_attempts(self):
        srv = self.phone.PhoneServer(_FakeEngine(), port=0)
        srv.start()
        try:
            base = f"http://127.0.0.1:{srv._httpd.server_address[1]}/api/pair"
            def rejected(body, status):
                req = urllib.request.Request(base, method="POST", data=body)
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    urllib.request.urlopen(req, timeout=5)
                self.assertEqual(cm.exception.code, status)
            for body in (b'[]', b'{"code":[]}', b'x' * 1025, b'not-json'):
                rejected(body, 400)
            for _ in range(8):
                rejected(b'{"code":"wrong"}', 401)
            rejected(b'{"code":"wrong"}', 429)
        finally:
            srv.stop()

    def test_server_uses_token_owner_not_requested_name(self):
        eng = _FakeEngine()
        srv = self.phone.PhoneServer(eng, port=0)
        srv.start()
        try:
            port = srv._httpd.server_address[1]
            ebru = self.phone.user_token("Ebru")

            def post(text, user):
                req = urllib.request.Request(f"http://127.0.0.1:{port}/api/ask", method="POST",
                                             data=json.dumps({"text": text, "user": user}).encode(),
                                             headers={"X-Token": ebru, "Content-Type": "application/json"})
                return json.loads(urllib.request.urlopen(req, timeout=10).read())["reply"]

            # Ebru'nun anahtarıyla "Hamdi" adına sormak: yine Ebru olarak işlenir
            self.assertEqual(post("birinci", "Hamdi"), "cevap:birinci:Ebru")
            self.assertTrue(all(u == "Ebru" for _, u, _ in eng.calls))
            # Aynı anda iki soru: yanıtlar karışmaz (ikincisi önce bitse bile)
            out = {}
            t = threading.Thread(target=lambda: out.setdefault("a", post("birinci", "")))
            t.start()
            time.sleep(0.02)
            out["b"] = post("ikinci", "")
            t.join(5)
            self.assertEqual(out["a"], "cevap:birinci:Ebru")
            self.assertEqual(out["b"], "cevap:ikinci:Ebru")
            # Yanlış anahtar reddedilir
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/log?after=0", headers={"X-Token": "x" * 30})
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(cm.exception.code, 401)
        finally:
            srv.stop()


class MainRequestIdTests(unittest.TestCase):
    def test_main_carries_request_id_to_answer(self):
        src = engine_source.source()
        self.assertIn('events.put(("command", text, source, user, rid))', src)
        self.assertIn('"rid": _cur_rid', src)
        self.assertIn("_, cmd, source, user, _cur_rid = (tuple(event) + (None, None))[:5]", src)
        self.assertIn("_ui = ui", src)
        self.assertIn("_cur_source = source", src)


if __name__ == "__main__":
    unittest.main()
