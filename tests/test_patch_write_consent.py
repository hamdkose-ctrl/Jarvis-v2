from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from modules import file_worker_extensions as ext


class MetinYamasiYazmaIzniTestleri(unittest.TestCase):
    """Yazma yalnız açık izinle ve izinli klasörde olur."""

    def _dosya(self, kok: Path, ad: str = "notlar.txt", icerik: str = "eski satır\n") -> Path:
        yol = kok / ad
        yol.write_text(icerik, encoding="utf-8")
        return yol

    def test_izin_yoksa_yazmaz(self):
        with tempfile.TemporaryDirectory() as tmp:
            kok = Path(tmp)
            yol = self._dosya(kok)
            with self.assertRaises(ext.FileWorkerExtensionError):
                ext.apply_patch(yol, {"eski": "yeni"}, consent=False, allowed_root=kok)
            self.assertEqual(yol.read_text(encoding="utf-8"), "eski satır\n")

    def test_klasor_disisnda_yazmaz(self):
        import tempfile as tf

        with tf.TemporaryDirectory() as dis, tf.TemporaryDirectory() as ic:
            yol = self._dosya(Path(dis))
            with self.assertRaises(ext.FileWorkerExtensionError):
                ext.apply_patch(yol, {"eski": "yeni"}, consent=True, allowed_root=ic)
            self.assertEqual(yol.read_text(encoding="utf-8"), "eski satır\n")

    def test_izinli_yazma_yedek_ve_ozet_uretir(self):
        with tempfile.TemporaryDirectory() as tmp:
            kok = Path(tmp)
            yol = self._dosya(kok)
            once = hashlib.sha256("eski satır\n".encode("utf-8")).hexdigest()
            kayit = ext.apply_patch(yol, {"eski": "yeni"}, consent=True, allowed_root=kok)
            self.assertEqual(yol.read_text(encoding="utf-8"), "yeni satır\n")
            self.assertEqual(kayit["digest_before"], once)
            self.assertEqual(
                kayit["digest_after"],
                hashlib.sha256("yeni satır\n".encode("utf-8")).hexdigest(),
            )
            yedek = Path(kayit["backup"])
            self.assertTrue(yedek.is_file())
            self.assertEqual(yedek.read_text(encoding="utf-8"), "eski satır\n")

    def test_eski_davranis_bozulmadi(self):
        with tempfile.TemporaryDirectory() as tmp:
            yol = self._dosya(Path(tmp))
            self.assertEqual(ext.patch_text(yol, {"eski": "yeni"}), "yeni satır\n")
    def test_file_task_izinsiz_reddeder(self):
        from modules import task_workers

        with tempfile.TemporaryDirectory() as tmp:
            kok = Path(tmp)
            yol = self._dosya(kok)
            with self.assertRaises(ValueError):
                task_workers.file_task(
                {"operation": "patch_text", "path": str(yol),
                 "replacements": {"eski": "yeni"}, "allowed_root": str(kok)}
            )
            self.assertEqual(yol.read_text(encoding="utf-8"), "eski satır\n")

    def test_file_task_izinli_uygular(self):
        from modules import task_workers

        with tempfile.TemporaryDirectory() as tmp:
            kok = Path(tmp)
            yol = self._dosya(kok)
            sonuc = task_workers.file_task(
                {"operation": "patch_text", "path": str(yol),
                 "replacements": {"eski": "yeni"}, "allowed_root": str(kok),
                 "allow_write": True}
            )
            self.assertEqual(sonuc["state"], "done")
            self.assertEqual(sonuc["operation"], "patch_text")
            self.assertTrue(Path(sonuc["backup"]).is_file())
            self.assertEqual(yol.read_text(encoding="utf-8"), "yeni satır\n")


if __name__ == "__main__":
    unittest.main()
