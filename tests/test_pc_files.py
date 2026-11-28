"""Dosya kaydetme: sandbox sınırı, onay kapısı, diskten doğrulama."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import pc_files


class Sandbox(unittest.TestCase):
    def test_names_are_confined_to_sandbox(self):
        path = pc_files.sandbox_path("deneme.txt")
        self.assertIn("sandbox", str(path))
        self.assertTrue(str(path).startswith(str(pc_files.SANDBOX)))

    def test_path_traversal_is_neutralised(self):
        path = pc_files.sandbox_path("../../kotu.txt")
        self.assertNotIn("..", path.name)
        self.assertIn("sandbox", str(path))

    def test_empty_name_gets_a_default(self):
        self.assertTrue(pc_files.sandbox_path("").name)


class Confirmation(unittest.TestCase):
    def setUp(self):
        pc_files.pc_hands._pending.clear()

    def test_save_always_asks_first(self):
        with patch("pyautogui.hotkey") as hotkey:
            result = pc_files.save_as("not defteri", "x.txt")
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertEqual(hotkey.call_count, 0)

    def test_confirmation_flow_reaches_ctrl_s(self):
        with patch.object(pc_files.pc_hands.pc_awareness, "find_window",
                          lambda q: {"match": {"title": "Not Defteri", "hwnd": 1}, "reason": ""}), \
             patch.object(pc_files.pc_hands, "_focus", return_value=True), \
             patch.object(pc_files.pc_hands, "_paste", return_value=True), \
             patch("pyautogui.hotkey") as hotkey, patch("pyautogui.press"):
            pc_files.save_as("not defteri", "x.txt")
            result = pc_files.confirm_save()
        self.assertEqual(hotkey.call_args[0], ("ctrl", "s"))
        self.assertIn(result["status"], ("no_change", "done"))

    def test_onaylayinca_bekleyen_kayit_gercekten_yapilir(self):
        with patch.object(pc_files.pc_hands.pc_awareness, "find_window",
                          lambda q: {"match": {"title": "Not Defteri", "hwnd": 1}, "reason": ""}), \
             patch.object(pc_files.pc_hands, "_focus", return_value=True), \
             patch.object(pc_files.pc_hands, "_paste", return_value=True), \
             patch("pyautogui.hotkey") as hotkey, patch("pyautogui.press"):
            pc_files.save_as("not defteri", "onay.txt")
            sonuc = pc_files.pc_hands.confirm_pending()
        self.assertEqual(hotkey.call_args[0], ("ctrl", "s"))
        self.assertIn(sonuc["status"], ("no_change", "done"))

    def test_bekleyen_yoksa_kaydetme_onayi_da_yok(self):
        pc_files.pc_hands._pending.clear()
        sonuc = pc_files.pc_hands.confirm_pending()
        self.assertEqual(sonuc["status"], "none")


class Verification(unittest.TestCase):
    def test_existing_file_is_confirmed_from_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.txt"
            path.write_text("merhaba", encoding="utf-8")
            result = pc_files.verify_saved(path)
        self.assertEqual(result["status"], "done")
        self.assertIn("7 bayt", result["text"])

    def test_missing_file_is_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = pc_files.verify_saved(Path(tmp) / "yok.txt")
        self.assertEqual(result["status"], "no_change")

    def test_cleanup_refuses_outside_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "b.txt"
            path.write_text("x", encoding="utf-8")
            self.assertFalse(pc_files.cleanup(str(path)))
            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
