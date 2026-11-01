"""Brain bağlamı sohbet sıfırlamasını çeviri modülüne bağımlı olmadan okur."""
import inspect
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import brain_context, conversation_reset

ROOT = Path(__file__).resolve().parents[1]


class ConversationResetTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.temp_path = Path(self.temp.name) / "chat_sessions.json"

    def test_recent_drops_rows_before_reset_and_keeps_all_without_one(self):
        rows = [{"ts": "2026-01-01 10:00:00", "text": "a"}, {"ts": "2026-01-01 12:00:00", "text": "b"}]
        with patch.dict(conversation_reset._resets, {"u": "2026-01-01 11:00:00.000000"}, clear=True):
            self.assertEqual([r["text"] for r in conversation_reset.recent("u", rows)], ["b"])
            self.assertEqual(conversation_reset.recent("other", rows), rows)

    def test_active_context_default_filter_is_not_chat_translation(self):
        source = inspect.getsource(brain_context)
        self.assertNotIn("chat_translation", source)
        self.assertIn("conversation_reset.recent", source)

    def test_the_new_chat_door_owns_the_boundary_here(self):
        """'Yeni sohbet' yalnız bu kesiti yazar; çeviride ikinci bir oturum hafızası kalmadı."""
        source = (ROOT / "web_chat.py").read_text(encoding="utf-8")
        self.assertIn("conversation_reset.mark", source)
        self.assertNotIn("chat_translation", source)

    def test_mark_keeps_the_durable_single_writer_shape(self):
        with patch.object(conversation_reset, "_reset_file", Path(self.temp_path)), \
             patch.object(conversation_reset, "_resets", {}):
            conversation_reset.mark("u")
            self.assertIn("u", conversation_reset._resets)
            self.assertEqual([r["text"] for r in conversation_reset.recent("u", [{"ts": "2026-01-01 10:00:00", "text": "a"}])], [])


if __name__ == "__main__":
    unittest.main()
