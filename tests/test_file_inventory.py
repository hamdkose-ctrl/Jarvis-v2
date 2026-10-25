"""Klasör envanteri v1: salt-okunur rapor üretimi. Hiçbir test gerçek dosya
taşıma/silme yapmaz; `file_worker.allowed_roots()` izole bir tmp klasöre
yönlendirilir."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import file_inventory as fi
from modules import file_worker as fw


class FileInventoryTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._patch = patch.object(fw, 'allowed_roots', return_value=[self.root])
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def write(self, name: str, content: str = 'x') -> Path:
        p = self.root / name
        p.write_text(content, encoding='utf-8')
        return p


class BuildReportTests(FileInventoryTestCase):
    def test_counts_total_and_by_extension(self):
        self.write('a.txt')
        self.write('b.txt')
        self.write('c.csv')
        report = fi.build_report(str(self.root))
        self.assertEqual(report.total_files, 3)
        self.assertEqual(report.by_extension, {'.txt': 2, '.csv': 1})

    def test_finds_duplicate_and_similar_groups(self):
        self.write('rapor.txt', 'aynı')
        self.write('rapor_kopya.txt', 'aynı')
        self.write('fatura.txt', 'A')
        self.write('fatura (1).txt', 'B')
        report = fi.build_report(str(self.root))
        self.assertEqual(len(report.duplicate_groups), 1)
        self.assertEqual(len(report.similar_name_groups), 1)

    def test_flags_empty_file_candidates(self):
        self.write('bos.txt', '')
        self.write('dolu.txt', 'x')
        report = fi.build_report(str(self.root))
        self.assertEqual([e['name'] for e in report.empty_file_candidates], ['bos.txt'])

    def test_flags_old_file_candidates(self):
        p = self.write('eski.txt', 'x')
        old_time = time.time() - (fi.OLD_FILE_DAYS + 1) * 86400
        import os
        os.utime(p, (old_time, old_time))
        self.write('yeni.txt', 'x')
        report = fi.build_report(str(self.root))
        self.assertEqual([e['name'] for e in report.old_file_candidates], ['eski.txt'])

    def test_flags_temp_name_candidates(self):
        # '.crdownload'/'.tmp'/'.part' gibi uzantılar zaten scan_folder'ın junk
        # filtresinde (files._IGNORE_EXT) elendiği için envantere hiç girmez;
        # burada yalnız o filtrede OLMAYAN '.bak' ve '~$' önekini sınıyoruz.
        self.write('~$belge.docx')
        self.write('eski_rapor.bak')
        self.write('gercek.docx')
        report = fi.build_report(str(self.root))
        names = {e['name'] for e in report.temp_name_candidates}
        self.assertEqual(names, {'~$belge.docx', 'eski_rapor.bak'})

    def test_missing_folder_raises_file_worker_error(self):
        with self.assertRaises(fw.FileWorkerError) as ctx:
            fi.build_report(str(self.root / 'yok'))
        self.assertEqual(ctx.exception.reason_code, 'FILE_NOT_FOUND')

    def test_outside_allowed_root_raises_permission_mismatch(self):
        with tempfile.TemporaryDirectory() as other:
            with self.assertRaises(fw.FileWorkerError) as ctx:
                fi.build_report(other)
            self.assertEqual(ctx.exception.reason_code, 'PERMISSION_MISMATCH')

    def test_never_writes_to_scanned_files(self):
        p = self.write('korunan.txt', 'değişmeyecek')
        before = p.read_bytes()
        fi.build_report(str(self.root))
        self.assertEqual(p.read_bytes(), before)

    def test_empty_folder_gives_empty_report(self):
        report = fi.build_report(str(self.root))
        self.assertEqual(report.total_files, 0)
        self.assertEqual(report.duplicate_groups, [])
        self.assertFalse(report.truncated)


if __name__ == '__main__':
    unittest.main()
