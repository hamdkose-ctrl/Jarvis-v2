"""Anlama bağlam önbelleği: varsayılan kapalı, hata olursa tam isteme dönüş."""
import unittest
from unittest.mock import patch

from modules import understanding_cache


def _ayar(acik):
    return patch('config.load_settings', lambda: {'understanding_cache': acik})


class CacheLifecycleTests(unittest.TestCase):
    def setUp(self):
        understanding_cache.forget()
        self._gercek = understanding_cache._create

    def tearDown(self):
        understanding_cache._create = self._gercek
        understanding_cache.forget()

    def test_disabled_by_default_never_creates_a_cache(self):
        self.assertFalse(understanding_cache.enabled())
        with _ayar(False), patch.object(understanding_cache, '_create',
                                        side_effect=AssertionError('çağrılmamalı')):
            self.assertIsNone(understanding_cache.acquire('hamdi', 'm', 'sözleşme', 'sistem'))

    def test_enabled_reuses_the_same_handle_for_the_same_contract(self):
        cagri = []

        def sahte(owner, model, contract, system):
            cagri.append((owner, model))
            return 'cachedContents/abc'

        with _ayar(True), patch.object(understanding_cache, '_create', side_effect=sahte):
            self.assertEqual(understanding_cache.acquire('hamdi', 'm', 'A', 's'), 'cachedContents/abc')
            self.assertEqual(understanding_cache.acquire('hamdi', 'm', 'A', 's'), 'cachedContents/abc')
        self.assertEqual(cagri, [('hamdi', 'm')])

    def test_a_different_contract_gets_its_own_cache(self):
        ada = iter(['cachedContents/1', 'cachedContents/2'])
        with _ayar(True), patch.object(understanding_cache, '_create', lambda *a: next(ada)):
            self.assertEqual(understanding_cache.acquire('hamdi', 'm', 'A', 's'), 'cachedContents/1')
            self.assertEqual(understanding_cache.acquire('hamdi', 'm', 'B', 's'), 'cachedContents/2')

    def test_creation_failure_returns_none_and_backs_off(self):
        cagri = []

        def patlat(owner, model, contract, system):
            cagri.append(1)
            raise RuntimeError('kota')

        with _ayar(True), patch.object(understanding_cache, '_create', side_effect=patlat):
            self.assertIsNone(understanding_cache.acquire('hamdi', 'm', 'A', 's'))
            # Bekleme penceresi: her turda yeniden denenmez.
            self.assertIsNone(understanding_cache.acquire('hamdi', 'm', 'A', 's'))
        self.assertEqual(len(cagri), 1)

    def test_stats_count_hits_and_misses(self):
        once = understanding_cache.stats()
        understanding_cache.note(True)
        understanding_cache.note(False)
        sonra = understanding_cache.stats()
        self.assertEqual(sonra['hit'] - once['hit'], 1)
        self.assertEqual(sonra['miss'] - once['miss'], 1)

    def test_llm_raises_cache_miss_so_the_caller_can_fall_back(self):
        """Sözleşme verilip önbellek kurulamazsa sessiz yanlış yerine açık sinyal."""
        from modules import llm
        with _ayar(True), patch.object(understanding_cache, '_create', side_effect=RuntimeError('yok')):
            token = llm._CONTRACT.set('S')
            try:
                with self.assertRaises(llm.CacheMissError):
                    llm._send_provider('gemini', 'gövde', 'sistem', 100, None,
                                       model='gemini-3.5-flash-lite')
            finally:
                llm._CONTRACT.reset(token)


class RequestContractTests(unittest.TestCase):
    def test_model_request_carries_no_contract_by_default(self):
        from modules import smart_router
        req = smart_router.ModelRequest(owner='hamdi')
        self.assertIsNone(req.static_contract)


if __name__ == '__main__':
    unittest.main()
