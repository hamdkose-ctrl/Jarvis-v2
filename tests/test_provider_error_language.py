"""#350: sağlayıcı hatası kullanıcıya insan diliyle gider.

Canlı ölçüm (22 Kasım 2026, 15:02) kullanıcıya şu metni verdi:

    "Uygun modelden yanıt alınamadı. groq: kota veya hız sınırı (LocalModelError);
     cloudflare: çağrı başarısız (LocalModelError) Atlanan sağlayıcılar: gemini:
     Önceki çağrı hatası nedeniyle bağlantı kısa süre beklemede.."

Sınıf adı, sağlayıcı iç istisnası ve "cooldown" jargonu kullanıcıya gidiyordu.
Artık: tek sade cümle + tek öneri; teknik ayrıntı `exc.detail` içinde kalır.
"""
import unittest

from modules import failure_policy, llm, smart_router

# 15:02'deki gerçek deneme satırları (sağlayıcı, tür, durum).
DENEMELER = [
    {"provider": "groq", "model": "openai/gpt-oss-120b", "ok": False, "error": "LocalModelError",
     "kind": "quota", "status": None},
    {"provider": "cloudflare", "model": "@cf/meta/llama", "ok": False, "error": "LocalModelError",
     "kind": "other", "status": None},
]
ATLANAN = [{"provider": "gemini", "reason": "Önceki çağrı hatası nedeniyle bağlantı kısa süre beklemede"}]


class PlainTextTests(unittest.TestCase):
    def test_no_class_name_or_http_code_in_user_text(self):
        for kind in ("key", "quota", "request_limit", "timeout", "response_validation", "other"):
            text = failure_policy.plain_reason(kind)
            self.assertNotIn("Error", text)
            self.assertNotIn("HTTP", text)
            self.assertNotIn("(", text)
            self.assertTrue(text.strip())

    def test_each_failure_kind_is_described_differently(self):
        kinds = ("key", "quota", "request_limit", "timeout", "other")
        texts = {failure_policy.plain_reason(kind) for kind in kinds}
        self.assertEqual(len(texts), len(kinds))
        self.assertIn("anahtar", failure_policy.plain_reason("key"))
        self.assertIn("kota", failure_policy.plain_reason("quota"))
        self.assertIn("boyut", failure_policy.plain_reason("request_limit"))

    def test_hint_follows_the_measured_cause(self):
        self.assertIn("Bağlantılar", failure_policy.plain_hint({"key"}, recovery_class="user_action_required"))
        self.assertIn("kısalt", failure_policy.plain_hint({"request_limit"}))
        self.assertIn("kota", failure_policy.plain_hint({"quota"}))
        self.assertIn("tekrar dene", failure_policy.plain_hint(set()))


class ExhaustedMessageTests(unittest.TestCase):
    def test_exhausted_message_is_plain_and_keeps_technical_detail_apart(self):
        teknik = "; ".join(smart_router.failure_detail(row) for row in DENEMELER)
        teknik += " Atlanan sağlayıcılar: " + "; ".join(
            row["provider"] + ": " + row["reason"] for row in ATLANAN) + "."
        parcalar = [llm.provider_label(row["provider"]) + ": "
                    + failure_policy.plain_reason(row["kind"]) for row in DENEMELER]
        mesaj = ("Şu an cevap veremiyorum; " + " · ".join(parcalar) + ". "
                 + failure_policy.plain_hint({row["kind"] for row in DENEMELER}))
        exc = failure_policy.ProviderExhaustedError(mesaj, detail=teknik)
        self.assertIn("kota", str(exc))
        self.assertNotIn("LocalModelError", str(exc))
        self.assertNotIn("HTTP", str(exc))
        self.assertNotIn("cooldown", str(exc))
        # Teknik iz kaybolmadı, yalnız kullanıcı metninden ayrıldı.
        self.assertIn("groq:", exc.detail)
        self.assertIn("Atlanan sağlayıcılar", exc.detail)

    def test_five_failure_kinds_stay_distinct_and_free_of_raw_names(self):
        satirlar = [
            {"provider": "gemini", "kind": "quota", "error": "ClientError", "status": 429},
            {"provider": "groq", "kind": "key", "error": "PermissionDeniedError", "status": 401},
            {"provider": "cloudflare", "kind": "other", "error": "Timeout", "status": None},
            {"provider": "ollama", "kind": "request_limit", "error": "ProviderRequestLimitError", "status": 413},
            {"provider": "gemini", "kind": "other", "error": "ConnectionError", "status": None},
        ]
        metinler = [smart_router.user_attempt_text(row) for row in satirlar]
        self.assertIn("kota", metinler[0])
        self.assertIn("kimlik", metinler[1])
        self.assertIn("zaman aşımı", metinler[2])
        self.assertIn("boyut", metinler[3])
        self.assertIn("bağlantı", metinler[4])
        for metin in metinler:
            self.assertNotIn("Error", metin)
            self.assertNotIn("HTTP", metin)

    def test_user_message_never_returns_the_technical_line(self):
        exc = failure_policy.ProviderExhaustedError("Şu an cevap veremiyorum; Gemini: günlük kotası doldu.",
                                                    detail="gemini: kimlik/erişim reddedildi (ClientError, HTTP 400)")
        self.assertNotIn("ClientError", failure_policy.user_message(exc))

    def test_provider_labels_are_used_for_people_not_module_names(self):
        for provider, beklenen in (("gemini", "Gemini"), ("groq", "Groq")):
            self.assertIn(beklenen, llm.provider_label(provider))


if __name__ == "__main__":
    unittest.main()
