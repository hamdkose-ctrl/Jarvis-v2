"""Bearer sızıntısı ve tekrar maskelemede oluşan artıklar için regresyonlar."""
import unittest

from modules import privacy


class PrivacyMaskGapTests(unittest.TestCase):
    def test_bearer_jwt_and_long_tokens_keep_prefix_and_mask_value(self):
        tokens = ('eyJhbGciOiJIUzI1NiJ9.abc.def', 'aB_9-' * 4,
                  'a' * 19 + 'b', 'abcDEF0123456789+/~_-' + '==')
        for token in tokens:
            for prefix in ('Bearer ', 'Authorization: Bearer ', 'authorization: bearer\t'):
                with self.subTest(token=token, prefix=prefix):
                    raw = prefix + token
                    masked = privacy.redact(raw, force=True)
                    self.assertEqual(masked, prefix + '[gizli değer gizlendi]')
                    self.assertEqual(privacy.redact(masked, force=True), masked)

    def test_all_existing_patterns_are_idempotent(self):
        cases = {
            'alice@example.org': '[e-posta gizlendi]',
            '0532 123 45 67': '[telefon gizlendi]',
            '4111 1111 1111 1111': '[kart gizlendi]',
            '10000000146': '[kimlik no gizlendi]',
            'TR33 0006 1005 1978 6457 8413 26': '[iban gizlendi]',
            'token=abcd1234efgh5678': 'token=[gizli değer gizlendi]',
            'sk-' + 'a' * 28: '[anahtar gizlendi]',
            'token:   abcdefgh': 'token:   [gizli değer gizlendi]',
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                once = privacy.redact(raw, force=True)
                self.assertEqual(once, expected)
                self.assertEqual(privacy.redact(once, force=True), once)

    def test_adjacent_phone_and_card_are_masked_in_one_call(self):
        raw = '0532 123 45 67 4111 1111 1111 1111'
        once = privacy.redact(raw, force=True)
        self.assertEqual(once, '[telefon gizlendi] [kart gizlendi]')
        self.assertEqual(privacy.redact(once, force=True), once)

    def test_labeled_secret_has_exactly_one_mask_without_trailing_residue(self):
        text = 'token=abcd1234efgh5678'
        for _ in range(4):
            text = privacy.redact(text, force=True)
            self.assertEqual(text, 'token=[gizli değer gizlendi]')

    def test_existing_mask_labels_are_preserved_after_secret_label(self):
        for label in ('gizli değer', 'anahtar', 'e-posta', 'iban', 'kart', 'telefon', 'kimlik no'):
            raw = f'token:   [{label} gizlendi]'
            with self.subTest(label=label):
                self.assertEqual(privacy.redact(raw, force=True), raw)

    def test_brackets_do_not_exempt_an_unmasked_labeled_secret(self):
        self.assertEqual(privacy.redact('token=[abcd1234efgh5678]', force=True),
                         'token=[gizli değer gizlendi]')

    def test_ordinary_words_and_short_bearer_values_are_unchanged(self):
        for raw in ('günün sebzesi', 'bearer bonds', 'Bearer kısa', 'Bearer ' + 'a' * 19,
                    'bearer', 'Authorization: Bearer yok', 'şifreni unutursan sıfırla'):
            with self.subTest(raw=raw):
                self.assertEqual(privacy.redact(raw, force=True), raw)


if __name__ == '__main__':
    unittest.main()
