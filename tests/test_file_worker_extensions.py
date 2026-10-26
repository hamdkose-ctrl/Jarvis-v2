import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import file_worker_extensions as ext


class FileWorkerExtensionsTests(unittest.TestCase):
    def test_extracts_obligations_and_deadlines(self):
        rows = ext.extract_obligations("Raporu 2026-11-05 tarihine kadar göndermelisin. Ek dosyayı kontrol et.")
        self.assertEqual(rows[0]["due"], "2026-11-05")
        self.assertTrue(any(row["kind"] == "obligation" for row in rows))

    def test_pptx_writer_is_injected_and_payload_is_structured(self):
        calls = []
        result = ext.create_pptx("sunum.pptx", [{"title": "Başlık", "body": "İçerik"}], writer=calls.append)
        self.assertEqual(result["slides"], 1)
        self.assertEqual(calls[0]["destination"], "sunum.pptx")

    def test_search_handles_unicode_names_and_skips_special_or_minified_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "Türkçe not.txt").write_text("önemli yükümlülük", encoding="utf-8")
            (root / "kod.min.js").write_text("x=" + "a" * 10000, encoding="utf-8")
            results = ext.search_files(root, "yükümlülük")
            self.assertEqual([row["name"] for row in results], ["Türkçe not.txt"])

    def test_patch_rejects_special_large_and_minified_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            normal = root / "not.txt"
            normal.write_text("eski metin", encoding="utf-8")
            self.assertEqual(ext.patch_text(normal, {"eski": "yeni"}), "yeni metin")
            huge = root / "buyuk.txt"
            huge.write_text("x" * (ext.MAX_PATCH_BYTES + 1), encoding="utf-8")
            with self.assertRaises(ext.FileWorkerExtensionError):
                ext.patch_text(huge, {"x": "y"})
            mini = root / "bundle.js"
            mini.write_text("a=" + "b" * 10000, encoding="utf-8")
            with self.assertRaises(ext.FileWorkerExtensionError):
                ext.patch_text(mini, {"a": "c"})


if __name__ == "__main__":
    unittest.main()
