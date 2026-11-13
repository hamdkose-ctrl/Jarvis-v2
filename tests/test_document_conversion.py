"""Real format round trips and failure atomicity; no model or device calls."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from docx import Document
from openpyxl import Workbook, load_workbook
from modules import conversion
from modules.document_conversion import read_source, text_blocks
from modules.exam_conversion import extract_questions


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_word_table_order_and_turkish_pdf(self):
        source = self.root/'source.docx'
        doc = Document(); doc.add_heading('Türkçe ölçüm', 1)
        doc.add_paragraph('Tablo öncesi')
        table = doc.add_table(rows=2, cols=2)
        for cell, value in zip([c for row in table.rows for c in row.cells], ['İş','Değer','Ölçüm','42']): cell.text=value
        doc.add_paragraph('Tablo sonrası'); doc.save(source)
        content = read_source(source)
        self.assertEqual([b.kind for b in content.blocks], ['heading','paragraph','table','paragraph'])
        target = self.root/'result.xlsx'; conversion.convert(source,target)
        wb = load_workbook(target)
        try:
            self.assertEqual(wb['Tablo 1']['B2'].value, '42')
            self.assertEqual(wb['Belge']['B5'].value, 'Tablo sonrası')
        finally: wb.close()
        from modules.conversion_writers import _unicode_pdf_font
        if _unicode_pdf_font() is None:
            self.skipTest('Unicode PDF font unavailable; Word/Excel checks passed, PDF round trip did not run')
        target = self.root/'result.pdf'; conversion.convert(source,target)
        self.assertIn('Türkçe ölçüm', '\n'.join(read_source(target).pages))
        self.assertIn('Tablo sonrası', '\n'.join(read_source(target).pages))

    def test_missing_unicode_font_preserves_existing_output(self):
        target = self.root / 'result.pdf'
        target.write_bytes(b'previous output')
        with patch('modules.conversion_writers._unicode_pdf_font', return_value=None):
            with self.assertRaisesRegex(ValueError, 'Unicode'):
                conversion.save_text('Türkçe ölçüm', target, 'rapor')
        self.assertEqual(target.read_bytes(), b'previous output')
        self.assertFalse(list(self.root.glob('.jarvis-convert-*')))

    def test_markdown_tables_are_native_tables(self):
        text = '# Başlık\n\n| Ad | Sayı |\n| --- | ---: |\n| Pompa | 3 |\n\nSon paragraf'
        blocks = text_blocks(text)
        self.assertEqual([b.kind for b in blocks], ['heading','table','paragraph'])
        target = self.root/'result.docx'; conversion.save_text(text,target,'rapor')
        doc = Document(target)
        self.assertEqual(doc.tables[0].cell(1,0).text,'Pompa')
        self.assertEqual(doc.paragraphs[-1].text,'Son paragraf')

    def test_copy_same_format_is_exact(self):
        source=self.root/'source.xlsx'; target=self.root/'out.xlsx'
        wb=Workbook();wb.active['A1']='=SUM(B1:B3)';wb.save(source)
        conversion.convert(source,target)
        self.assertEqual(source.read_bytes(),target.read_bytes())

    def test_never_overwrite_source(self):
        source=self.root/'source.pdf';source.write_bytes(b'original')
        with self.assertRaisesRegex(ValueError,'Kaynak'):conversion.convert(source,source)
        self.assertEqual(source.read_bytes(),b'original')

    def test_failed_conversion_preserves_existing_output(self):
        source=self.root/'source.txt';source.write_text('veri',encoding='utf-8')
        target=self.root/'result.xlsx';target.write_bytes(b'previous output')
        with patch.object(conversion,'write_content',side_effect=ValueError('failure')):
            with self.assertRaises(ValueError):conversion.convert(source,target)
        self.assertEqual(target.read_bytes(),b'previous output')
        self.assertFalse(list(self.root.glob('.jarvis-convert-*')))

    def test_failed_text_export_preserves_existing_output(self):
        target=self.root/'result.xlsx';target.write_bytes(b'previous output')
        with patch.object(conversion,'write_content',side_effect=ValueError('failure')):
            with self.assertRaises(ValueError):conversion.save_text('text',target,'rapor')
        self.assertEqual(target.read_bytes(),b'previous output')

    def test_successful_conversion_must_not_replace_existing_target(self):
        source = self.root/'source.docx'
        Document().save(source)
        target = self.root/'already.docx'
        target.write_bytes(b'foreign owner data')
        with self.assertRaises(FileExistsError):
            conversion.convert(source, target)
        self.assertEqual(target.read_bytes(), b'foreign owner data')
        self.assertFalse(list(self.root.glob('.jarvis-convert-*')))

    def test_successful_text_export_must_not_replace_existing_target(self):
        target = self.root/'already.docx'
        target.write_bytes(b'foreign owner data')
        with self.assertRaises(FileExistsError):
            conversion.save_text('safe content', target, 'rapor')
        self.assertEqual(target.read_bytes(), b'foreign owner data')
        self.assertFalse(list(self.root.glob('.jarvis-convert-*')))

    def test_destination_created_during_conversion_never_clobbered(self):
        source = self.root/'source.docx'
        Document().save(source)
        target = self.root/'raced.docx'
        publish = conversion._publish_new

        def race(temp, destination):
            target.write_bytes(b'new file from another process')
            return publish(temp, destination)

        with patch.object(conversion, '_publish_new', side_effect=race):
            with self.assertRaises(FileExistsError):
                conversion.convert(source, target)
        self.assertEqual(target.read_bytes(), b'new file from another process')
        self.assertFalse(list(self.root.glob('.jarvis-convert-*')))

    def test_formula_like_source_remains_text(self):
        target=self.root/'result.xlsx';conversion.save_text('=HYPERLINK("https://invalid")',target,'rapor')
        wb=load_workbook(target)
        try:self.assertEqual(wb['Belge']['B2'].data_type,'s')
        finally:wb.close()

    def test_unsupported_format_has_clear_error(self):
        source=self.root/'old.doc';source.write_bytes(b'original')
        with self.assertRaisesRegex(ValueError,'DOC/XLS'):conversion.convert(source,self.root/'out.pdf')

    def test_exam_nested_number_does_not_create_fake_question(self):
        questions=extract_questions(['(111) DERS – 1\n1. Soru\nA) a\nB) b\nC) c\nD) d\n2. Soru\n1. çocuk\nA) a\nB) b\nC) c\nD) d\n3. Soru\nA) a\nB) b\nC) c\nD) d',
            'CEVAP ANAHTARI\n(111) DERS – 1\n1. A\n2. B\n3. C'])
        self.assertEqual([q.number for q in questions],[1,2,3])
        self.assertEqual([q.answer for q in questions],['A','B','C'])
        self.assertIn('1. çocuk',questions[1].text)

    def test_pdf_word_has_editable_text(self):
        from reportlab.pdfgen import canvas
        source=self.root/'source.pdf';c=canvas.Canvas(str(source))
        for i in range(3):c.drawString(50,750,f'Page {i+1}');c.rect(50,100,100,100);c.showPage()
        c.save();target=self.root/'out.docx'
        result=conversion.convert(source,target)
        self.assertIn('düzenlenebilir olarak',result['note'])
        document=Document(target)
        self.assertEqual(len(document.inline_shapes),3)
        text='\n'.join(p.text for p in document.paragraphs)
        for i in range(3):self.assertIn(f'Page {i+1}',text)

if __name__=='__main__':unittest.main()
