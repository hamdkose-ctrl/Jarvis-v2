"""Gateway giriş olayı canonical hook hattından geçiyor mu (Faz 2, T21)."""
import unittest

from modules import hooks, webhook_server


class _SahteIstek:
    """Handler._gateway_event yalnız kendini kullanır; gerçek soket gerekmez."""

    _gateway_event = webhook_server.Handler._gateway_event


class GatewayHookTests(unittest.TestCase):
    def setUp(self):
        self.olaylar = []
        hooks.clear()
        hooks.register("gateway", self.olaylar.append)
        self.addCleanup(hooks.clear)

    def test_gelen_olay_gateway_hook_olarak_dusuyor(self):
        _SahteIstek()._gateway_event('hamdi', 'github', {'kind': 'push'})
        self.assertEqual(len(self.olaylar), 1)
        yuk = self.olaylar[0]["payload"]
        self.assertEqual(yuk['event'], 'inbound')
        self.assertEqual(yuk['source'], 'github')
        self.assertEqual(yuk['kind'], 'push')
        self.assertEqual(self.olaylar[0]['owner'], 'hamdi')

    def test_yuk_gonderilmiyor_ve_uzun_alan_kirpiliyor(self):
        _SahteIstek()._gateway_event('hamdi', 'x' * 80, {'kind': 'k' * 80, 'secret': 'gizli'})
        yuk = self.olaylar[0]["payload"]
        self.assertEqual(len(yuk['source']), 40)
        self.assertEqual(len(yuk['kind']), 40)
        self.assertNotIn('secret', yuk)

    def test_gozlemci_hatasi_gelen_olayi_dusurmuyor(self):
        def patla(event):
            raise RuntimeError("gozlemci bozuk")
        hooks.register("gateway", patla)
        _SahteIstek()._gateway_event('hamdi', 'github', {'kind': 'push'})
        self.assertEqual(len(self.olaylar), 1)


if __name__ == "__main__":
    unittest.main()
