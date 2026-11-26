"""T2: 413 iki farklı hastalıktır ve ayrılmalı; emekli model tipli hatadır.

Canlı kanıt (26 Kasım): "HTTP 413" tek tür sayılıyordu ama Groq aynı kodu **iki** durumda
döndürüyor: (1) gövde modelin istek sınırını aşıyor → kırpma çözümü var; (2) modelin
**tüm dakikalık TPM'i** tek istekle aşılıyor → kırpma çözüm değil, fren/yedek gerekir.
Ayrıca emekli/unknown model adı geçerse sessiz varsayılana taşınmak yerine **tipli hata**
verilir (fail-closed: bilinmeyen → çalıştırma).
"""
import unittest
from unittest import mock

from modules import llm


class RetiredModels(unittest.TestCase):
    def test_unknown_model_raises_typed_error(self):
        with self.assertRaises(llm.RetiredModelError) as caught:
            llm.resolve_groq_model("yeni-model-2029")
        self.assertIn("emekli", str(caught.exception))
        self.assertIn(llm.GROQ_MODELS[0], str(caught.exception))

    def test_known_model_passes_through(self):
        self.assertEqual(llm.resolve_groq_model(llm.GROQ_MODELS[1]), llm.GROQ_MODELS[1])

    def test_empty_falls_back_to_default(self):
        self.assertEqual(llm.resolve_groq_model(""), llm.GROQ_MODELS[0])


class Split413(unittest.TestCase):
    """Gövde çok büyük → kırpılır; TPM aşımı → kırpılmaz (tipli hata)."""

    def _trimmed(self, error_message):
        response = mock.Mock(status_code=413, text=error_message, json=lambda: {
            "error": {"code": "rate_limit_exceeded", "message": error_message}})
        with mock.patch.object(llm.requests, "post", return_value=response) as post, \
             mock.patch.object(llm, "user_groq_key", return_value="k"), \
             mock.patch.object(llm, "_limited", return_value=None), \
             mock.patch.object(llm, "usage_meter", mock.Mock()):
            try:
                llm._groq([{"role": "user", "content": str(i)} for i in range(10)], "sistem", 100)
            except llm.failure_policy.ProviderRequestLimitError as exc:
                return post.call_count, exc
        return post.call_count, None

    def test_body_too_big_is_trimmed_once(self):
        calls, exc = self._trimmed("Request too large for model.")
        self.assertEqual(calls, 2)          # 1 orijinal + 1 kırpılmış tekrar
        self.assertEqual(exc.limit_kind, "request_size")

    def test_tpm_overflow_is_not_trimmed(self):
        calls, exc = self._trimmed(
            "Rate limit reached for model: Limit 6000, Requested 8000 tokens per minute (TPM).")
        self.assertEqual(calls, 1)          # kırpma denemesi yok
        self.assertEqual(exc.limit_kind, "tokens_per_minute")


if __name__ == "__main__":
    unittest.main()
