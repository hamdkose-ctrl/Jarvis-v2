"""Yerel sağlık anahtarı: soğutma yazıldığı anahtarla okunmalı; ağ yok."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from modules import goal_executor, llm, resource_leases, smart_router as router


class HealthKeyTests(unittest.TestCase):
    """(T3d) Anahtar, istek sırasında değişen global yapılandırmaya bağlanmaz.

    Kanıt: aynı süreçte kayıt anahtarı 5e6cb21e…, okuma anahtarı b3c0e55c…, kalan 29,99 sn
    olmasına rağmen `_health_wait` 0 dönüyordu; yani soğutma yazılıyor ama okunamıyordu.
    """

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.enterContext(patch.object(router, '_HEALTH', {}))
        self.enterContext(patch.object(llm, 'current_user', return_value='alice'))
        self.enterContext(patch.object(llm, '_ollama_effective_model', return_value='local-test'))
        self.enterContext(patch.object(router, '_STORE', self.root / 'router'))
        self.enterContext(patch.object(goal_executor, '_RESOURCE_LEASES', resource_leases.LeaseTable()))
        self.enterContext(patch.object(router, 'settings', return_value={'gemini_scopes': []}))
        self.enterContext(patch.object(router.privacy, 'mode', return_value='normal'))

    def record(self, provider, model):
        key = router._health_key('alice', provider, model)
        router._HEALTH[key] = {'until': time.monotonic() + 30, 'error': 'LocalModelError'}
        return key

    def test_ollama_key_does_not_hash_mutable_provider_configuration(self):
        config = {'provider': 'auto', 'backend': 'ollama',
                  'url': 'http://127.0.0.1:11434', 'model': 'one'}
        with patch.object(llm, 'provider_configuration', return_value=config):
            recorded = self.record('ollama', '*')
        config.update(provider='gemini', model='two')
        with patch.object(llm, 'provider_configuration', return_value=config):
            self.assertEqual(router._health_key('alice', 'ollama', '*'), recorded)
            self.assertGreater(router._health_wait('alice', 'ollama', 'local-test'), 0)

    def test_auto_gemini_selection_still_reads_ollama_cooldown(self):
        config = {'provider': 'auto', 'backend': 'ollama',
                  'url': 'http://127.0.0.1:11434', 'model': 'one'}
        with patch.object(llm, 'provider_configuration', return_value=config):
            recorded = self.record('ollama', '*')
        config.update(provider='gemini', model='two')
        with patch.object(llm, 'provider', return_value='gemini'), \
             patch.object(llm, 'provider_configuration', return_value=config):
            self.assertEqual(router._health_key('alice', 'ollama', '*'), recorded)
            self.assertGreater(router._health_wait('alice', 'ollama', 'local-test'), 0)

    def test_failed_ollama_request_is_read_back_outside_the_request(self):
        adapter = Mock(side_effect=llm.LocalModelError('connection failed'))
        request = router.ModelRequest(owner='alice', profile='conversation',
                                      max_network_attempts=1)
        with self.assertRaises(RuntimeError):
            router.run_request(request, adapter)
        adapter.assert_called_once()
        recorded = set(router._HEALTH)
        self.assertEqual(recorded, {router._health_key('alice', 'ollama', '*')})
        self.assertGreater(router._health_wait('alice', 'ollama', 'local-test'), 0)

    def test_local_endpoint_change_does_not_inherit_cooldown(self):
        with patch.object(llm, 'provider_configuration',
                          return_value={'backend': 'ollama', 'url': 'http://a'}):
            remembered = self.record('ollama', '*')
        with patch.object(llm, 'provider_configuration',
                          return_value={'backend': 'ollama', 'url': 'http://b'}):
            self.assertNotEqual(router._health_key('alice', 'ollama', '*'), remembered)
            self.assertEqual(router._health_wait('alice', 'ollama', 'local-test'), 0)

    def test_cloud_credential_change_does_not_inherit_cooldown(self):
        with patch.object(llm, 'user_key', return_value='key-one'):
            self.record('gemini', 'g2')
            self.assertGreater(router._health_wait('alice', 'gemini', 'g2'), 0)
        with patch.object(llm, 'user_key', return_value='key-two'):
            self.assertEqual(router._health_wait('alice', 'gemini', 'g2'), 0)


if __name__ == '__main__':
    unittest.main()