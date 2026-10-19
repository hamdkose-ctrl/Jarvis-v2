import unittest

from modules import privacy


class UnlabeledPrivacyTests(unittest.TestCase):
    def test_flexible_secret_labels_redact_values(self):
        cases = {
            "sifre Qw8!zT3pLm9": "sifre [gizli değer gizlendi]",
            "api anahtarım şu: 9fA3kLm2Xq7Rt0Zb4Vn8": "api anahtarım şu: [gizli değer gizlendi]",
            "parola olarak tK9#vL2$mQ4x kullan": "parola olarak [gizli değer gizlendi] kullan",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(privacy.redact(raw, force=True), expected)

    def test_flexible_secret_labels_do_not_mask_ordinary_text(self):
        unchanged = [
            "şifre sıfırlama bağlantısını aç",
            "api anahtarım şu bölümde anlatılıyor",
            "parola olarak güçlü bir ifade kullan",
            "Telegram kodu 482913",
        ]
        for raw in unchanged:
            with self.subTest(raw=raw):
                self.assertEqual(privacy.redact(raw, force=True), raw)

    def test_long_mixed_tokens_are_redacted(self):
        cases = [
            "Durum SESSION_CANARY_UNRECOGNIZED_XYZ",
            "kimlik Ab9_Xy7-Pq2_Rs8-Tu4",
            "değer 9fA3kLm2Xq7Rt0Zb4Vn8",
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                masked = privacy.redact(raw, force=True)
                self.assertIn("[gizli değer gizlendi]", masked)
                self.assertNotEqual(masked, raw)

    def test_long_mixed_rule_preserves_false_positive_boundaries(self):
        unchanged = [
            "toplantı saat 14:30 oda 3042",
            "normal Türkçe cümle ve açıklama metni",
            "https://example.com/docs/v2.3.1",
            r"C:\\Users\\Hamdi\\Documents\\rapor-v2.3.1.txt",
            "sürüm v2.3.1 tarih 2026-10-19 saat 14:30",
            "550e8400e29b41d4a716446655440000",
            "kısa A1_b2",
        ]
        for raw in unchanged:
            with self.subTest(raw=raw):
                self.assertEqual(privacy.redact(raw, force=True), raw)

    def test_existing_phone_card_and_telegram_behavior_is_preserved(self):
        self.assertEqual(privacy.redact("0532 123 45 67", force=True), "[telefon gizlendi]")
        self.assertEqual(privacy.redact("4111 1111 1111 1111", force=True), "[kart gizlendi]")
        self.assertEqual(privacy.redact("Telegram kodu 482913", force=True), "Telegram kodu 482913")


if __name__ == "__main__":
    unittest.main()
