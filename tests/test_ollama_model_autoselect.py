import unittest
from unittest.mock import Mock, patch

from modules import llm


class OllamaInstalledModelAutoselectTests(unittest.TestCase):
    def _cfg(self, model="llama3.2", backend="ollama"):
        return {
            "provider": "ollama",
            "backend": backend,
            "url": "http://127.0.0.1:11434" if backend == "ollama" else "http://127.0.0.1:1234/v1",
            "model": model,
        }

    def test_stale_user_model_falls_back_to_installed_ollama_model(self):
        posted = {}
        reply = Mock(status_code=200, content=b"{}")
        reply.json.return_value = {"message": {"content": "tamam"}}

        def post(_url, **kwargs):
            posted.update(kwargs["json"])
            return reply

        with patch.object(llm, "_cfg", return_value=self._cfg("llama3.2")), \
             patch.object(llm, "_choice", return_value={"local_model": "llama3.2"}), \
             patch.object(llm, "load_settings", return_value={"ollama_model": "llama3.2"}), \
             patch.object(llm, "ollama_models", return_value=["qwen2.5-coder:7b"]), \
             patch.object(llm.requests, "post", side_effect=post), \
             patch.object(llm.usage_meter, "record"):
            self.assertEqual(llm._ollama([{"role": "user", "content": "merhaba"}], "", 20), "tamam")

        self.assertEqual(posted["model"], "qwen2.5-coder:7b")

    def test_installed_user_model_is_preserved(self):
        c = self._cfg("qwen2.5-coder:7b")
        with patch.object(llm, "_choice", return_value={"local_model": "qwen2.5-coder:7b"}), \
             patch.object(llm, "load_settings", return_value={"ollama_model": "llama3.2"}), \
             patch.object(llm, "ollama_models", return_value=["qwen2.5-coder:7b"]):
            self.assertEqual(llm._ollama_effective_model(c), "qwen2.5-coder:7b")

    def test_installed_setting_model_is_used_without_user_override(self):
        c = self._cfg("mistral:7b")
        with patch.object(llm, "_choice", return_value={}), \
             patch.object(llm, "load_settings", return_value={"ollama_model": "mistral:7b"}), \
             patch.object(llm, "ollama_models", return_value=["mistral:7b", "qwen2.5-coder:7b"]):
            self.assertEqual(llm._ollama_effective_model(c), "mistral:7b")

    def test_single_installed_model_is_used_when_no_selection_matches(self):
        c = self._cfg("llama3.2")
        with patch.object(llm, "_choice", return_value={}), \
             patch.object(llm, "load_settings", return_value={}), \
             patch.object(llm, "ollama_models", return_value=["qwen2.5-coder:7b"]):
            self.assertEqual(llm._ollama_effective_model(c), "qwen2.5-coder:7b")

    def test_multiple_installed_models_choose_sorted_first_deterministically(self):
        c = self._cfg("llama3.2")
        with patch.object(llm, "_choice", return_value={"local_model": "llama3.2"}), \
             patch.object(llm, "load_settings", return_value={"ollama_model": "llama3.2"}), \
             patch.object(llm, "ollama_models", return_value=["mistral:7b", "qwen2.5-coder:7b"]):
            self.assertEqual(llm._ollama_effective_model(c), "mistral:7b")

    def test_no_installed_model_fails_closed(self):
        c = self._cfg("llama3.2")
        with patch.object(llm, "ollama_models", return_value=[]), \
             patch.object(llm, "local_hint", return_value="yerel model yok"):
            with self.assertRaises(llm.LocalModelError):
                llm._ollama_effective_model(c)

    def test_openai_compatible_local_backends_keep_existing_resolution(self):
        c = self._cfg("configured-model", backend="lmstudio")
        with patch.object(llm, "ollama_models") as models:
            self.assertEqual(llm._ollama_effective_model(c), "configured-model")
        models.assert_not_called()

    def test_local_info_exposes_stale_preference_and_effective_model(self):
        with patch.object(llm, "_cfg", return_value=self._cfg("llama3.2")), \
             patch.object(llm, "_choice", return_value={"local_model": "llama3.2"}):
            info = llm.local_info(installed_models=["qwen2.5-coder:7b"])
        self.assertEqual(info["local_model_preference"], "llama3.2")
        self.assertEqual(info["local_effective_model"], "qwen2.5-coder:7b")
        self.assertTrue(info["local_model_stale"])
        self.assertIn("qwen2.5-coder:7b", info["local_model_warning"])

    def test_local_info_valid_preference_has_no_warning(self):
        with patch.object(llm, "_cfg", return_value=self._cfg("qwen2.5-coder:7b")), \
             patch.object(llm, "_choice", return_value={"local_model": "qwen2.5-coder:7b"}):
            info = llm.local_info(installed_models=["qwen2.5-coder:7b"])
        self.assertEqual(info["local_effective_model"], "qwen2.5-coder:7b")
        self.assertFalse(info["local_model_stale"])
        self.assertEqual(info["local_model_warning"], "")

    def test_local_info_no_installed_model_does_not_invent_active_model(self):
        with patch.object(llm, "_cfg", return_value=self._cfg("llama3.2")), \
             patch.object(llm, "_choice", return_value={"local_model": "llama3.2"}):
            info = llm.local_info(installed_models=[])
        self.assertEqual(info["local_model_preference"], "llama3.2")
        self.assertEqual(info["local_effective_model"], "")
        self.assertFalse(info["local_model_stale"])

    def test_local_info_openai_compatible_backend_keeps_existing_view(self):
        with patch.object(llm, "_cfg", return_value=self._cfg("configured-model", backend="lmstudio")):
            info = llm.local_info(installed_models=["other-model"])
        self.assertEqual(info["ollama_model"], "configured-model")
        self.assertEqual(info["local_effective_model"], "configured-model")
        self.assertFalse(info["local_model_stale"])
        self.assertEqual(info["local_model_warning"], "")


if __name__ == "__main__":
    unittest.main()
