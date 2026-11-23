"""Ollama kuruluysa kullanılır, kurulu değilse sistem ona bağlı kalmaz.

Kullanıcı kararı (23 Kasım): "ollama kurulu ise istediği gibi kullansın, sistem
kurulu değilse ona bağlı kalmasın."

Kilitlenen davranış:
* Kurulu değilken yerel port yoklaması HIZLI biter (yerel bağlantı 0,4 sn) ve
  boş sonuç önbelleğe alınır; tur saniyelerce beklemez.
* Yerel model yoksa sağlayıcı listesinde olması turu düşürmez; bulut yolu çalışır.
* Yerel modda (yerel/gizli) bulut kapalıyken ollama aday olarak kalır.
"""
import time
import unittest
from unittest.mock import patch

from modules import llm


class NotInstalled(unittest.TestCase):
    def test_missing_local_server_fails_fast(self):
        dead = {"url": "http://127.0.0.1:59999", "backend": "ollama", "model": "yok"}
        with patch.object(llm, "_cfg", return_value=dead), \
             patch.object(llm, "_backend", return_value="ollama"), \
             patch.object(llm, "_ollama_tags_cache", {}):
            started = time.monotonic()
            self.assertEqual(llm.ollama_models(force=True), [])
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 2.0, "kurulu olmayan Ollama turu bekletmemeli")

    def test_missing_result_is_cached(self):
        dead = {"url": "http://127.0.0.1:59999", "backend": "ollama", "model": "yok"}
        cache = {}
        with patch.object(llm, "_cfg", return_value=dead), \
             patch.object(llm, "_backend", return_value="ollama"), \
             patch.object(llm, "_ollama_tags_cache", cache):
            llm.ollama_models(force=True)
            started = time.monotonic()
            llm.ollama_models()
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.05, "boş sonuç önbellekten gelmeli (tekrar yoklama yok)")

    def test_local_hint_points_to_install(self):
        self.assertIn("Ollama", llm.local_hint())


class Installed(unittest.TestCase):
    def test_local_models_are_listed(self):
        config = {"url": "http://127.0.0.1:11434", "backend": "ollama", "model": "qwen2.5:3b"}

        class _Tags:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"models": [{"name": "qwen2.5:3b"}]}

        with patch.object(llm, "_cfg", return_value=config), \
             patch.object(llm, "_backend", return_value="ollama"), \
             patch.object(llm, "_ollama_tags_cache", {}), \
             patch.object(llm.requests, "get", return_value=_Tags()):
            self.assertEqual(llm.ollama_models(force=True), ["qwen2.5:3b"])

    def test_router_keeps_local_candidate(self):
        from modules import smart_router
        with patch.object(smart_router, "_health_wait", return_value=0), \
             patch.object(smart_router, "_ready_unavailable", return_value=None):
            plan = smart_router._selection("owner", "conversation")
        self.assertIn("ollama", plan["candidates"])


if __name__ == "__main__":
    unittest.main()
