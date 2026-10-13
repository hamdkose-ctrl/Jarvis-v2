import time
import unittest
from unittest.mock import Mock, patch


class OllamaStartupTests(unittest.TestCase):
    def test_local_ollama_check_uses_short_connect_timeout_remote_keeps_long(self):
        from modules import llm
        resp = Mock(); resp.raise_for_status = Mock(); resp.json = Mock(return_value={'models': [{'name': 'llama3.2'}]})
        for url, connect in (('http://127.0.0.1:11434', 0.4), ('http://localhost:11434', 0.4), ('http://192.168.1.20:11434', 3)):
            with self.subTest(url=url):
                with patch.object(llm, '_ollama_tags_cache', {}), patch.object(llm, '_cfg', return_value={'url': url}), \
                     patch.object(llm.requests, 'get', return_value=resp) as get:
                    self.assertEqual(llm.ollama_models(), ['llama3.2'])
                    self.assertEqual(get.call_args.kwargs['timeout'], (connect, 3))

    def test_missing_ollama_result_is_cached_longer_so_snapshot_does_not_stall_again(self):
        from modules import llm
        with patch.object(llm, '_ollama_tags_cache', {}), patch.object(llm, '_cfg', return_value={'url': 'http://127.0.0.1:11434'}), \
             patch.object(llm.requests, 'get', side_effect=llm.requests.ConnectionError('kapalı')) as get:
            self.assertEqual(llm.ollama_models(), [])
            now = time.monotonic()
            with patch.object(llm.time, 'monotonic', return_value=now + 10):   # 3 sn'den uzun, 20 sn'den kısa
                self.assertEqual(llm.ollama_models(), [])
            self.assertEqual(get.call_count, 1)
            with patch.object(llm.time, 'monotonic', return_value=now + 25):
                llm.ollama_models()
            self.assertEqual(get.call_count, 2)

    def test_snapshot_ollama_flag_never_waits_for_the_check(self):
        import web
        started = time.time()
        with patch.dict(web._OLLAMA_UP, {'t': 0.0, 'up': False, 'busy': False}), \
             patch.object(web.llm, 'ollama_models', side_effect=lambda *a, **k: (time.sleep(0.8), ['m'])[1]):
            first = web._ollama_up()
            self.assertFalse(first)
            self.assertLess(time.time() - started, 0.5, 'anlık görüntü Ollama kontrolünü beklememeli')
            for _ in range(40):
                if not web._OLLAMA_UP['busy']:
                    break
                time.sleep(0.05)
            self.assertTrue(web._ollama_up(), 'arka plan kontrolü bitince değer güncellenir')


if __name__ == '__main__':
    unittest.main()
