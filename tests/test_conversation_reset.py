"""Brain bağlamı sohbet sıfırlamasını çeviri modülüne bağımlı olmadan okur."""
import inspect
import unittest
from unittest.mock import patch

from modules import brain_context, chat_translation, conversation_reset


class ConversationResetTests(unittest.TestCase):
    def test_recent_drops_rows_before_reset_and_keeps_all_without_one(self):
        rows = [{"ts": "2026-01-01 10:00:00", "text": "a"}, {"ts": "2026-01-01 12:00:00", "text": "b"}]
        with patch.dict(conversation_reset._resets, {"u": "2026-01-01 11:00:00.000000"}, clear=True):
            self.assertEqual([r["text"] for r in conversation_reset.recent("u", rows)], ["b"])
            self.assertEqual(conversation_reset.recent("other", rows), rows)

    def test_active_context_default_filter_is_not_chat_translation(self):
        source = inspect.getsource(brain_context)
        self.assertNotIn("chat_translation", source)
        self.assertIn("conversation_reset.recent", source)

    def test_chat_translation_shares_the_same_reset_state(self):
        self.assertIs(chat_translation._resets, conversation_reset._resets)
        rows = [{"ts": "2026-01-01 10:00:00", "text": "a"}]
        with patch.object(chat_translation, "_resets", {"u": "2026-01-01 11:00:00.000000"}):
            self.assertEqual(chat_translation.recent("u", rows), [])


if __name__ == "__main__":
    unittest.main()
