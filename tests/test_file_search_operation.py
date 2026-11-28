"""Dosya worker arama işlemi (R2a)."""
import tempfile, unittest
from pathlib import Path

from modules import task_workers


class FileSearchOperationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        kok = Path(self.tmp.name)
        (kok / "sozlesme.txt").write_text("Kira sözleşmesi 12 ay sürer.", encoding="utf-8")
        (kok / "diger.txt").write_text("Alakasız içerik.", encoding="utf-8")

    def test_eslesen_dosya_bulunur(self):
        sonuc = task_workers.file_task({"operation": "search_files", "path": self.tmp.name, "query": "kira"})
        self.assertEqual(sonuc["state"], "done")
        self.assertEqual(len(sonuc["matches"]), 1)
        self.assertTrue(sonuc["matches"][0]["path"].endswith("sozlesme.txt"))

    def test_eslesme_yoksa_bos_liste(self):
        sonuc = task_workers.file_task({"operation": "search_files", "path": self.tmp.name, "query": "yokböyle"})
        self.assertEqual(sonuc["matches"], [])
        self.assertIn("0 dosya", sonuc["text"])

    def test_bos_sorgu_hata_verir(self):
        with self.assertRaises(ValueError):
            task_workers.file_task({"operation": "search_files", "path": self.tmp.name, "query": "  "})

    def test_bilinmeyen_islem_reddedilir(self):
        with self.assertRaises(ValueError):
            task_workers.file_task({"operation": "sil", "path": self.tmp.name})


if __name__ == "__main__":
    unittest.main()
