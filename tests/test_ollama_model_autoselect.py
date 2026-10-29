from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modules import llm
from web_models import WebModels


class OllamaInstalledModelAutoselectTests(unittest.TestCase):
    def _cfg(self, model="llama3.2", backend="ollama"):
        return {
            "provider": "ollama",
            "backend": backend,
            "url": "http://127.0.0.1:11434" if backend == "ollama" else "http://127.0.0.1:1234/v1",
            "model": model,
        }

    def _ui_status(self, *, backend="ollama", preference="llama3.2", installed=None, effective=None, fail=False):
        installed = list(installed or [])
        stub = SimpleNamespace(
            status=lambda: {
                "local_backend": backend,
                "ollama_model": preference,
                "ollama_models": installed,
            },
            provider_configuration=lambda: self._cfg(preference, backend=backend),
            LocalModelError=llm.LocalModelError,
        )
        resolver = Mock()
        if fail:
            resolver.side_effect = llm.LocalModelError("yerel model yok")
        else:
            resolver.return_value = effective if effective is not None else preference
        stub._ollama_effective_model = resolver
        bridge = WebModels()
        bridge._runtime = SimpleNamespace(llm=stub)
        return bridge.llm_status(), resolver

    def _choice_bridge(self, *, backend="ollama", installed=None):
        installed = list(installed or [])
        choose = Mock(return_value={})
        stub = SimpleNamespace(
            status=lambda: {
                "local_backend": backend,
                "ollama_models": installed,
            },
            choose_model=choose,
        )
        bridge = WebModels()
        bridge._runtime = SimpleNamespace(
            llm=stub,
            _p=lambda: SimpleNamespace(slug="hamdi", name="Hamdi"),
            privacy=SimpleNamespace(audit=Mock()),
        )
        return bridge, choose

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

    def test_ui_status_exposes_stale_preference_and_effective_model(self):
        info, resolver = self._ui_status(
            preference="llama3.2",
            installed=["qwen2.5-coder:7b"],
            effective="qwen2.5-coder:7b",
        )
        self.assertEqual(info["local_model_preference"], "llama3.2")
        self.assertEqual(info["local_effective_model"], "qwen2.5-coder:7b")
        self.assertTrue(info["local_model_stale"])
        self.assertEqual(info["local_model_warning"], "Kayıtlı tercih kurulu olmadığı için aktif model otomatik seçildi.")
        resolver.assert_called_once()

    def test_ui_status_valid_preference_has_no_warning(self):
        info, _ = self._ui_status(
            preference="qwen2.5-coder:7b",
            installed=["qwen2.5-coder:7b"],
            effective="qwen2.5-coder:7b",
        )
        self.assertEqual(info["local_effective_model"], "qwen2.5-coder:7b")
        self.assertFalse(info["local_model_stale"])
        self.assertEqual(info["local_model_warning"], "")

    def test_ui_status_default_latest_alias_is_not_stale(self):
        info, _ = self._ui_status(preference="llama3.2", installed=["gemma3:4b", "llama3.2:latest"], effective="llama3.2:latest")
        self.assertFalse(info["local_model_stale"])
        self.assertEqual(info["local_effective_model"], "llama3.2:latest")

    def test_ui_status_no_installed_model_does_not_invent_active_model(self):
        info, _ = self._ui_status(preference="llama3.2", installed=[], fail=True)
        self.assertEqual(info["local_model_preference"], "llama3.2")
        self.assertEqual(info["local_effective_model"], "")
        self.assertEqual(info["local_installed_models"], [])
        self.assertFalse(info["local_model_select_enabled"])
        self.assertFalse(info["local_model_stale"])
        self.assertTrue(info["local_models_checked"])

    def test_ui_status_openai_compatible_backend_uses_effective_resolver(self):
        info, resolver = self._ui_status(
            backend="lmstudio",
            preference="configured-model",
            installed=["configured-model", "other-model"],
            effective="configured-model",
        )
        self.assertEqual(info["local_effective_model"], "configured-model")
        self.assertEqual(info["local_installed_models"], ["configured-model", "other-model"])
        self.assertFalse(info["local_model_stale"])
        self.assertEqual(info["local_model_warning"], "")
        resolver.assert_called_once()

    def test_status_exposes_single_installed_model(self):
        info, _ = self._ui_status(
            preference="llama3.2",
            installed=["qwen2.5-coder:7b"],
            effective="qwen2.5-coder:7b",
        )
        self.assertEqual(info["local_installed_models"], ["qwen2.5-coder:7b"])
        self.assertTrue(info["local_model_select_enabled"])

    def test_status_exposes_canonical_installed_model_list(self):
        info, _ = self._ui_status(
            preference="llama3.2",
            installed=["mistral:7b", "qwen2.5-coder:7b"],
            effective="mistral:7b",
        )
        self.assertEqual(info["local_installed_models"], ["mistral:7b", "qwen2.5-coder:7b"])

    def test_installed_local_model_can_be_saved(self):
        bridge, choose = self._choice_bridge(installed=["qwen2.5-coder:7b"])
        out = bridge.model_choice_save("ollama", "qwen2.5-coder:7b")
        self.assertTrue(out["ok"])
        choose.assert_called_once_with("hamdi", "ollama", "qwen2.5-coder:7b")

    def test_uninstalled_local_model_cannot_be_saved(self):
        bridge, choose = self._choice_bridge(installed=["qwen2.5-coder:7b"])
        out = bridge.model_choice_save("ollama", "llama3.2")
        self.assertFalse(out["ok"])
        choose.assert_not_called()

    def test_lmstudio_installed_model_can_be_saved(self):
        bridge, choose = self._choice_bridge(backend="lmstudio", installed=["configured-model", "server-model"])
        out = bridge.model_choice_save("ollama", "configured-model")
        self.assertTrue(out["ok"])
        choose.assert_called_once_with("hamdi", "ollama", "configured-model")

    def test_llamacpp_installed_model_can_be_saved(self):
        bridge, choose = self._choice_bridge(backend="llamacpp", installed=["gguf-model"])
        out = bridge.model_choice_save("ollama", "gguf-model")
        self.assertTrue(out["ok"])
        choose.assert_called_once_with("hamdi", "ollama", "gguf-model")

    def test_other_local_backend_uninstalled_model_is_rejected(self):
        bridge, choose = self._choice_bridge(backend="lmstudio", installed=["server-model"])
        out = bridge.model_choice_save("ollama", "missing-model")
        self.assertFalse(out["ok"])
        choose.assert_not_called()

    def test_ui_render_contract_uses_backend_installed_models_dropdown(self):
        src = (Path(__file__).parents[1] / "webui" / "local-model-panel.js").read_text(encoding="utf-8")
        self.assertIn("local_installed_models", src)
        self.assertIn("models.map", src)
        self.assertIn("Aktif Model", src)
        self.assertIn("Kurulu Modeller", src)
        self.assertIn("<select", src)
        self.assertIn('data-act="localmodelsave"', src)
        self.assertIn("Modeli Kaydet", src)
        self.assertIn("local_model_select_enabled", src)
        self.assertNotIn("qwen2.5-coder:7b</option>", src)
        self.assertNotIn("llama3.2</option>", src)

    def test_ui_stale_preference_is_info_not_active_value(self):
        src = (Path(__file__).parents[1] / "webui" / "local-model-panel.js").read_text(encoding="utf-8")
        self.assertIn("local_model_preference", src)
        self.assertIn("local_effective_model", src)
        self.assertIn("Kayıtlı tercih kurulu olmadığı için aktif model otomatik seçildi.", src)
        self.assertIn("local_model_stale", src)


if __name__ == "__main__":
    unittest.main()
