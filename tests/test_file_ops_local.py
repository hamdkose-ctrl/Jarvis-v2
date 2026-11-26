"""Yerel dosya işlemleri: okuma serbest, yazma yok, ev klasörü sınırı."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import file_ops_local as ops


class Reading(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.patch = patch.object(ops, "HOME", self.dir)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_list_folder_lists_entries(self):
        (self.dir / "a.txt").write_text("x", encoding="utf-8")
        (self.dir / "alt").mkdir()
        result = ops.list_folder(str(self.dir))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["entries"], ["alt/", "a.txt"])

    def test_read_file_returns_content(self):
        path = self.dir / "not.txt"
        path.write_text("merhaba dünya", encoding="utf-8")
        result = ops.read_file(str(path))
        self.assertEqual(result["status"], "ok")
        self.assertIn("merhaba", result["content"])

    def test_long_file_is_cut_and_says_so(self):
        path = self.dir / "uzun.txt"
        path.write_text("\n".join(str(i) for i in range(200)), encoding="utf-8")
        result = ops.read_file(str(path))
        self.assertIn("kısaltıldı", result["text"])

    def test_outside_home_is_refused(self):
        self.assertEqual(ops.read_file("C:/Windows/win.ini")["status"], "refused")
        self.assertEqual(ops.list_folder("C:/Windows")["status"], "refused")

    def test_missing_file_is_reported(self):
        self.assertEqual(ops.read_file(str(self.dir / "yok.txt"))["status"], "missing")

    def test_open_file_does_not_touch_content(self):
        path = self.dir / "ac.txt"
        path.write_text("içerik", encoding="utf-8")
        with patch.object(ops.os, "startfile", create=True) as start, patch.object(ops.time, "sleep"):
            result = ops.open_file(str(path))
        self.assertEqual(result["status"], "done")
        self.assertEqual(path.read_text(encoding="utf-8"), "içerik")

    def test_module_has_no_write_or_delete_calls(self):
        source = Path(ops.__file__).read_text(encoding="utf-8")
        for forbidden in ("write_text", "unlink", "rmtree", "rename"):
            self.assertNotIn(forbidden, source, forbidden)


if __name__ == "__main__":
    unittest.main()


class OpenFileTypes(unittest.TestCase):
    """Bilinmeyen türde Windows "birlikte aç" penceresi çıkmasın."""

    def test_markdown_opens_in_notepad(self):
        from unittest.mock import patch
        from modules import file_ops_local
        with patch.object(file_ops_local, "_resolve", return_value=Path(__file__)), \
             patch("subprocess.Popen") as popen, \
             patch("os.startfile", create=True) as startfile:
            result = file_ops_local.open_file("belge.md")
        self.assertEqual(popen.call_args[0][0][0], "notepad.exe")
        startfile.assert_not_called()

    def test_unknown_extension_is_refused(self):
        from unittest.mock import patch
        from modules import file_ops_local
        target = Path(__file__).with_suffix(".weird")
        with patch.object(file_ops_local, "_resolve", return_value=target), \
             patch.object(Path, "exists", return_value=True), \
             patch("os.startfile", create=True) as startfile:
            result = file_ops_local.open_file("x.weird")
        self.assertEqual(result["status"], "refused")
        startfile.assert_not_called()
