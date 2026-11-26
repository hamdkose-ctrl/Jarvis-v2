"""413 kırpma: aşırı büyük gövde bir kez küçültülür, yedek sağlayıcı gerçekten denenir.

Canlı ölçüm (26 Kasım): 753 istekte 12× 413. Aynı gövde yedek sağlayıcıya aynen gittiği
için o da 413 veriyordu; kırpma bu döngüyü kırar.
"""
import unittest

from modules import llm


class Trim(unittest.TestCase):
    def _msgs(self, turns=10):
        return [{"role": "system", "content": "sistem"}] + [
            {"role": "user", "content": f"t{i}"} for i in range(turns)]

    def test_keeps_system_and_last_turns(self):
        trimmed = llm.trim_for_request_limit(self._msgs(), keep=4)
        self.assertEqual(trimmed[0]["content"], "sistem")
        self.assertEqual([m["content"] for m in trimmed[1:]], ["t6", "t7", "t8", "t9"])

    def test_small_body_is_not_trimmed(self):
        self.assertIsNone(llm.trim_for_request_limit(self._msgs(turns=2), keep=4))

    def test_no_system_message_is_supported(self):
        rows = [{"role": "user", "content": f"t{i}"} for i in range(8)]
        trimmed = llm.trim_for_request_limit(rows, keep=2)
        self.assertEqual([m["content"] for m in trimmed], ["t6", "t7"])

    def test_trim_never_returns_more_than_input(self):
        msgs = self._msgs(turns=5)
        trimmed = llm.trim_for_request_limit(msgs, keep=4)
        self.assertLessEqual(len(trimmed), len(msgs))


if __name__ == "__main__":
    unittest.main()
