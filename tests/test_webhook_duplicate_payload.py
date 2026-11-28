from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from modules import llm
from modules import message_inbox as inbox
from modules import service_store as store
from modules import publish_services as services
from modules import webhook_server


class TekrarYukOlayUretmezTestleri(unittest.TestCase):
    """Aynı yük iki kez gelirse ikinci geliş yeni olay sayılmamalı (B2b)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        yama = patch.object(store, "ROOT", Path(self.tmp.name))
        yama.start()
        self.addCleanup(yama.stop)
        token = llm._key_context.set("alice")
        self.addCleanup(llm._key_context.reset, token)
        self.settings = {
            "webhook_enabled": True,
            "app_secret": "secret-is-local-and-long",
            "verify_token": "verify-token-long-enough",
            "phone_number_id": "123",
        }
        yama = patch.object(services, "configuration", return_value=self.settings)
        yama.start()
        self.addCleanup(yama.stop)
        from modules import scheduler_resource_gate
        self.enterContext(
            patch.object(scheduler_resource_gate, "_ACCOUNT_CLAIM_ROOT",
                         Path(self.tmp.name) / "claims")
        )
        self.enterContext(
            patch.object(services, "DATA_DIR", Path(self.tmp.name) / "connections")
        )

    def _yuk(self, mesaj_id: str = "wamid.1") -> bytes:
        veri = {
            "metadata": {"phone_number_id": "123"},
            "messages": [{"id": mesaj_id, "from": "905001234567",
                          "text": {"body": "Merhaba"}}],
        }
        return json.dumps({
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"field": "messages", "value": veri}]}],
        }).encode("utf-8")

    def _imza(self, ham: bytes) -> str:
        return "sha256=" + hmac.new(
            self.settings["app_secret"].encode(), ham, hashlib.sha256
        ).hexdigest()

    def _sunucu(self):
        sunucu = ThreadingHTTPServer(("127.0.0.1", 0), webhook_server.Handler)
        sunucu.allowed_owners = {"alice"}
        sunucu.notify = Mock()
        is_parcacik = threading.Thread(target=sunucu.serve_forever, daemon=True)
        is_parcacik.start()
        self.addCleanup(is_parcacik.join, 2)
        self.addCleanup(sunucu.server_close)
        self.addCleanup(sunucu.shutdown)
        return sunucu

    def _gonder(self, sunucu, ham: bytes) -> int:
        baglanti = http.client.HTTPConnection("127.0.0.1", sunucu.server_port, timeout=3)
        baglanti.request("POST", "/whatsapp/alice", ham,
                         {"X-Hub-Signature-256": self._imza(ham)})
        yanit = baglanti.getresponse()
        yanit.read()
        kod = yanit.status
        baglanti.close()
        return kod

    def test_ayni_yuk_ikinci_kez_olay_uretmez(self):
        sunucu = self._sunucu()
        ham = self._yuk()
        self.assertEqual(self._gonder(sunucu, ham), 200)
        self.assertEqual(self._gonder(sunucu, ham), 200)
        sunucu.notify.assert_called_once()
        self.assertEqual(len(inbox.read("alice")["snapshot"]["items"]), 1)

    def test_farkli_yuk_yeni_olay_uretir(self):
        sunucu = self._sunucu()
        self.assertEqual(self._gonder(sunucu, self._yuk("wamid.1")), 200)
        self.assertEqual(self._gonder(sunucu, self._yuk("wamid.2")), 200)
        self.assertEqual(sunucu.notify.call_count, 2)


if __name__ == "__main__":
    unittest.main()
