"""Bellek kapısı: sınır, özetleme, sabitler, gönderme çözümü."""
import unittest

from modules import memory_gate as gate


class Limits(unittest.TestCase):
    def test_small_history_is_kept(self):
        self.assertEqual(gate.plan([{"text": "merhaba"}])["action"], "keep")

    def test_long_history_is_summarised(self):
        history = [{"text": "x" * 100} for _ in range(60)]
        result = gate.plan(history)
        self.assertEqual(result["action"], "summarize")
        self.assertEqual(result["keep"], gate.SUMMARY_KEEP)

    def test_char_limit_triggers_summary(self):
        history = [{"text": "y" * 1000} for _ in range(15)]
        self.assertEqual(gate.plan(history)["action"], "summarize")

    def test_summary_text_is_readable(self):
        text = gate.summary_text([{"text": "toplantı notlarını özetle"}])
        self.assertIn("toplantı", text)


class References(unittest.TestCase):
    def test_pronoun_resolves_to_last_real_action(self):
        result = gate.resolve_reference("bunu kaydet", {"target": "toplanti.txt", "window": "Not Defteri"})
        self.assertEqual(result["target"], "toplanti.txt")

    def test_no_previous_action_means_no_guess(self):
        self.assertIsNone(gate.resolve_reference("bunu kaydet", None))

    def test_sentence_without_pronoun_is_not_reference(self):
        self.assertIsNone(gate.resolve_reference("youtube aç", {"target": "x"}))


if __name__ == "__main__":
    unittest.main()
