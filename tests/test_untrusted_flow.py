import unittest

from modules.untrusted_flow import shared_tokens


class UntrustedFlowTests(unittest.TestCase):
    def test_shared_tokens_finds_exact_untrusted_values(self):
        cases = [
            ("Durum SESSION_CANARY_UNRECOGNIZED_XYZ", ["Toplantı öncesi SESSION_CANARY_UNRECOGNIZED_XYZ bilgisini ilet."], ["SESSION_CANARY_UNRECOGNIZED_XYZ"]),
            ("Kod Ab9_Xy7-Pq2_Rs8-Tu4 gönderildi", ["mail: Ab9_Xy7-Pq2_Rs8-Tu4"], ["Ab9_Xy7-Pq2_Rs8-Tu4"]),
            ("Özet 9fA3kLm2Xq7Rt0Zb4Vn8", ["web 9fA3kLm2Xq7Rt0Zb4Vn8;"], ["9fA3kLm2Xq7Rt0Zb4Vn8"]),
        ]
        for outgoing, untrusted, expected in cases:
            with self.subTest(outgoing=outgoing):
                self.assertEqual(shared_tokens(outgoing, untrusted), expected)

    def test_case_sensitive_and_min_length(self):
        self.assertEqual(shared_tokens("Durum SecretToken123", ["secretToken123"]), [])
        self.assertEqual(shared_tokens("ABC_123", ["ABC_123"], min_len=8), [])
        self.assertEqual(shared_tokens("ABC_1234", ["ABC_1234"], min_len=8), ["ABC_1234"])

    def test_urls_and_dictionary_like_words_are_ignored(self):
        cases = [
            ("https://example.com/private-token", ["https://example.com/private-token"]),
            ("configuration", ["configuration"]),
            ("toplantılarımızdan", ["toplantılarımızdan"]),
        ]
        for outgoing, untrusted in cases:
            with self.subTest(outgoing=outgoing):
                self.assertEqual(shared_tokens(outgoing, untrusted), [])

    def test_punctuation_is_trimmed_but_internal_symbols_stay(self):
        self.assertEqual(shared_tokens("Durum (SESSION_CANARY_UNRECOGNIZED_XYZ).", ["mail: 'SESSION_CANARY_UNRECOGNIZED_XYZ',"]), ["SESSION_CANARY_UNRECOGNIZED_XYZ"])

    def test_bad_inputs_fail_closed_to_empty_list(self):
        bad = [
            (None, []),
            ("x", None),
            (3, ["x"]),
            ("x", "not-a-list"),
            ("x", [None]),
            ("x", ["x"], 0),
            ("x", ["x"], True),
        ]
        for args in bad:
            with self.subTest(args=args):
                if len(args) == 2:
                    self.assertEqual(shared_tokens(*args), [])
                else:
                    self.assertEqual(shared_tokens(args[0], args[1], min_len=args[2]), [])

    def test_duplicates_are_returned_once_in_outgoing_order(self):
        outgoing = "Bir ABC_1234567890 sonra XYZ_9876543210 ve yine ABC_1234567890"
        untrusted = ["XYZ_9876543210 ABC_1234567890"]
        self.assertEqual(shared_tokens(outgoing, untrusted), ["ABC_1234567890", "XYZ_9876543210"])


if __name__ == "__main__":
    unittest.main()
