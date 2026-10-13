"""Document reading: MarkItDown first, built-in readers as fallback, clear refusals for unsafe files."""
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from modules import docs


def pptx(path, slides):
    """Minimal .pptx container with text boxes (no python-pptx needed)."""
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        for i, lines in enumerate(slides, 1):
            body = ''.join(f'<a:p><a:r><a:t>{t}</a:t></a:r></a:p>' for t in lines)
            z.writestr(f'ppt/slides/slide{i}.xml', f'<p:sld xmlns:a="a" xmlns:p="p">{body}</p:sld>')


class DocumentReadingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def path(self, name, data=b''):
        p = self.dir / name
        p.write_bytes(data.encode('utf-8') if isinstance(data, str) else data)
        return p

    def test_fallback_readers_cover_new_formats_without_markitdown(self):
        with patch.object(docs, 'markitdown_available', return_value=False):
            slides = self.dir / 'sunum.pptx'; pptx(slides, [['Başlık', 'Gelir &amp; gider'], ['Sonuç']] + [['x']] * 9)
            text = docs.read_document(str(slides))
            self.assertIn('[Slayt 1]\nBaşlık\nGelir & gider', text)
            self.assertLess(text.index('[Slayt 2]'), text.index('[Slayt 10]'))   # numeric slide order
            csv_text = docs.read_document(str(self.path('liste.csv', 'Malzeme;Adet\nVida;10\n'.encode('cp1254'))))
            self.assertEqual(csv_text, 'Malzeme | Adet\nVida | 10')
            self.assertEqual(docs.read_document(str(self.path('tr.csv', 'Şube;Ürün\nİzmir;Çay\n'.encode('cp1254')))),
                             'Şube | Ürün\nİzmir | Çay')
            page = self.path('sayfa.html', '<html><style>x{}</style><script>alert(1)</script><h1>Rapor</h1><p>Toplam 5</p></html>')
            self.assertEqual(docs.read_document(str(page)), 'Rapor\nToplam 5')

    def test_markitdown_is_primary_and_failure_falls_back(self):
        slides = self.dir / 's.pptx'; pptx(slides, [['Yedek okuyucu']])
        with patch.object(docs, 'read_markitdown_isolated', return_value='# Slide 1\nMarkItDown'):
            self.assertEqual(docs.read_document(str(slides)), '# Slide 1\nMarkItDown')
        with patch.object(docs, 'read_markitdown_isolated', return_value=None):
            self.assertIn('Yedek okuyucu', docs.read_document(str(slides)))
        with patch.object(docs, 'read_markitdown_isolated', side_effect=AssertionError('txt/pdf stay on old path')):
            self.assertEqual(docs.read_document(str(self.path('a.txt', 'merhaba'))), 'merhaba')

    def test_markitdown_subprocess_failure_returns_none(self):
        from types import SimpleNamespace
        with patch.object(docs, 'markitdown_available', return_value=True), \
             patch('subprocess.run', return_value=SimpleNamespace(returncode=1, stdout=b'', stderr=b'UnsupportedFormatException')):
            self.assertIsNone(docs.read_markitdown_isolated('x.pptx'))
        with patch.object(docs, 'markitdown_available', return_value=True), \
             patch('subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=b'  ', stderr=b'')):
            self.assertIsNone(docs.read_markitdown_isolated('x.pptx'))

    @unittest.skipUnless(docs.markitdown_available(), 'MarkItDown kurulu değil')
    def test_real_markitdown_reads_excel_as_table(self):
        from openpyxl import Workbook
        wb = Workbook(); wb.active.title = 'Özet'; wb.active.append(['Kalem', 'Tutar']); wb.active.append(['Kira', 1200])
        target = self.dir / 'butce.xlsx'; wb.save(target)
        text = docs.read_document(str(target))
        self.assertIn('Özet', text); self.assertIn('| Kira', text); self.assertIn('1200', text)

    def test_unsafe_or_unsupported_files_get_clear_messages(self):
        with self.assertRaisesRegex(ValueError, r'“\.docx” olarak kaydet'):
            docs.read_document(str(self.path('eski.doc', b'x')))
        with self.assertRaisesRegex(ValueError, 'parola korumalı'):
            docs.read_document(str(self.path('gizli.xlsx', b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + b'0' * 100)))
        with self.assertRaisesRegex(ValueError, 'bozuk'):
            docs.read_document(str(self.path('bozuk.docx', b'not a zip')))
        big = self.dir / 'bomba.xlsx'
        with zipfile.ZipFile(big, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('xl/a.xml', '0' * 200_000)
        with patch.object(docs, '_MAX_UNZIPPED', 100_000), patch.object(docs, 'read_markitdown_isolated', side_effect=AssertionError('read')):
            with self.assertRaisesRegex(ValueError, 'çok büyüyor'):
                docs.read_document(str(big))
        with patch.object(docs, 'read_pdf_isolated', side_effect=RuntimeError('FileNotDecryptedError: File has not been decrypted')):
            with self.assertRaisesRegex(ValueError, 'PDF parola'):
                docs.read_document(str(self.path('kilitli.pdf', b'%PDF')))
        with patch.object(docs, 'read_pdf_isolated', side_effect=RuntimeError('başka hata')):
            with self.assertRaisesRegex(RuntimeError, 'başka hata'):
                docs.read_document(str(self.path('k2.pdf', b'%PDF')))
        with self.assertRaisesRegex(ValueError, 'PowerPoint'):
            docs.read_document(str(self.path('x.zip', b'')))

    def test_macro_workbook_reads_values_only(self):
        from openpyxl import Workbook
        wb = Workbook(); wb.active['A1'] = 'Makro yok'
        target = self.dir / 'm.xlsm'; wb.save(target)
        with patch.object(docs, 'read_markitdown_isolated', return_value=None):
            self.assertIn('A1: Makro yok', docs.read_document(str(target)))


if __name__ == '__main__':
    unittest.main()
