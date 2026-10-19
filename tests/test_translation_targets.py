"""Target-language parsing regression tests; no model or translation service is called."""
import unittest

from modules.translation_targets import target_from_command


LANGUAGES = (
    ('Türkçe', 'turkce', 'Türkçe', 'türkçeye', 'turkceye', 'türkçeden', 'turkceden'),
    ('İngilizce', 'ingilizce', 'İngilizce', 'ingilizceye', 'ingilizceye', 'ingilizceden', 'ingilizceden'),
    ('Almanca', 'almanca', 'Almanca', 'almancaya', 'almancaya', 'almancadan', 'almancadan'),
    ('Fransızca', 'fransizca', 'Fransızca', 'fransızcaya', 'fransizcaya', 'fransızcadan', 'fransizcadan'),
    ('Arapça', 'arapca', 'Arapça', 'arapçaya', 'arapcaya', 'arapçadan', 'arapcadan'),
    ('Rusça', 'rusca', 'Rusça', 'rusçaya', 'ruscaya', 'rusçadan', 'ruscadan'),
    ('İspanyolca', 'ispanyolca', 'İspanyolca', 'ispanyolcaya', 'ispanyolcaya', 'ispanyolcadan', 'ispanyolcadan'),
)


class TranslationTargetsTests(unittest.TestCase):
    def test_all_language_names_in_turkish_and_ascii(self):
        for native, ascii_name, expected, *_ in LANGUAGES:
            for name in (native, ascii_name):
                with self.subTest(name=name):
                    self.assertEqual(target_from_command(f'Metni {name} çevir'), expected)

    def test_destination_suffixes_in_turkish_and_ascii(self):
        for _, _, expected, native_target, ascii_target, *_ in LANGUAGES:
            for target in (native_target, ascii_target):
                with self.subTest(target=target):
                    self.assertEqual(target_from_command(f'Metni {target} çevir'), expected)

    def test_straight_and_curly_apostrophe_destination_suffixes(self):
        for name, _, expected, target, *_ in LANGUAGES:
            suffix = target[-2:]
            for apostrophe in ("'", '’'):
                command = f'Metni {name}{apostrophe}{suffix} çevir'
                with self.subTest(command=command):
                    self.assertEqual(target_from_command(command), expected)

    def test_plain_source_suffixes_alone_are_not_destinations(self):
        for *_, native_source, ascii_source in LANGUAGES:
            for source in (native_source, ascii_source):
                with self.subTest(source=source):
                    self.assertEqual(target_from_command(f'{source} çevir'), '')

    def test_source_before_destination_does_not_replace_target(self):
        self.assertEqual(target_from_command('ingilizceden turkceye çevir'), 'Türkçe')
        self.assertEqual(target_from_command('Türkçeden İngilizceye çevir'), 'İngilizce')

    def test_source_after_destination_is_not_the_last_target(self):
        self.assertEqual(target_from_command('Türkçeye İngilizceden çevir'), 'Türkçe')
        self.assertEqual(target_from_command('Almancaya Fransızcadan çevir'), 'Almanca')

    def test_last_language_wins_for_every_pair(self):
        for first, *rest in LANGUAGES:
            for last, _, expected, *_ in LANGUAGES:
                with self.subTest(first=first, last=last):
                    self.assertEqual(target_from_command(f'{first} değil {last} çevir'), expected)
        self.assertEqual(target_from_command('Türkçe İngilizce Almanca'), 'Almanca')

    def test_no_language_name_returns_empty(self):
        for command in ('', 'Bu metni çevir', 'Dosyayı aç', 'İngilizceleşmiş sözcük'):
            with self.subTest(command=command):
                self.assertEqual(target_from_command(command), '')

    def test_uppercase_dotted_and_ascii_i(self):
        for command, expected in (
            ('İNGİLİZCE', 'İngilizce'), ('INGILIZCE', 'İngilizce'),
            ('İNGİLİZCEYE ÇEVİR', 'İngilizce'), ('İSPANYOLCA', 'İspanyolca'),
            ('FRANSIZCAYA CEVIR', 'Fransızca'), ('TÜRKÇEYE ÇEVİR', 'Türkçe'),
        ):
            with self.subTest(command=command):
                self.assertEqual(target_from_command(command), expected)

    @unittest.expectedFailure  # Source apostrophe is currently mistaken for a target.
    def test_straight_apostrophe_source_only_is_not_a_destination(self):
        self.assertEqual(target_from_command("İngilizce'den çevir"), '')

    @unittest.expectedFailure  # Same source-suffix bug with a curly apostrophe.
    def test_curly_apostrophe_source_only_is_not_a_destination(self):
        self.assertEqual(target_from_command('Almanca’dan çevir'), '')


if __name__ == '__main__':
    unittest.main()
