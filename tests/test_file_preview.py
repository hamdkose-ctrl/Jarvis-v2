import base64
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
from reportlab.pdfgen import canvas

from modules import nxapi
from web_files import WebFiles


class FilePreviewTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'files'
        self.root.mkdir()
        roots = patch.object(nxapi, '_roots', return_value=[self.root])
        roots.start()
        self.addCleanup(roots.stop)
        self.bridge = WebFiles()
        self.bridge._runtime = SimpleNamespace(_p=lambda: SimpleNamespace(slug='alice'))

    def render(self, file):
        result = self.bridge.file_preview(str(file), 'alice')
        self.assertEqual(result['owner'], 'alice')
        self.assertTrue(result['image'].startswith('data:image/webp;base64,'))
        payload = base64.b64decode(result['image'].split(',', 1)[1], validate=True)
        return Image.open(io.BytesIO(payload))

    def test_pdf_first_page_is_rasterized_and_bounded(self):
        file = self.root / 'Örnek rapor.pdf'
        pdf = canvas.Canvas(str(file), pagesize=(600, 800))
        pdf.setFillColorRGB(1, 0, 0)
        pdf.rect(0, 0, 600, 800, stroke=0, fill=1)
        pdf.showPage()
        pdf.setFillColorRGB(0, 0, 1)
        pdf.rect(0, 0, 600, 800, stroke=0, fill=1)
        pdf.save()
        with self.render(file) as image:
            self.assertEqual(image.format, 'WEBP')
            self.assertEqual(image.size, (840, 1120))
            red, _, blue = image.getpixel((420, 560))
            self.assertGreater(red, 250)
            self.assertLess(blue, 5)

    def test_image_is_downscaled_and_wrong_format_is_rejected(self):
        file = self.root / 'Görsel.png'
        with Image.new('RGB', (1200, 600), '#275c89') as image:
            image.save(file)
        with self.render(file) as image:
            self.assertEqual(image.size, (840, 420))
        renamed = self.root / 'Görsel.jpg'
        renamed.write_bytes(file.read_bytes())
        with self.assertRaisesRegex(ValueError, 'açılamadı'):
            self.render(renamed)

    def test_owner_and_allowed_roots_are_required(self):
        outside = self.root.parent / 'outside.png'
        outside.write_bytes(b'outside')
        with self.assertRaisesRegex(ValueError, 'kullanıcı değişti'):
            self.bridge.file_preview(str(outside), 'bob')
        with self.assertRaisesRegex(ValueError, 'erişilebilir değil'):
            self.render(outside)

    def test_size_limit_applies_before_render(self):
        file = self.root / 'Büyük.pdf'
        with file.open('wb') as handle:
            handle.truncate(20 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(ValueError, '20 MB'):
            self.render(file)
