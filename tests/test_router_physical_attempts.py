"""Gemini router physical-attempt contract; no live provider traffic or secrets."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import llm


class RouterPhysicalAttemptTests(unittest.TestCase):
    def test_gemini_request_uses_remaining_timeout_without_sdk_retry(self):
        from modules import requests_state

        chat = SimpleNamespace(send_message=lambda _text: SimpleNamespace(text='OK', candidates=[]))
        api = SimpleNamespace(chats=SimpleNamespace(create=Mock(return_value=chat)))
        with patch.object(llm, '_cli', return_value=api), \
             patch.object(llm.privacy, 'mode', return_value='normal'), \
             patch.object(llm.usage_meter, 'record'), requests_state.budget(12):
            self.assertEqual(llm._send_provider('gemini', 'ping', '', 32, [], model='gemini-test'), 'OK')
        options = api.chats.create.call_args.kwargs['config'].http_options
        self.assertGreater(options.timeout, 0)
        self.assertLessEqual(options.timeout, 12_000)
        self.assertEqual(options.retry_options.attempts, 1)

    def test_global_and_runtime_gemini_clients_disable_sdk_retries(self):
        # Tek sahip _gemini_http_options(): global istemci modül yüklenirken, kullanıcı
        # istemcisi _cli() içinde bu seçeneklerle kurulur. Çalışma zamanı anahtar değişimi
        # kişiye özel anahtar sahipliğine taşındığı için ayrı bir kurucu yoktur.
        opts = llm._gemini_http_options()
        self.assertEqual(opts["timeout"], 45000)
        self.assertEqual(opts["retry_options"]["attempts"], 1)
        self.assertIsNot(opts, llm._gemini_http_options())
        src = Path(llm.__file__).read_text(encoding="utf-8")
        self.assertIn("_client = genai.Client(api_key=API_KEY, http_options=_gemini_http_options())", src)
        self.assertNotIn("def set_api_key(", src)
        with patch.object(llm, "_user_clients", {}), \
             patch.object(llm, "user_key", return_value="alice-key"), \
             patch.object(llm.genai, "Client") as ctor:
            llm.set_user_context("alice")
            try:
                self.assertIs(llm._cli(), llm._cli())
                ctor.assert_called_once()
                self.assertEqual(ctor.call_args.kwargs["http_options"]["retry_options"], {"attempts": 1})
                self.assertEqual(ctor.call_args.kwargs["api_key"], "alice-key")
            finally:
                llm.set_user_context(None)

    def _send(self, send_message):
        fake = SimpleNamespace(chats=SimpleNamespace(
            create=lambda **_kwargs: SimpleNamespace(send_message=send_message)))
        with patch.object(llm, "_cli", return_value=fake), \
             patch.object(llm, "current_user", return_value="alice"), \
             patch.object(llm.privacy, "mode", return_value="normal"), \
             patch.object(llm.privacy, "redact", side_effect=lambda text: text), \
             patch.object(llm.usage_meter, "record") as meter:
            try:
                result = llm._send_provider("gemini", "prompt", "system", 32,
                                            None, model="router-selected")
                return result, meter.call_args_list
            except Exception:
                return None, meter.call_args_list

    def test_routed_success_counts_one_physical_attempt(self):
        send = Mock(return_value=SimpleNamespace(text="ok", usage_metadata=None))
        result, calls = self._send(send)
        self.assertEqual(result, "ok")
        send.assert_called_once_with("prompt")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args, ("gemini", "router-selected", 12, 2))
        self.assertEqual(calls[0].kwargs.get("tokens"), None)

    def test_routed_failed_http_attempt_is_metered_once_and_rethrown(self):
        problem = llm.errors.ClientError(
            429, {"error": {"message": "quota limit", "status": "RESOURCE_EXHAUSTED"}})
        send = Mock(side_effect=problem)
        fake = SimpleNamespace(chats=SimpleNamespace(
            create=lambda **_kwargs: SimpleNamespace(send_message=send)))
        with patch.object(llm, "_cli", return_value=fake), \
             patch.object(llm, "current_user", return_value="alice"), \
             patch.object(llm.privacy, "mode", return_value="normal"), \
             patch.object(llm.privacy, "redact", side_effect=lambda text: text), \
             patch.object(llm.usage_meter, "record") as meter:
            with self.assertRaises(llm.errors.ClientError):
                llm._send_provider("gemini", "prompt", "system", 32, None,
                                   model="router-selected")
        send.assert_called_once_with("prompt")
        meter.assert_called_once()
        self.assertEqual(meter.call_args.args[:5],
                         ("gemini", "router-selected", 12, 0, "429"))

    def test_exact_model_adapter_failure_has_no_hidden_model_loop(self):
        problem = llm.errors.ClientError(
            429, {"error": {"message": "quota limit", "status": "RESOURCE_EXHAUSTED"}})
        send = Mock(side_effect=problem)
        fake = SimpleNamespace(chats=SimpleNamespace(
            create=lambda **_kwargs: SimpleNamespace(send_message=send)))
        with patch.object(llm, "_cli", return_value=fake), \
             patch.object(llm, "current_user", return_value="alice"), \
             patch.object(llm, "model_names", return_value=["fallback-model"]), \
             patch.object(llm, "_rate_limited", {}), \
             patch.object(llm, "_fallback_states", {}), \
             patch.object(llm.privacy, "mode", return_value="normal"), \
             patch.object(llm.privacy, "redact", side_effect=lambda text: text), \
             patch.object(llm.usage_meter, "record") as meter:
            with self.assertRaises(llm.errors.ClientError):
                llm._send_provider("gemini", "prompt", "system", 32, None,model="fallback-model")
        send.assert_called_once()
        meter.assert_called_once()


if __name__ == "__main__":
    unittest.main()
