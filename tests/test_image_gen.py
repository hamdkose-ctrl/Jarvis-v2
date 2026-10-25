"""image_gen: Cloudflare Workers AI (FLUX) görsel üretim katmanı.

Hiçbir test gerçek ağa çıkmaz; `requests.post` yerine sahte bir `_session`
nesnesi verilir. Anahtar dosyaları izole bir DATA_DIR'e yönlendirilir.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import image_gen as ig


class ImageGenKeyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = patch("config.DATA_DIR", Path(self._tmp.name))
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_set_and_read_roundtrip(self):
        ig.set_user_cloudflare("hamdi", "acc123", "tok456")
        self.assertEqual(ig.user_cloudflare_account("hamdi"), "acc123")
        self.assertEqual(ig.user_cloudflare_token("hamdi"), "tok456")

    def test_other_user_has_no_access_to_key(self):
        ig.set_user_cloudflare("hamdi", "acc123", "tok456")
        self.assertEqual(ig.user_cloudflare_account("ebru"), "")
        self.assertEqual(ig.user_cloudflare_token("ebru"), "")

    def test_clearing_with_empty_values_deletes_key(self):
        ig.set_user_cloudflare("hamdi", "acc123", "tok456")
        ig.set_user_cloudflare("hamdi", None, None)
        self.assertEqual(ig.user_cloudflare_account("hamdi"), "")
        self.assertEqual(ig.user_cloudflare_token("hamdi"), "")

    def test_key_state_does_not_leak_secrets(self):
        ig.set_user_cloudflare("hamdi", "acc123", "tok456")
        state = ig.key_state("hamdi")
        self.assertTrue(state["configured"])
        dumped = str(state)
        self.assertNotIn("acc123", dumped)
        self.assertNotIn("tok456", dumped)

    def test_key_state_unconfigured_for_unknown_user(self):
        state = ig.key_state("kimse")
        self.assertFalse(state["configured"])


class _FakeResponse:
    def __init__(self, status_code=200, content=b"", headers=None, json_body=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self._json_body = json_body

    def json(self):
        if self._json_body is None:
            raise ValueError("no json")
        return self._json_body


class _FakeSession:
    def __init__(self, response=None, raise_exc=None):
        self._response = response
        self._raise_exc = raise_exc
        self.calls = []

    def post(self, url, headers=None, data=None, timeout=None):
        self.calls.append((url, headers, data, timeout))
        if self._raise_exc:
            raise self._raise_exc
        return self._response


class GenerateImageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = patch("config.DATA_DIR", Path(self._tmp.name))
        self._patch.start()
        ig.set_user_cloudflare("hamdi", "acc123", "tok456")

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_empty_prompt_rejected_without_network_call(self):
        session = _FakeSession()
        with self.assertRaises(ig.ImageGenError) as ctx:
            ig.generate_image("", slug="hamdi", _session=session)
        self.assertEqual(ctx.exception.reason_code, "EMPTY_PROMPT")
        self.assertEqual(session.calls, [])

    def test_missing_user_key_rejected_without_network_call(self):
        session = _FakeSession()
        with self.assertRaises(ig.ImageGenError) as ctx:
            ig.generate_image("bir kedi çiz", slug="ebru", _session=session)
        self.assertEqual(ctx.exception.reason_code, "NO_KEY")
        self.assertEqual(session.calls, [])

    def test_successful_image_response_returns_bytes(self):
        session = _FakeSession(_FakeResponse(
            status_code=200, content=b"\x89PNGfakebytes",
            headers={"content-type": "image/png"},
        ))
        data = ig.generate_image("süreç özeti görseli", slug="hamdi", _session=session)
        self.assertEqual(data, b"\x89PNGfakebytes")
        self.assertEqual(len(session.calls), 1)
        url, headers, body, timeout = session.calls[0]
        self.assertIn("acc123", url)
        self.assertEqual(headers["Authorization"], "Bearer tok456")

    def test_base64_json_response_is_decoded(self):
        import base64
        encoded = base64.b64encode(b"rawpixels").decode()
        session = _FakeSession(_FakeResponse(
            status_code=200, content=b"", headers={"content-type": "application/json"},
            json_body={"result": {"image": encoded}},
        ))
        data = ig.generate_image("zihin haritası", slug="hamdi", _session=session)
        self.assertEqual(data, b"rawpixels")

    def test_auth_failure_maps_to_auth_failed(self):
        session = _FakeSession(_FakeResponse(status_code=401))
        with self.assertRaises(ig.ImageGenError) as ctx:
            ig.generate_image("x", slug="hamdi", _session=session)
        self.assertEqual(ctx.exception.reason_code, "AUTH_FAILED")

    def test_rate_limit_maps_to_quota_exceeded(self):
        session = _FakeSession(_FakeResponse(status_code=429))
        with self.assertRaises(ig.ImageGenError) as ctx:
            ig.generate_image("x", slug="hamdi", _session=session)
        self.assertEqual(ctx.exception.reason_code, "QUOTA_EXCEEDED")

    def test_network_error_maps_to_network_error(self):
        session = _FakeSession(raise_exc=ConnectionError("boom"))
        with self.assertRaises(ig.ImageGenError) as ctx:
            ig.generate_image("x", slug="hamdi", _session=session)
        self.assertEqual(ctx.exception.reason_code, "NETWORK_ERROR")

    def test_unexpected_status_maps_to_provider_error(self):
        session = _FakeSession(_FakeResponse(status_code=500))
        with self.assertRaises(ig.ImageGenError) as ctx:
            ig.generate_image("x", slug="hamdi", _session=session)
        self.assertEqual(ctx.exception.reason_code, "PROVIDER_ERROR")


if __name__ == "__main__":
    unittest.main()
