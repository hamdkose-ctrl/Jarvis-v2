"""Brain bağlamı sohbet sıfırlamasını çeviri modülüne bağımlı olmadan okur."""
import inspect
import json
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
        self.enterContext(patch.object(conversation_reset, "_reset_file", self.temp_path))
        self.enterContext(patch.object(conversation_reset, "_resets", {}))

    def test_recent_drops_rows_before_reset_and_keeps_all_without_one(self):
        rows = [{"ts": "2026-01-01 10:00:00", "text": "a"}, {"ts": "2026-01-01 12:00:00", "text": "b"}]
        with patch.dict(conversation_reset._resets, {"u": "2026-01-01 11:00:00.000000"}, clear=True):
            self.assertEqual([r["text"] for r in conversation_reset.recent("u", rows)], ["b"])
            self.assertEqual(conversation_reset.recent("other", rows), rows)

    def test_two_stale_process_snapshots_cannot_erase_another_reset(self):
        conversation_reset.mark("alice")
        saved = conversation_reset._resets["alice"]
        # A second process may have imported before Alice's reset.
        conversation_reset._resets.clear()
        conversation_reset.mark("bob")
        self.assertEqual(conversation_reset._resets["alice"], saved)
        self.assertIn("bob", conversation_reset._resets)
        self.assertEqual(json.loads(self.temp_path.read_text())["alice"], saved)

    def test_failed_durable_reset_preserves_existing_owner_and_cleans_staging(self):
        conversation_reset.mark("alice")
        old_bytes = self.temp_path.read_bytes()
        with patch.object(conversation_reset.os, 'replace',
                          side_effect=OSError('disk failed')):
            with self.assertRaises(OSError):
                conversation_reset.mark("bob")
        self.assertEqual(self.temp_path.read_bytes(), old_bytes)
        self.assertEqual(set(conversation_reset._resets), {"alice"})
        self.assertFalse(list(self.temp_path.parent.glob('.chat-sessions-*')))

    def test_busy_reset_does_not_leak_pre_reset_context(self):
        from modules import file_resource_guard, resource_leases
        conversation_reset.mark("alice")
        before = self.temp_path.read_bytes()
        with file_resource_guard.claim_paths(self.temp_path):
            with self.assertRaises(resource_leases.LeaseConflict):
                conversation_reset.mark("bob")
            self.assertEqual(
                conversation_reset.recent("alice", [{"ts": "2024-01-01", "text": "old"}]),
                [],
            )
        self.assertEqual(self.temp_path.read_bytes(), before)

    def test_recent_checks_disk_even_if_unclaimed_existence_check_would_miss(self):
        # A peer can publish a reset after a naive path.exists() preflight.
        # History must be checked under the actual cross-process claim.
        self.temp_path.write_text(json.dumps({
            'alice': '2026-01-01 11:00:00.000000',
        }), encoding='utf-8')
        original_exists = Path.exists
        with patch.object(Path, 'exists', lambda path:
                          False if path == self.temp_path else original_exists(path)):
            self.assertEqual(conversation_reset.recent('alice', [
                {'ts': '2026-01-01 10:00:00', 'text': 'old'},
                {'ts': '2026-01-01 12:00:00', 'text': 'new'},
            ]), [{'ts': '2026-01-01 12:00:00', 'text': 'new'}])

    def test_external_file_disappearance_cannot_erase_known_cutoff(self):
        conversation_reset.mark('alice')
        cutoff = conversation_reset._resets['alice']
        self.temp_path.unlink()
        self.assertEqual(conversation_reset.recent('alice', [
            {'ts': '2024-01-01', 'text': 'old'},
        ]), [])
        conversation_reset.mark('bob')
        self.assertEqual(json.loads(self.temp_path.read_text())['alice'], cutoff)

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
