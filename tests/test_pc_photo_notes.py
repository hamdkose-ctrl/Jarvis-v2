import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
from types import SimpleNamespace
from modules import main_documents, note_images, personalization


class PhotoNotesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patches = [patch.object(note_images, 'DATA_DIR', self.root),
                        patch.object(personalization, 'USERS_DIR', self.root),
                        patch('modules.nxapi.allowed', side_effect=lambda value: Path(value))]
        for p in self.patches: p.start()
        self.profile = personalization.Profile('Test User')
        self.source = self.root/'source.png'
        Image.new('RGB', (24, 24), 'red').save(self.source)

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def test_image_persists_and_original_is_unchanged(self):
        original = self.source.read_bytes()
        item = note_images.add(self.profile, 'Örnek', str(self.source), 'Başlık')
        reloaded = personalization.Profile('Test User')
        self.assertEqual(reloaded.data['items'][0]['photo'], item['photo'])
        self.assertEqual(reloaded.data['items'][0]['title'], 'Başlık')
        self.assertEqual(reloaded.data['items'][0]['text'], 'Örnek')
        self.assertTrue(note_images.preview(reloaded, item['id']).startswith('data:image/jpeg;base64,'))
        self.assertEqual(self.source.read_bytes(), original)

    def test_text_only_and_image_only(self):
        self.assertNotIn('photo', note_images.add(self.profile, 'Metin'))
        self.assertEqual(note_images.add(self.profile, '', str(self.source))['text'], 'Görsel not')

    def test_another_profile_cannot_open_image(self):
        item = note_images.add(self.profile, 'Özel', str(self.source))
        other = personalization.Profile('Other User')
        other.data['items'] = [item]
        with self.assertRaises(ValueError): note_images.preview(other, item['id'])

    def test_failed_save_rolls_back_image_and_note(self):
        with patch.object(self.profile, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): note_images.add(self.profile, 'Örnek', str(self.source))
        self.assertEqual(self.profile.data['items'], [])
        self.assertEqual(list(note_images.folder(self.profile).glob('*.png')), [])

    def test_existing_note_image_name_cannot_be_overwritten(self):
        directory = note_images.folder(self.profile)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / 'claimed-image.png'
        target.write_bytes(b'foreign image content')
        identity = SimpleNamespace(uuid4=lambda: SimpleNamespace(hex='claimed-image'))
        with patch.object(note_images, 'uuid', identity):
            with self.assertRaises(FileExistsError):
                note_images.add(self.profile, 'Not', str(self.source))
        self.assertEqual(target.read_bytes(), b'foreign image content')
        self.assertEqual(self.profile.data['items'], [])
        self.assertFalse(list(directory.glob('.jarvis-note-*')))

    def test_failed_note_publish_does_not_leave_partial_file(self):
        with patch.object(note_images.os, 'link',
                          side_effect=OSError('no create-only publish')):
            with self.assertRaises(OSError):
                note_images.add(self.profile, 'Not', str(self.source))
        directory = note_images.folder(self.profile)
        self.assertFalse(list(directory.glob('*.png')))
        self.assertFalse(list(directory.glob('.jarvis-note-*')))
        self.assertEqual(self.profile.data['items'], [])

    def test_empty_and_invalid_image_are_rejected(self):
        with self.assertRaises(ValueError): note_images.add(self.profile, '')
        self.source.write_text('not an image')
        with self.assertRaises(OSError): note_images.add(self.profile, '', str(self.source))
        self.assertEqual(self.profile.data['items'], [])


class PhonePhotoPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'incoming.png'
        self.source.write_bytes(b'original incoming image')
        self.runtime = SimpleNamespace(
            _PHOTO_DIR=self.root / 'photos',
            profile=SimpleNamespace(slug='owner', data={'items': []}),
            time=SimpleNamespace(
                strftime=lambda *_args: '20000101_000000',
                time=time.time,
            ),
            secrets=SimpleNamespace(token_hex=lambda _size: 'test-nonce'),
        )
        self.target = (self.runtime._PHOTO_DIR / 'owner' /
                       '20000101_000000_test-nonce.png')

    def test_phone_photo_publishes_complete_file_then_releases_source(self):
        path = main_documents._keep_photo(self.runtime, str(self.source))
        self.assertEqual(path, str(self.target))
        self.assertEqual(self.target.read_bytes(), b'original incoming image')
        self.assertFalse(self.source.exists())
        self.assertEqual(list(self.target.parent.glob('.jarvis-photo-*')), [])

    def test_phone_photo_never_overwrites_a_concurrent_target(self):
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_bytes(b'other owner content')
        with self.assertRaises(FileExistsError):
            main_documents._keep_photo(self.runtime, str(self.source))
        self.assertEqual(self.target.read_bytes(), b'other owner content')
        self.assertEqual(self.source.read_bytes(), b'original incoming image')
        self.assertEqual(list(self.target.parent.glob('.jarvis-photo-*')), [])

    def test_phone_photo_failed_publish_exposes_no_partial_artifact(self):
        with patch('os.link', side_effect=OSError('not supported')):
            with self.assertRaises(OSError):
                main_documents._keep_photo(self.runtime, str(self.source))
        self.assertFalse(self.target.exists())
        self.assertTrue(self.source.exists())
        self.assertEqual(list(self.target.parent.glob('.jarvis-photo-*')), [])
