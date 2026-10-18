import unittest

from modules import privacy


class LabeledSecretRedactionTests(unittest.TestCase):
    def test_labeled_values_are_redacted_but_labels_remain(self):
        cases = {
            "oturum_belirteci=SESSION_CANARY_UNRECOGNIZED_XYZ": "oturum_belirteci=[gizli değer gizlendi]",
            "token: abc123XYZ789": "token: [gizli değer gizlendi]",
            "Parola = Gizli123!": "Parola = [gizli değer gizlendi]",
            "şifre: Deneme-2026": "şifre: [gizli değer gizlendi]",
            "api_key=ZZZ_not_a_known_prefix_123": "api_key=[gizli değer gizlendi]",
            "secret=abcd1234": "secret=[gizli değer gizlendi]",
            "TOKEN=MixCase987": "TOKEN=[gizli değer gizlendi]",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(privacy.redact(raw, force=True), expected)

    def test_non_secret_label_like_text_is_not_changed(self):
        unchanged = [
            "şifreni unutursan sıfırla",
            "şifre: yok",
            "token: -",
            "https://x.org/token/abc",
            "[anahtar gizlendi]",
            "Sipariş 123456 ve kayıt 20261018",
        ]
        for raw in unchanged:
            with self.subTest(raw=raw):
                self.assertEqual(privacy.redact(raw, force=True), raw)

    def test_existing_phone_and_card_redaction_is_preserved(self):
        self.assertEqual(privacy.redact("0532 123 45 67", force=True), "[telefon gizlendi]")
        self.assertEqual(privacy.redact("4111 1111 1111 1111", force=True), "[kart gizlendi]")


if __name__ == "__main__":
    unittest.main()
