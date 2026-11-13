import base64
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject
from modules import math_tutor as mt, nxapi, study, study_preview as sp


class OriginalPageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for obj, name, value in [(study, 'ROOT', self.root/'study'), (nxapi, 'FILES_DIR', self.root/'files')]:
            p = patch.object(obj, name, value); p.start(); self.addCleanup(p.stop)
        nxapi.FILES_DIR.mkdir()
        self.profile = SimpleNamespace(slug='alice', data={}, save=lambda: None, _new_id=lambda: 1)
        self.path = nxapi.FILES_DIR/'source.pdf'
        writer = PdfWriter()
        for width, height, color in [(300, 100, '1 0 0'), (100, 300, '0 0 1')]:
            page = writer.add_blank_page(width=width, height=height)
            content = DecodedStreamObject(); content.set_data(f'{color} rg 0 0 {width} {height} re f'.encode())
            page[NameObject('/Contents')] = writer._add_object(content)
        with self.path.open('wb') as f: writer.write(f)
        self.original = self.path.read_bytes()
        self.reply = json.dumps({'text': 'Yalnız bu kısmın açıklaması.', 'visual': None})

    def test_math_preview_uses_whole_original_page_and_selected_page_for_model(self):
        with patch.object(mt.llm, 'ask_image', return_value=self.reply): mt.solve(self.profile, '', str(self.path))
        reference = self.profile.data['study']['math_attachment']
        saved = study._dir(self.profile)/'math'/reference['pdf']
        self.assertEqual(saved.read_bytes(), self.original)
        self.path.unlink()  # Preview must survive removal of the upload.
        view = mt.preview(self.profile, 2)
        self.assertEqual((view['page'], view['pages']), (2, 2))
        with Image.open(io.BytesIO(base64.b64decode(view['image'].split(',')[1]))) as im:
            self.assertAlmostEqual(im.width/im.height, 1/3)
            self.assertEqual(im.getpixel((im.width//2, im.height//2)), (0, 0, 255))
        def model(path, prompt, **kwargs):
            with Image.open(path) as im: self.assertAlmostEqual(im.width/im.height, 1/3)
            self.assertEqual(json.loads(prompt.split('\n')[0])['scope'], 'question')
            return self.reply
        with patch.object(mt.llm, 'ask_image', side_effect=model):
            mt.solve(self.profile, 'Çöz', selection={'image_id': view['image_id'], 'page': 2, 'full_page': True})
        self.assertEqual(saved.read_bytes(), self.original)
        with patch.object(mt.llm, 'ask_image', return_value=self.reply):
            mt.solve(self.profile, 'Bu alanı anlat', selection={'image_id': view['image_id'], 'page': 2, 'box': [0, 0, .5, 1]})
        self.assertEqual(saved.read_bytes(), self.original)
        self.assertEqual(mt.preview(self.profile, 2)['image_id'], view['image_id'])
        mt.clear(self.profile); self.assertFalse(saved.exists())

    def test_source_keeps_original_bytes_and_removal_cleans_copy(self):
        with patch.object(study, '_read_isolated', return_value='Denklem ve üs hesaplarını açıklayan ders içeriği.\fİkinci sayfanın ders içeriği.'):
            item = study.add(self.profile, str(self.path))
        saved = study._dir(self.profile)/'1.source.pdf'
        self.assertEqual(saved.read_bytes(), self.original)
        view = sp.source(self.profile, item['id'], 2)
        self.assertTrue(view['source_page']); self.assertNotIn('text', view)
        self.assertEqual(view['image_id'], 'source:1:2')
        with patch.object(study.llm, 'ask_image', return_value='Seçili kısmın açıklaması.') as model:
            study.ask_source(self.profile, 'Yalnız bu kısmı anlat', 1, selection={'image_id': view['image_id'], 'page': 2, 'box': [0, 0, .5, 1]})
            self.assertIn('Sayfa: 2', model.call_args.args[1])
            self.assertIn('Yalnız seçili kırpılmış alanı', model.call_args.args[1])
        study.remove(self.profile, 1); self.assertFalse(saved.exists())

    def test_bad_page_stale_key_and_foreign_profile_do_not_reach_model(self):
        with patch.object(mt.llm, 'ask_image', return_value=self.reply): mt.solve(self.profile, '', str(self.path))
        view = mt.preview(self.profile, 1)
        for page in [0, 3, True]:
            with self.assertRaises(ValueError): mt.preview(self.profile, page)
        with patch.object(mt.llm, 'ask_image') as model, self.assertRaises(ValueError):
            mt.solve(self.profile, 'Anlat', selection={'image_id': view['image_id'], 'page': 2, 'full_page': True})
        model.assert_not_called()
        other = SimpleNamespace(slug='bob', data={}, save=lambda: None)
        with self.assertRaises(ValueError): sp.source(other, 1)

    def test_legacy_source_explains_missing_original(self):
        self.profile.data = {'study': {'docs': [{'id': 1, 'title': 'old.pdf'}]}}
        (study._dir(self.profile)/'1.txt').write_text('Denklem hesaplarının ders içeriği.', encoding='utf8')
        view = sp.source(self.profile, 1)
        self.assertNotIn('image', view)
        self.assertIn('yeniden yükle', view['note'])
        self.assertTrue(view['missing_original'])

    def legacy_source(self, **fields):
        item = {'id': 1, 'title': 'old.pdf', **fields}
        self.profile.data = {'study': {'docs': [item], 'progress': {'kept': True}}}
        (study._dir(self.profile)/'1.txt').write_text('Denklem hesaplarının ders içeriği.', encoding='utf8')
        return item

    def test_restore_legacy_original_keeps_id_progress_and_renders_real_page(self):
        item = self.legacy_source()
        with patch.object(study, '_read_isolated', return_value='Denklem hesaplarının  ders içeriği.\n'):
            self.assertEqual(sp.restore_original(self.profile, 1, str(self.path)), {'ok': True, 'id': 1})
        self.assertIs(self.profile.data['study']['docs'][0], item)
        self.assertEqual(self.profile.data['study']['progress'], {'kept': True})
        self.assertEqual((study._dir(self.profile)/'1.source.pdf').read_bytes(), self.original)
        self.path.unlink()
        view = sp.source(self.profile, 1, 2)
        self.assertEqual((view['page'], view['pages']), (2, 2))
        with Image.open(io.BytesIO(base64.b64decode(view['image'].split(',')[1]))) as im:
            self.assertEqual(im.getpixel((im.width//2, im.height//2)), (0, 0, 255))

    def test_existing_original_without_metadata_flag_still_renders(self):
        self.legacy_source()
        (study._dir(self.profile)/'1.source.pdf').write_bytes(self.original)
        self.assertTrue(sp.source(self.profile, 1)['source_page'])

    def test_wrong_original_and_foreign_profile_leave_record_unchanged(self):
        item = self.legacy_source()
        with patch.object(study, '_read_isolated', return_value='Farklı bir kaynak.'), self.assertRaises(ValueError):
            sp.restore_original(self.profile, 1, str(self.path))
        self.assertNotIn('original_pdf', item)
        self.assertFalse((study._dir(self.profile)/'1.source.pdf').exists())
        other = SimpleNamespace(slug='bob', data={}, save=lambda: None)
        with self.assertRaises(ValueError): sp.restore_original(other, 1, str(self.path))

    def test_hash_verification_and_stale_record_reject_before_replacement(self):
        import hashlib
        self.legacy_source(source_hash='wrong')
        with patch.object(study, '_read_isolated') as extract, self.assertRaises(ValueError):
            sp.restore_original(self.profile, 1, str(self.path))
        extract.assert_not_called()
        self.legacy_source(source_hash=hashlib.sha256(self.original).hexdigest())
        original_render = sp.pdf_page
        def changed(*args):
            self.profile.data['study']['source_generation'] = 1
            return original_render(*args)
        with patch.object(sp, 'pdf_page', side_effect=changed), self.assertRaises(ValueError):
            sp.restore_original(self.profile, 1, str(self.path))
        self.assertFalse((study._dir(self.profile)/'1.source.pdf').exists())

    def test_restore_existing_original_never_overwrites_a_foreign_file(self):
        import hashlib
        self.legacy_source(source_hash=hashlib.sha256(self.original).hexdigest())
        target = study._dir(self.profile)/'1.source.pdf'
        target.write_bytes(b'foreign existing original')
        with self.assertRaises(FileExistsError):
            sp.restore_original(self.profile, 1, str(self.path))
        self.assertEqual(target.read_bytes(), b'foreign existing original')
        self.assertFalse(self.profile.data['study']['docs'][0].get('original_pdf'))
        self.assertFalse(list(target.parent.glob('.jarvis-original-*')))

    def test_restore_failed_metadata_save_rolls_back_only_new_original(self):
        import hashlib
        item = self.legacy_source(source_hash=hashlib.sha256(self.original).hexdigest())
        self.profile.save = lambda: (_ for _ in ()).throw(OSError('disk full'))
        target = study._dir(self.profile)/'1.source.pdf'
        with self.assertRaises(OSError):
            sp.restore_original(self.profile, 1, str(self.path))
        self.assertFalse(target.exists())
        self.assertNotIn('original_pdf', item)
        self.assertEqual(item['source_hash'], hashlib.sha256(self.original).hexdigest())
        self.assertFalse(list(target.parent.glob('.jarvis-original-*')))

    def test_unreadable_original_keeps_text_and_restore_action(self):
        self.legacy_source()
        saved = study._dir(self.profile)/'1.source.pdf'
        saved.write_bytes(b'Not a PDF')
        view = sp.source(self.profile, 1)
        self.assertNotIn('image', view)
        self.assertEqual(view['text'], 'Denklem hesaplarının ders içeriği.')
        self.assertTrue(view['missing_original'])
        self.assertIn('Kayıtlı metin', view['note'])
        self.assertNotIn('saklanmamış', view['note'])
        self.assertEqual(saved.read_bytes(), b'Not a PDF')

    def test_unicode_file_is_opened_as_stream_and_real_pages_remain_correct(self):
        import pypdfium2 as pdfium
        path = self.root/'Hamdi İşi, Çalışma'/ 'Özgün Şema.pdf'
        path.parent.mkdir();path.write_bytes(self.original)
        real_document = pdfium.PdfDocument
        def stream_document(stream):
            self.assertFalse(isinstance(stream, (str, Path)))
            self.assertTrue(hasattr(stream, 'readinto'))
            return real_document(stream)
        with patch.object(pdfium, 'PdfDocument', side_effect=stream_document):
            image, pages = sp.pdf_page(path, 2)
        self.assertEqual(pages, 2)
        self.assertEqual(image.getpixel((image.width//2, image.height//2)), (0, 0, 255))
        path.unlink()  # Both reader and file handles have been released.

    def test_parallel_page_reads_are_serialized_and_keep_correct_page_colors(self):
        import pypdfium2 as pdfium
        from concurrent.futures import ThreadPoolExecutor
        from contextlib import contextmanager
        import threading
        import time
        document = pdfium.PdfDocument
        counter = threading.Lock()
        state = {'active': 0, 'peak': 0}
        @contextmanager
        def tracked(stream):
            with counter:
                state['active'] += 1
                state['peak'] = max(state['peak'], state['active'])
            try:
                time.sleep(.01)
                with document(stream) as opened:
                    yield opened
            finally:
                with counter:
                    state['active'] -= 1
        with patch.object(pdfium, 'PdfDocument', side_effect=tracked), ThreadPoolExecutor(max_workers=6) as pool:
            pages = [1, 2] * 6
            results = list(pool.map(lambda page: sp.pdf_page(self.path, page), pages))
        self.assertEqual(state['peak'], 1)
        for page, (image, count) in zip(pages, results):
            self.assertEqual(count, 2)
            self.assertEqual(image.getpixel((image.width//2, image.height//2)), (255, 0, 0) if page == 1 else (0, 0, 255))
