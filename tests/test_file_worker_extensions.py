import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import file_worker_extensions as ext


class FileWorkerExtensionsTests(unittest.TestCase):
    def setUp(self):
        self.claim_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.claim_tmp.cleanup)
        from modules import file_resource_guard
        guard = patch.object(
            file_resource_guard, '_FILE_EFFECT_CLAIM_ROOT',
            Path(self.claim_tmp.name) / 'claims',
        )
        guard.start()
        self.addCleanup(guard.stop)

    def test_pptx_create_refuses_existing_artifact_before_writer_runs(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'existing.pptx'
            target.write_bytes(b'original artifact')
            calls = []
            with self.assertRaises(FileExistsError):
                ext.create_pptx(
                    str(target), [{'title': 'New', 'body': 'Text'}],
                    writer=calls.append,
                )
            self.assertEqual(calls, [])
            self.assertEqual(target.read_bytes(), b'original artifact')

    def test_pptx_complete_temp_is_fsynced_before_atomic_publish(self):
        try:
            from pptx import Presentation
        except ImportError:
            self.skipTest('python-pptx is unavailable in this environment')
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'report.pptx'
            real_fsync = ext.os.fsync
            real_link = ext.os.link
            calls = []

            def observed_fsync(fd):
                calls.append('fsync')
                return real_fsync(fd)

            def observed_link(src, dst):
                self.assertIn('fsync', calls, 'Publishing before flush is forbidden')
                calls.append('publish')
                return real_link(src, dst)

            with patch.object(ext.os, 'fsync', side_effect=observed_fsync), \
                 patch.object(ext.os, 'link', side_effect=observed_link):
                result = ext.create_pptx(str(target), [
                    {'title': 'Evidence', 'body': 'Verified report'},
                ])
            self.assertEqual(result['state'], 'written')
            self.assertEqual(calls, ['fsync', 'publish'])
            self.assertEqual(Presentation(str(target)).slides[0].shapes.title.text,
                             'Evidence')
            self.assertEqual(list(Path(folder).iterdir()), [target])

    def test_pptx_failed_atomic_link_leaves_no_document_or_temp(self):
        try:
            import pptx
        except ImportError:
            self.skipTest('python-pptx is unavailable in this environment')
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'report.pptx'
            with patch.object(ext.os, 'link', side_effect=OSError('link failed')):
                with self.assertRaises(OSError):
                    ext.create_pptx(str(target), [
                        {'title': 'Evidence', 'body': 'Verified report'},
                    ])
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_text_patch_does_not_truncate_original_when_atomic_write_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'original.txt'
            target.write_text('important original', encoding='utf-8')
            with patch.object(ext.release_guard, 'atomic',
                              side_effect=OSError('simulated disk write failure')):
                with self.assertRaises(OSError):
                    ext.patch_text(target, {'original': 'updated'})
            self.assertEqual(target.read_text(encoding='utf-8'), 'important original')


    def test_extracts_obligations_and_deadlines(self):
        rows = ext.extract_obligations("Raporu 2026-11-05 tarihine kadar göndermelisin. Ek dosyayı kontrol et.")
        self.assertEqual(rows[0]["due"], "2026-11-05")
        self.assertTrue(any(row["kind"] == "obligation" for row in rows))


class TurkishDateExtractionTests(unittest.TestCase):
    """Onaylı biçimler: `5 Aralık 2026`, `05.12.2026`, `2026-12-05` → ISO due.
    Geçersiz/eksik tarihte due=None; asla tarih uydurulmaz."""

    def test_iso_form_normalized(self):
        rows = ext.extract_obligations("Teslim 2026-12-05 tarihinde yapılacak.")
        self.assertEqual(rows[0]["due"], "2026-12-05")

    def test_tr_month_name_form(self):
        rows = ext.extract_obligations("Sözleşme 5 Aralık 2026 günü imzalanır.")
        deadlines = [row for row in rows if row["kind"] == "deadline"]
        self.assertEqual(deadlines[0]["due"], "2026-12-05")

    def test_dotted_dmy_form(self):
        rows = ext.extract_obligations("Rapor 05.12.2026 teslim.")
        self.assertEqual(rows[0]["due"], "2026-12-05")

    def test_slash_dmy_form(self):
        self.assertEqual(ext.extract_dates("05/12/2026"), ["2026-12-05"])

    def test_uppercase_tr_month_name(self):
        self.assertEqual(ext.extract_dates("5 ARALIK 2026"), ["2026-12-05"])

    def test_turkish_diacritic_months(self):
        for text, expected in (("15 Şubat 2027", "2027-02-15"), ("1 Mart 2027", "2027-03-01"),
                               ("20 Ağustos 2027", "2027-08-20"), ("9 Eylül 2027", "2027-09-09"),
                               ("30 Kasım 2027", "2027-11-30")):
            self.assertEqual(ext.extract_dates(text), [expected], text)

    def test_invalid_calendar_date_is_not_invented(self):
        rows = ext.extract_obligations("Kontrol 31.02.2026 tarihinde yapılacak.")
        self.assertEqual([row for row in rows if row["kind"] == "deadline"], [])
        for row in rows:
            self.assertIsNone(row["due"])

    def test_day_without_year_is_not_invented(self):
        self.assertEqual(ext.extract_dates("5 Aralık teslim günü."), [])
        self.assertEqual(ext.extract_dates("yarın son gün"), [])

    def test_multiple_dates_keep_first_as_due_and_order(self):
        rows = ext.extract_obligations("Ön rapor 3 Kasım 2026, kesin rapor 05.12.2026 tarihinde.")
        deadline = next(row for row in rows if row["kind"] == "deadline")
        self.assertEqual(deadline["due"], "2026-11-03")
        self.assertEqual(ext.extract_dates("Ön rapor 3 Kasım 2026, kesin rapor 05.12.2026 tarihinde."),
                         ["2026-11-03", "2026-12-05"])

    def test_empty_text_still_rejected(self):
        with self.assertRaises(ValueError):
            ext.extract_obligations("   ")
        self.assertEqual(ext.extract_dates(""), [])

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
