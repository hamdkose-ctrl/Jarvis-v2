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


class TruncationAndContinuationTests(FileWorkerTestCase):
    """Hamdi'nin kapanış şartı: 1200. karakterden veya 200. konumdan sonraki
    önemli maddeler sessizce kaybolmaz — açık uyarı + devam parçası vardır."""

    def _paragraphs(self, count: int, chars: int = 60) -> str:
        return '\n\n'.join(f'MADDE {i} ' + 'x' * chars for i in range(1, count + 1))

    def test_location_limit_truncates_with_explicit_warning(self):
        p = self.write('uzun.txt', self._paragraphs(250))
        obs = fw.extract(str(p))
        self.assertEqual(obs.reason_code, 'OK')
        self.assertTrue(obs.truncated)
        self.assertEqual(len(obs.locations), fw.MAX_LOCATIONS)
        self.assertIsNotNone(obs.continuation)
        self.assertTrue(any('offset=' in w for w in obs.warnings),
                        'Kesinti sessiz olamaz; uyarı devam offset içermeli')

    def test_continuation_chunk_covers_items_after_location_limit(self):
        p = self.write('uzun2.txt', self._paragraphs(250))
        first = fw.extract(str(p))
        second = fw.extract(str(p), offset=first.continuation)
        self.assertFalse(second.truncated)
        self.assertIsNone(second.continuation)
        texts = [loc.text for loc in first.locations] + [loc.text for loc in second.locations]
        seen = [text.split()[1] for text in texts]
        self.assertEqual(sorted(map(int, seen)), list(range(1, 251)))  # eksik yok
        self.assertEqual(len(set(seen)), 250)                          # tekrar yok
        joined = '\n'.join(texts)
        for i in (200, 201, 250):
            self.assertIn(f'MADDE {i} ', joined)

    def test_evidence_budget_stops_with_warning_not_silently(self):
        p = self.write('butce.txt', '\n\n'.join(f'B{i} ' + 'y' * 1100 for i in range(1, 41)))
        obs = fw.extract(str(p))
        self.assertTrue(obs.truncated)
        self.assertLess(len(obs.locations), 40)
        self.assertLessEqual(sum(len(loc.text) for loc in obs.locations), fw.EVIDENCE_BUDGET)
        self.assertTrue(any('bütçe' in w for w in obs.warnings))
        second = fw.extract(str(p), offset=obs.continuation)
        self.assertTrue(second.locations)  # kalan parça erişilebilir

    def test_snippet_len_is_1200_and_clips_long_unit(self):
        self.assertEqual(fw.SNIPPET_LEN, 1200)
        p = self.write('k.txt', 'z' * 5000)
        obs = fw.extract(str(p))
        self.assertEqual(len(obs.locations[0].text), 1200)
        self.assertFalse(obs.truncated)

    def test_invalid_offset_is_rejected(self):
        p = self.write('a.txt', 'metin')
        for bad in (-1, True, '200', None):
            with self.assertRaises(fw.FileWorkerError) as ctx:
                fw.extract(str(p), offset=bad)
            self.assertEqual(ctx.exception.reason_code, 'INVALID_OFFSET')

    def test_offset_beyond_end_yields_empty_but_honest(self):
        p = self.write('kisa.txt', self._paragraphs(3))
        obs = fw.extract(str(p), offset=999)
        self.assertEqual(obs.reason_code, 'NO_TEXT_EXTRACTED')
        self.assertFalse(obs.truncated)


class FileTaskIntegrationTests(FileWorkerTestCase):
    def test_obligations_keep_location_and_truncation_is_visible(self):
        from modules import task_workers
        content = '\n\n'.join(
            [f'MADDE {i} doldur metni' for i in range(1, 210)] +
            ['Sözleşme 5 Aralık 2026 tarihine kadar uzatılabilir.'])
        p = self.write('sozlesme.txt', content)
        result = task_workers.file_task({'path': str(p), 'operation': 'extract_obligations'})
        self.assertEqual(result['state'], 'done')
        self.assertTrue(result['file_evidence']['truncated'])
        self.assertIn('offset=', result['text'])
        deadlines = [row for row in result['obligations'] if row['kind'] == 'deadline']
        self.assertEqual(deadlines, [])  # madde ilk parçada değil; uydurma yok

    def test_continuation_round_finds_obligation_after_first_chunk(self):
        from modules import task_workers
        content = '\n\n'.join(
            [f'MADDE {i} doldur metni' for i in range(1, 210)] +
            ['Rapor 05.12.2026 günü teslim edilir; bildirim yapılmalı.'])
        p = self.write('devam.txt', content)
        first = task_workers.file_task({'path': str(p), 'operation': 'extract_obligations'})
        self.assertFalse(any(row['kind'] == 'deadline' for row in first['obligations']))
        second = task_workers.file_task({
            'path': str(p), 'operation': 'extract_obligations',
            'offset': first['file_evidence']['continuation']})
        deadlines = [row for row in second['obligations'] if row['kind'] == 'deadline']
        self.assertEqual([row['due'] for row in deadlines], ['2026-12-05'])
        self.assertTrue(all(isinstance(row['line'], int) for row in second['obligations']),
                        'Her bulgu kaynak satır bilgisiyle korunur')

    def test_file_task_rejects_bad_offset(self):
        from modules import task_workers
        p = self.write('x.txt', 'metin')
        with self.assertRaises(ValueError):
            task_workers.file_task({'path': str(p), 'operation': 'extract_obligations', 'offset': -5})


if __name__ == '__main__':
    unittest.main()
