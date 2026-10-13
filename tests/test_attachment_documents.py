import io
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
