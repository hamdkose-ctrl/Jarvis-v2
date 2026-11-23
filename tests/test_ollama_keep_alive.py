"""Yerel model sıcak tutulur: soğuk yükleme yedeği kaybettirmesin.

Canlı kusur (23 Kasım 22:22): Ollama yanıtı zaman aşımına uğradı; hemen ardından
bulut sağlayıcıları da tükendi ve Jarvis "model kullanılamıyor" dedi. Ollama
modeli 5 dakika boşta boşaltıyor; soğuk yükleme CPU yükü altında okuma süresini
aşıyor. Çözüm: `keep_alive` ile model sıcak, okuma süresi 90 sn.
"""
import unittest
from unittest.mock import patch

from modules import llm


class _Response:
    status_code = 200
    content = b"{}"

    def json(self):
        return {"message": {"content": "tamam"}, "done_reason": "stop"}


class KeepAlive(unittest.TestCase):
    def _capture(self):
        captured = {}

        def fake_post(url, timeout=None, json=None, **rest):
            captured["url"] = url
            captured["timeout"] = timeout
            captured["json"] = json
            return _Response()

        return captured, fake_post

    def test_request_keeps_model_warm(self):
        captured, fake_post = self._capture()
        config = {"url": "http://127.0.0.1:11434", "model": "qwen2.5:3b"}
        with patch.object(llm, "provider_configuration", return_value=config), \
             patch.object(llm.requests, "post", side_effect=fake_post), \
             patch.object(llm, "_ollama_effective_model", return_value="qwen2.5:3b"), \
             patch.object(llm.usage_meter, "record"), \
             patch.object(llm.usage_meter, "observe_response"), \
             patch.object(llm.usage_meter, "size", return_value=10), \
             patch.object(llm.usage_meter, "tokens_from", return_value=None):
            text = llm._ollama([{"role": "user", "content": "selam"}], "", 40, model="qwen2.5:3b")
        self.assertEqual(text, "tamam")
        self.assertEqual(captured["json"]["keep_alive"], "30m")
        self.assertGreaterEqual(captured["timeout"][1], 90)

    def test_num_predict_is_still_passed(self):
        captured, fake_post = self._capture()
        with patch.object(llm.requests, "post", side_effect=fake_post), \
             patch.object(llm, "_ollama_effective_model", return_value="qwen2.5:3b"), \
             patch.object(llm.usage_meter, "record"), \
             patch.object(llm.usage_meter, "observe_response"), \
             patch.object(llm.usage_meter, "size", return_value=10), \
             patch.object(llm.usage_meter, "tokens_from", return_value=None):
            llm._ollama([{"role": "user", "content": "selam"}], "", 77, model="qwen2.5:3b")
        self.assertEqual(captured["json"]["options"]["num_predict"], 77)


if __name__ == "__main__":
    unittest.main()
