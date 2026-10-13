import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class Profile:
    slug = 'quality'
    def __init__(self):
        self.data = {'study': {'docs': [{'id': 1, 'title': 'Biyoloji.pdf', 'kind': 'book'}]}}
    def save(self):
        pass


class StudyContentQualityTests(unittest.TestCase):
    def test_publishing_lines_are_not_learning_material(self):
        from modules import study
        profile = Profile()
        text = ('Kitabın Basıldığı Matbaa Adı, 2024\n'
                'MİLLÎ EĞİTİM BAKANLIĞI YAYINLARI ................ : 9604\n'
                'Her hakkı saklıdır ve Millî Eğitim Bakanlığına aittir.\n'
                'Canlıların temel bileşenleri\n'
                'Proteinler amino asitlerden oluşur. Karbonhidratlar enerji sağlar.')
        with tempfile.TemporaryDirectory() as directory, patch.object(study, 'ROOT', Path(directory)), patch.object(study.llm, 'ask', return_value='Proteinler') as model:
            folder = Path(directory) / profile.slug
            folder.mkdir()
            (folder / '1.txt').write_text(text, encoding='utf8')
            info, content = study.source_info(profile, 1, 'Temel Bileşenler')
            self.assertIn('Proteinler', content)
            self.assertNotIn('9604', content)
            self.assertNotIn('Matbaa', content)
            self.assertTrue(all('Temel Bileşenler' in question for question in info['questions']))
            self.assertTrue(all('9604' not in question for question in info['questions']))
            study.ask_source(profile, '', 1)
            self.assertNotIn('9604', model.call_args.args[0])

    def test_metadata_only_source_is_not_presented_as_a_lesson(self):
        from modules import study
        with self.assertRaisesRegex(ValueError, 'ders içeriği'):
            with tempfile.TemporaryDirectory() as directory, patch.object(study, 'ROOT', Path(directory)):
                folder = Path(directory) / 'quality'
                folder.mkdir()
                (folder / '1.txt').write_text('ISBN 123456\nHer hakkı saklıdır.', encoding='utf8')
                study.source_info(Profile(), 1)

    def test_biology_media_does_not_reuse_statistics_cache(self):
        from modules import studymedia as media
        media.reset_cache()
        try:
            with patch.object(media, 'get_youtube_key', return_value=''), patch.object(media, '_wiki_summary', return_value={'title': 'Temel bileşen analizi'}) as wiki, patch.object(media, '_wiki_images', return_value=[{'title': 'Temel bileşen analizi', 'from': 'Vikipedi'}, {'title': 'Protein', 'from': 'Vikipedi'}, {'title': 'Yazılım', 'from': 'Wikimedia'}]):
                generic = media.media('Temel Bileşenler')
                biology = media.media('Temel Bileşenler', 'BİYOLOJİ – 1')
                self.assertTrue(generic['wiki'])
                self.assertEqual(biology['wiki'], {})
                self.assertEqual([image['title'] for image in biology['images']], ['Protein'])
                self.assertIn('biyoloji', wiki.call_args.args[0])
                self.assertEqual(wiki.call_count, 2)
        finally:
            media.reset_cache()
