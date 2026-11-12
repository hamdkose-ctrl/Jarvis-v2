"""BRAIN-03 Taildrop: bounded owner choices reach Core, never raw follow-up.

Tests use temporary owner roots and stubs; no real phone, file transfer or
external network access. This is not full Windows acceptance.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import test_brain_pr3_raw_text_authority as baseline
from modules import brain_core_map, filesend


class TaildropCanonicalStateTests(baseline._CanonicalAuthorityHarness):
    def setUp(self):
        super().setUp()
        root = Path(self.temp.name) / "Downloads"
        root.mkdir()
        self.files = [root / "report-a.pdf", root / "report-b.pdf"]
        for i, path in enumerate(self.files):
            path.write_text(f"test-file-{i}", encoding="utf-8")
        for obj, attr, value in (
            (filesend, "_pending_by_owner", {}),
            (filesend, "_folders", lambda: [root]),
            (filesend, "find", lambda text: list(self.files)),
            (filesend, "_score_gap", lambda text, choices: False),
        ):
            stub = patch.object(obj, attr, value)
            stub.start()
            self.addCleanup(stub.stop)
        self.sent = Mock(return_value="TAILDROP_SENT")
        sender = patch.object(filesend, "send", self.sent)
        sender.start()
        self.addCleanup(sender.stop)

    def open_choice(self, owner=None):
        reply = filesend.handle(
            "rapor dosyasını telefonuma gönder", owner=self.owner if owner is None else owner)
        self.assertIn("hangisini", reply)
        return reply

    def test_numbered_selection_is_a_state_core_effect_once(self):
        self.open_choice()
        entry, result, handler, feedback = self.turn_real("2", model_understanding=False)
        self.assertTrue(entry.state_gate.matched)
        self.assertEqual(entry.state_gate.protocol, "filesend.pending.select")
        self.assertEqual(entry.state_gate.selection, 2)
        self.assertEqual(brain_core_map.state_plan(entry.state_gate.protocol, 2, None),
                         ("filesend_select", {"index": 2}))
        self.assertEqual(result, "TAILDROP_SENT")
        self.assertEqual(feedback.result_status, "handled")
        self.sent.assert_called_once_with(self.files[1])
        handler.assert_not_called()
        self.assertIsNone(filesend.pending_choices(self.owner))
        self.assertIn("süresi doldu", filesend.select_pending(self.owner, 2))
        self.sent.assert_called_once()

    def test_cancel_is_bounded_and_never_calls_raw_selector(self):
        self.open_choice()
        entry, result, handler, feedback = self.turn_real("vazgeç", model_understanding=False)
        self.assertTrue(entry.state_gate.matched)
        self.assertEqual(entry.state_gate.protocol, "filesend.pending.cancel")
        self.assertIn("göndermiyorum", result)
        handler.assert_not_called()
        self.sent.assert_not_called()
        self.assertIsNone(filesend.pending_choices(self.owner))

    def test_other_owner_cannot_read_or_consume_candidates(self):
        self.open_choice()
        self.assertIsNone(filesend.pending_choices("another-user"))
        self.assertIn("süresi doldu", filesend.select_pending("another-user", 1))
        self.sent.assert_not_called()
        self.assertIsNotNone(filesend.pending_choices(self.owner))

    def test_stale_file_mtime_or_contents_blocks_transfer(self):
        self.open_choice()
        self.files[0].write_text("tampered after preview", encoding="utf-8")
        entry, result, handler, feedback = self.turn_real("1", model_understanding=False)
        self.assertEqual(entry.state_gate.protocol, "filesend.pending.select")
        self.assertIn("Dosya değişmiş", result)
        self.sent.assert_not_called()
        self.assertIsNone(filesend.pending_choices(self.owner))

    def test_symlink_and_escaped_path_never_enter_owner_choice(self):
        outside = Path(self.temp.name) / "private.txt"
        outside.write_text("secret", encoding="utf-8")
        from pathlib import Path
        wrong = self.files[0].parent / "linked.txt"
        try:
            wrong.symlink_to(outside)
        except OSError:
            self.skipTest("Platform test ortamı symlink oluşturamıyor.")
        self.assertIsNone(filesend._file_proof(wrong))
        self.assertFalse(filesend.remember_pending(self.owner, [wrong, outside]))
        self.assertIsNone(filesend.pending_choices(self.owner))

    def test_ambiguous_choices_without_owner_are_not_process_global(self):
        reply = filesend.handle("rapor dosyasını telefonuma gönder")
        self.assertIn("güvenli seçim", reply)
        self.assertIsNone(filesend.pending_choices(self.owner))
        self.sent.assert_not_called()

    def test_non_offered_substring_does_not_transfer_any_file(self):
        self.open_choice()
        entry, result, handler, feedback = self.turn_real("report-a", model_understanding=False)
        self.assertFalse(entry.state_gate.matched)
        self.sent.assert_not_called()


if __name__ == "__main__":
    import unittest
    unittest.main()
