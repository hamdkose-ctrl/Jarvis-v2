"""Gateway giriş olayı gerçek sunucudan geçiyor mu (Faz 2, T21)."""
import hashlib, hmac, json, threading, time, unittest, urllib.error, urllib.request
from unittest.mock import patch

from modules import hooks, webhook_server


class GatewayHookTests(unittest.TestCase):
    """Gerçek Handler + gerçek soket: yardımcı değil, bağlantı ölçülür."""

    def setUp(self):
        self.olaylar = []
        hooks.clear()
        hooks.register("gateway", self.olaylar.append)
        self.addCleanup(hooks.clear)
        self.durdur = threading.Event()
        self.addCleanup(self.durdur.set)
        self.addCleanup(self._sunucuyu_kapat)
        for hedef, deger in ((webhook_server.event_webhooks, {'enabled': True, 'sources': {'github': {'secret': 'x' * 20}}}),
                             (webhook_server.message_inbox, {'enabled': True})):
            yama = patch.object(hedef, 'config', return_value=deger)
            yama.start()
            self.addCleanup(yama.stop)

    def test_gelen_olay_gateway_hook_olarak_dusuyor(self):
        with patch.object(webhook_server.event_webhooks, "ingest", return_value={"kind": "push"}):
            kod, _ = self._gonder("/event/hamdi/github", b'{"kind": "push"}')
        self.assertEqual(kod, 200)
        self.assertEqual(len(self.olaylar), 1)
        yuk = self.olaylar[0]["payload"]
        self.assertEqual(yuk["event"], "inbound")
        self.assertEqual(yuk["source"], "github")
        self.assertEqual(yuk["kind"], "push")
        self.assertEqual(self.olaylar[0]["owner"], "hamdi")

    def _sunucuyu_kapat(self):
        sunucu = webhook_server._SERVER
        if sunucu is not None:
            sunucu.shutdown()
            sunucu.server_close()
        webhook_server._SERVER = None

    def _gonder(self, yol, govde):
        webhook_server.start(self.durdur, lambda: {"hamdi"}, port=0)
        port = self._port()
        istek = urllib.request.Request("http://127.0.0.1:%d%s" % (port, yol), data=govde,
                                       headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(istek, timeout=10) as yanit:
                return yanit.status, yanit.read()
        except urllib.error.HTTPError as hata:
            return hata.code, hata.read()

    def _port(self):
        for _ in range(50):
            sunucu = webhook_server._SERVER
            if sunucu is not None and getattr(sunucu, "server_address", None):
                return sunucu.server_address[1]
            time.sleep(0.1)
        self.skipTest("sunucu açılmadı")


if __name__ == "__main__":
    unittest.main()