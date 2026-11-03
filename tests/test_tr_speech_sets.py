"""Saf taşıma sözleşmesi: eski söyleyişler ve gerçek EngineContext bağlantısı.

Gerçek mikrofon veya model ölçülmez. Beklentiler taşıma öncesi main
d5f195bda37164cfa94cd10e597e131d7c70bec8 değerlerinden kopyalandı.
"""
import ast
import importlib
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from modules.turkish_text import lower

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    'WEATHER_STOP': {
        'bugün', 'yarın', 'şimdi', 'şuan', 'bana', 'bugünkü', 'acaba', 'dışarı',
        'dışarıda', 'burada', 'bu', 'şu', 'bir', 've', 'hava', 'nasıl', 'ne', 'kaç',
    },
    'NAME_SUFFIXES': {'im', 'yim', 'ye', 'ya', 'de', 'da', 'in', 'nin', 'dir', 'ydi'},
    'JARVIS_MISHEAR': {
        'servis', 'travis', 'carvis', 'cervis', 'jervis', 'çarviş', 'harvis', 'garvis',
        'darvis', 'yarış', 'yarvis', 'jarviş', 'jarvisi', 'service', 'jarves', 'javis', 'carviş',
    },
}
# Motor yüzeyindeki aynalar: PR3A'dan sonra `WEATHER_STOP` yalnız canonical şehir çözümünde
# (`brain_understanding`) doğrudan kümeden okunur, `runtime._WEATHER_STOP` olarak taşınmaz.
RUNTIME_MIRRORED = ('NAME_SUFFIXES', 'JARVIS_MISHEAR')


class TurkishSpeechSetTests(unittest.TestCase):
    def test_constants_are_frozensets_with_exact_old_contents(self):
        sets = importlib.import_module('modules.tr_speech_sets')
        for name, expected in EXPECTED.items():
            with self.subTest(name=name):
                actual = getattr(sets, name)
                self.assertIsInstance(actual, frozenset)
                self.assertEqual(actual, expected)

    def test_every_item_is_lowercase_whitespace_free_and_turkish_normalized(self):
        sets = importlib.import_module('modules.tr_speech_sets')
        invalid = [(name, word) for name in EXPECTED for word in getattr(sets, name)
                   if not isinstance(word, str) or not word or word != word.lower()
                   or word != lower(word) or any(c.isspace() for c in word)]
        self.assertEqual(invalid, [], 'Davranış değişmesin: bozuk eski öğeyi düzeltmeden PR açıklamasında bildir.')

    def test_data_module_contains_only_docstring_and_three_literal_frozensets(self):
        tree = ast.parse((ROOT / 'modules' / 'tr_speech_sets.py').read_text(encoding='utf-8'))
        self.assertIsNotNone(ast.get_docstring(tree))
        self.assertEqual(len(tree.body), 4)
        for node in tree.body[1:]:
            self.assertIsInstance(node, ast.Assign)
            self.assertEqual(len(node.targets), 1)
            self.assertIn(node.targets[0].id, EXPECTED)
            self.assertIsInstance(node.value, ast.Call)
            self.assertIsInstance(node.value.func, ast.Name)
            self.assertEqual(node.value.func.id, 'frozenset')
            self.assertEqual(len(node.value.args), 1)
            self.assertEqual(node.value.keywords, [])
            self.assertEqual(ast.literal_eval(node.value.args[0]), EXPECTED[node.targets[0].id])

    def _context(self):
        # Mevcut test_engine_modular.context yolu: gerçek kurucu, geçici DATA_DIR,
        # kök log tutucularının ve ön-getirme havuzunun garantili temizlenmesi.
        import test_engine_modular as fixture
        engine = fixture.engine_runtime
        owner = SimpleNamespace(slug='speech-test', name='Speech Test')
        with patch.object(engine, 'Profile', return_value=owner), \
                patch.object(engine, 'get_active', return_value=owner.name), \
                patch.object(engine, 'migrate_legacy'), \
                patch.object(engine.system_control, 'installed_apps'), \
                patch.object(engine._llm, 'set_user_context'):
            return fixture.ModularEngineTests.context(self)

    def test_real_engine_context_keeps_old_attribute_names_and_shared_values(self):
        sets = importlib.import_module('modules.tr_speech_sets')
        runtime = self._context()
        for name in RUNTIME_MIRRORED:
            with self.subTest(name=name):
                self.assertEqual(getattr(runtime, '_' + name), getattr(sets, name))
                self.assertIs(getattr(runtime, '_' + name), getattr(sets, name))

    def test_weather_stop_is_read_by_its_canonical_owner_not_the_engine_surface(self):
        # PR3A: kümenin tek motor okuyucusu emekli edilen ham şehir ayrıştırıcısı
        # (engine_tools._city_in) idi; ayna artık yüzeyde durmuyor. İçerik kilidi
        # test_constants_are_frozensets_with_exact_old_contents'de; okuyucu canonical.
        runtime = self._context()
        self.assertFalse(hasattr(runtime, '_WEATHER_STOP'))
        source = (ROOT / 'modules' / 'brain_understanding.py').read_text(encoding='utf-8')
        self.assertIn('from modules.tr_speech_sets import WEATHER_STOP', source)


if __name__ == '__main__':
    unittest.main()
