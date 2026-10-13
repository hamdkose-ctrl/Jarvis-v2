import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from modules import note_images, personalization


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

    def test_empty_and_invalid_image_are_rejected(self):
        with self.assertRaises(ValueError): note_images.add(self.profile, '')
        self.source.write_text('not an image')
        with self.assertRaises(OSError): note_images.add(self.profile, '', str(self.source))
        self.assertEqual(self.profile.data['items'], [])
