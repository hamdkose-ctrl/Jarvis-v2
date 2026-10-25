"""FileWorker v1: yalnız salt-okunur çıkarım/tarama/yineleme-tespiti. Hiçbir test
gerçek yazma/silme/taşıma yapmaz; `allowed_roots()` her testte izole bir tmp
klasöre yönlendirilir, gerçek Masaüstü/Belgeler klasörlerine dokunulmaz."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import file_worker as fw


class FileWorkerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._patch = patch.object(fw, 'allowed_roots', return_value=[self.root])
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def write(self, name: str, content: str) -> Path:
        p = self.root / name
        p.write_text(content, encoding='utf-8')
        return p


class ScanFolderTests(FileWorkerTestCase):
    def test_lists_files_with_metadata(self):
        self.write('a.txt', 'merhaba')
        self.write('b.csv', 'x,y\n1,2\n')
        entries = fw.scan_folder(str(self.root))
        names = {e['name'] for e in entries}
        self.assertEqual(names, {'a.txt', 'b.csv'})
        self.assertTrue(all('size' in e and 'mtime' in e for e in entries))

    def test_ignores_known_junk_files(self):
        self.write('desktop.ini', 'x')
        self.write('real.txt', 'x')
        entries = fw.scan_folder(str(self.root))
        self.assertEqual([e['name'] for e in entries], ['real.txt'])

    def test_outside_allowed_root_is_permission_mismatch(self):
        with tempfile.TemporaryDirectory() as other:
            with self.assertRaises(fw.FileWorkerError) as ctx:
                fw.scan_folder(other)
            self.assertEqual(ctx.exception.reason_code, 'PERMISSION_MISMATCH')

    def test_missing_folder_is_file_not_found(self):
        with self.assertRaises(fw.FileWorkerError) as ctx:
            fw.scan_folder(str(self.root / 'yok'))
        self.assertEqual(ctx.exception.reason_code, 'FILE_NOT_FOUND')


class DuplicateAndSimilarTests(FileWorkerTestCase):
    def test_finds_content_duplicates(self):
        self.write('rapor.txt', 'aynı içerik')
        self.write('rapor_kopya.txt', 'aynı içerik')
        self.write('farkli.txt', 'başka içerik')
        entries = fw.scan_folder(str(self.root))
        groups = fw.find_duplicates(entries)
        self.assertEqual(len(groups), 1)
        self.assertEqual({e['name'] for e in groups[0]}, {'rapor.txt', 'rapor_kopya.txt'})

    def test_finds_similar_names_with_counter_suffix(self):
        self.write('fatura.txt', 'A')
        self.write('fatura (1).txt', 'B')
        entries = fw.scan_folder(str(self.root))
        groups = fw.find_similar_names(entries)
        self.assertEqual(len(groups), 1)
        self.assertEqual({e['name'] for e in groups[0]}, {'fatura.txt', 'fatura (1).txt'})


class ExtractTests(FileWorkerTestCase):
    def test_extract_txt_has_digest_and_locations(self):
        p = self.write('not.txt', 'birinci satır\niki\n')
        obs = fw.extract(str(p))
        self.assertEqual(obs.reason_code, 'OK')
        self.assertIsNotNone(obs.content_digest)
        self.assertTrue(obs.locations)
        self.assertIn('birinci satır', obs.locations[0].text)

    def test_extract_csv_has_cell_locations(self):
        p = self.write('tablo.csv', 'ad,tutar\nkira,100\n')
        obs = fw.extract(str(p))
        self.assertEqual(obs.reason_code, 'OK')
        self.assertTrue(any(loc.cell_or_range for loc in obs.locations) or obs.locations)

    def test_extract_missing_file_is_file_not_found(self):
        with self.assertRaises(fw.FileWorkerError) as ctx:
            fw.extract(str(self.root / 'yok.txt'))
        self.assertEqual(ctx.exception.reason_code, 'FILE_NOT_FOUND')

    def test_extract_unsupported_extension_raises(self):
        p = self.write('veri.bin', 'xx')
        with self.assertRaises(fw.FileWorkerError) as ctx:
            fw.extract(str(p))
        self.assertEqual(ctx.exception.reason_code, 'UNSUPPORTED_FORMAT')

    def test_extract_outside_allowed_root_is_permission_mismatch(self):
        with tempfile.TemporaryDirectory() as other:
            p = Path(other) / 'a.txt'
            p.write_text('x', encoding='utf-8')
            with self.assertRaises(fw.FileWorkerError) as ctx:
                fw.extract(str(p))
            self.assertEqual(ctx.exception.reason_code, 'PERMISSION_MISMATCH')

    def test_extract_empty_file_is_no_text_extracted(self):
        p = self.write('bos.txt', '   \n\n  ')
        obs = fw.extract(str(p))
        self.assertEqual(obs.reason_code, 'NO_TEXT_EXTRACTED')

    def test_never_writes_to_source_file(self):
        p = self.write('korunan.txt', 'değişmeyecek')
        before = p.read_bytes()
        fw.extract(str(p))
        self.assertEqual(p.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
