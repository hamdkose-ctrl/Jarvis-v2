import io
import os
import subprocess
import unittest
from unittest.mock import patch
import zipfile
from modules import attachment_documents as docs,mail_attachments


class DocumentAttachmentTests(unittest.TestCase):
    def test_real_docx_xlsx_and_pptx_text_without_formula_execution(self):
        from docx import Document
        from openpyxl import Workbook
        from pptx import Presentation
        from pptx.util import Inches
        word=Document();word.add_paragraph('Hello Word');buf=io.BytesIO();word.save(buf)
        self.assertIn('Hello Word',docs.read(buf.getvalue(),'.docx')['body'])
        book=Workbook();book.active['A1']='Hello Excel';book.active['B1']='=1+2';buf=io.BytesIO();book.save(buf)
        result=docs.read(buf.getvalue(),'.xlsx')['body'];self.assertIn('Hello Excel',result);self.assertIn('hesaplanmadı',result)
        presentation=Presentation();slide=presentation.slides.add_slide(presentation.slide_layouts[6])
        slide.shapes.add_textbox(Inches(1),Inches(1),Inches(3),Inches(1)).text='Hello Slides'
        buf=io.BytesIO();presentation.save(buf)
        self.assertIn('Hello Slides',docs.read(buf.getvalue(),'.pptx')['body'])

    def test_real_pdf_and_scan_without_text(self):
        from reportlab.pdfgen import canvas
        for has_text in (True,False):
            buf=io.BytesIO();c=canvas.Canvas(buf)
            if has_text:c.drawString(30,30,'Hello PDF')
            c.showPage();c.save()
            if has_text:self.assertIn('Hello PDF',docs.read(buf.getvalue(),'.pdf')['body'])
            else:
                with self.assertRaises(ValueError):docs.read(buf.getvalue(),'.pdf')

    def _turkish_pdf(self,text,**kw):
        import glob
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        fonts=glob.glob('/usr/share/fonts/**/DejaVuSans.ttf',recursive=True)+glob.glob(r'C:\Windows\Fonts\arial.ttf')
        if not fonts:self.skipTest('Türkçe harfli TrueType yazı tipi yok')
        pdfmetrics.registerFont(TTFont('TRFont',fonts[0]))
        buf=io.BytesIO();c=canvas.Canvas(buf,**kw);c.setFont('TRFont',12);c.drawString(40,700,text);c.showPage();c.save()
        return buf.getvalue()

    def test_turkish_pdf_reads_under_windows_code_page(self):
        # Gerçek PC'de ekli PDF'ler genel hata veriyordu: alt süreç çıktısı yerel kod sayfasında (cp1254) yazılıyordu.
        raw=self._turkish_pdf('Sözleşme ödeme günü İstanbul şubesi')
        for env in ({'PYTHONIOENCODING':'cp1254','PYTHONUTF8':'0'},{'PYTHONIOENCODING':'cp1252','PYTHONUTF8':'0'}):
            with patch.dict(os.environ,env):
                self.assertIn('Sözleşme ödeme günü İstanbul şubesi',docs.read(raw,'.pdf')['body'])

    def test_gmail_attachment_id_bytes_reach_worker_intact(self):
        # Gmail ek kimliğiyle gelen urlsafe base64 baytlar, boyut kontrolünden sonra alt sürece aynen gider.
        import base64
        from unittest.mock import Mock
        raw=self._turkish_pdf('Ödeme planı ve şartlar')
        part={'filename':'Sözleşme.pdf','mimeType':'application/pdf','body':{'size':len(raw),'attachmentId':'ANGjdJ_x-1'}}
        messages=Mock();messages.attachments().get().execute.return_value={'data':base64.urlsafe_b64encode(raw).decode().rstrip('=')}
        seen=[];real=docs.subprocess.run
        def run(cmd,**kw):seen.append(kw['input']);return real(cmd,**kw)
        with patch.dict(os.environ,{'PYTHONIOENCODING':'cp1254','PYTHONUTF8':'0'}),patch.object(docs.subprocess,'run',side_effect=run):
            result=mail_attachments.read(messages,'M1',part)
        messages.attachments().get.assert_called_with(userId='me',messageId='M1',id='ANGjdJ_x-1')
        self.assertEqual(seen,[raw]);self.assertIn('Ödeme planı ve şartlar',result['body'])

    def test_failure_reasons_are_distinct_and_content_free(self):
        def reason(raw,suffix='.pdf'):
            with self.assertRaises(ValueError) as ctx:docs.read(raw,suffix)
            return str(ctx.exception)
        self.assertIn('şifreli',reason(self._turkish_pdf('Gizli içerik',encrypt='parola')))
        from reportlab.pdfgen import canvas
        buf=io.BytesIO();c=canvas.Canvas(buf);c.showPage();c.save()
        self.assertIn('OCR gerekir',reason(buf.getvalue()))
        broken=reason(b'%PDF-1.4 gizli-bozuk-icerik')
        self.assertIn('bozuk',broken);self.assertNotIn('gizli',broken)
        self.assertIn('bozuk',reason(b'PK not a zip','.docx'))
        self.assertIn('desteklenmiyor',reason(b'x','.doc'))
        with patch.object(docs.subprocess,'run',side_effect=subprocess.TimeoutExpired('worker',30)):
            self.assertIn('süre sınırı',reason(b'x'))
        with patch.object(docs.subprocess,'run',side_effect=FileNotFoundError()):
            self.assertIn('başlatılamadı',reason(b'x'))
        with patch.object(docs.subprocess,'run',side_effect=subprocess.CalledProcessError(1,'worker')):
            self.assertIn('beklenmedik',reason(b'x'))
        with patch('modules.pdf_runtime.open_pdf',side_effect=ImportError('pypdfium2')):
            self.assertEqual(docs._worker(b'%PDF','.pdf'),{'error':'reader_missing'})
        self.assertIn('okuyucu paketi',docs.REASONS['reader_missing'])
        with patch.object(docs.subprocess,'run',return_value=subprocess.CompletedProcess([],0,b'{"error":"bilinmeyen"}',b'')):
            self.assertIn('geçersiz çıktı',reason(b'x'))

    def test_macro_entity_and_zip_expansion_are_rejected(self):
        for extra,xml in [('word/vbaProject.bin','<x/>'),('', '<!DOCTYPE x [<!ENTITY a "secret">]><x>&a;</x>')]:
            buf=io.BytesIO()
            with zipfile.ZipFile(buf,'w') as archive:
                archive.writestr('word/document.xml',xml)
                if extra:archive.writestr(extra,b'macro')
            with self.assertRaises(ValueError):docs.read(buf.getvalue(),'.docx')
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as archive:archive.writestr('word/document.xml','x'*(docs.MAX_BYTES+1))
        with self.assertRaises(ValueError):docs.read(buf.getvalue(),'.docx')

    def test_type_mismatch_legacy_macro_format_and_size_limits(self):
        self.assertTrue(mail_attachments.supported('a.pdf','application/pdf',300000))
        self.assertFalse(mail_attachments.supported('a.docm','application/octet-stream',100))
        self.assertFalse(mail_attachments.supported('a.pdf','text/html',100))
        self.assertFalse(mail_attachments.supported('a.pdf','application/pdf',docs.MAX_BYTES+1))

    def test_timeout_and_malformed_worker_output_never_succeed(self):
        with patch.object(docs.subprocess,'run',side_effect=subprocess.TimeoutExpired('worker',30)):
            with self.assertRaises(ValueError):docs.read(b'file','.pdf')
        with patch.object(docs.subprocess,'run',return_value=subprocess.CompletedProcess([],0,b'{"body":"", "truncated":false}',b'')):
            with self.assertRaises(ValueError):docs.read(b'file','.pdf')

    def test_gmail_document_dispatch_and_exact_size_check(self):
        import base64
        from unittest.mock import Mock
        raw=b'fake pdf';part={'filename':'a.pdf','mimeType':'application/pdf','body':{'size':len(raw),'data':base64.urlsafe_b64encode(raw).decode()}}
        with patch.object(docs,'read',return_value={'body':'extracted','truncated':False}) as read:
            self.assertEqual(mail_attachments.read(Mock(),'M1',part)['body'],'extracted')
            read.assert_called_once_with(raw,'.pdf')
