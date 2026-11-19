"""OMURGA — çağrısız ölü sembollerin fiziksel göçü (18 Kasım 2026).

Bu paket, üretimde hiçbir çağrı noktası kalmamış yüzeyleri "uykuda bırakmak" yerine siler.
Testler üç şeyi birlikte kanıtlar: (1) sembol modülünde ve kaynak metninde fiziksen yoktur,
(2) hiçbir üretim dosyası adını anmaz (sessiz "yaşıyor" gibi kalamaz), (3) o yüzeyin taşıdığı
sorumluluğun TEK sahibi hâlâ canlı ve çağrılabilir. Ayrıca hiçbir çitin (konuşma isteği şeması,
öneri kind kümesi, kullanıcıya özel anahtar izolasyonu) bu silmeyle gevşemediği pozitif
testlerle ölçülür; silinmeyen/bırakılan caller-zero yüzeyler `docs/BEKLEYEN_ISLER.md` içinde
kayıtlıdır ve bu dosya o kaydı denetler.

Mock'un kendi davranışı sınanmaz: üretim modülleri ve gerçek kaynak metinleri okunur.
"""
import ast
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

# (modül, silinen ad) — hiçbiri üretimde çağrılmıyordu.
RETIRED = (
    ('modules/brain_delegate.py', 'try_run'),
    ('modules/brain_delegate.py', '_safe'),
    ('modules/brain_delegate.py', '_render'),
    ('modules/brain_understanding.py', 'notes_read_view'),
    ('modules/codegen.py', 'scaffold'),
    ('modules/proactive_advisor.py', 'PRIORITIES'),
    ('modules/richtext.py', 'inline_parts'),
    ('modules/richtext.py', 'INLINE'),
    ('modules/vision.py', 'preview_b64'),
    ('modules/voice_core.py', 'SPEECH_STAGES'),
    ('modules/wakeword.py', 'THRESHOLD'),
    ('modules/when.py', 'WEEKDAYS_TITLE'),
    ('modules/llm.py', 'OLLAMA_BIG_MODEL'),
    ('config.py', 'GROQ_KEY_FILE'),
    ('config.py', 'save_groq_key'),
    ('config.py', 'get_groq_key'),
)
RETIRED_NAMES = tuple(sorted({name for _path, name in RETIRED} | {'GROQ_API_KEY'}))
# `_safe` ve `_render` başka modüllerde kendi yerel yardımcıları olan sıradan özel adlardır;
# bunların anlamı kanıtı ait oldukları modülden fiziksen kalkmasıdır (yukarıdaki AST/satır
# kilidi). Depo geneli ad taraması yalnız ayırt edici adları kapsar.
GLOBAL_LOCK_NAMES = tuple(name for name in RETIRED_NAMES if name not in {'_safe', '_render'})


def _module_for(relative: str):
    import importlib
    return importlib.import_module(relative[:-3].replace('/', '.').replace('config.', 'config'))


def _production_sources():
    return sorted(list(ROOT.glob('*.py')) + list((ROOT / 'modules').glob('*.py')))


class RetiredSymbolIsGoneTests(unittest.TestCase):
    def test_each_retired_symbol_is_absent_from_its_module_and_its_source(self):
        for relative, name in RETIRED:
            module = _module_for(relative)
            source = (ROOT / relative).read_text(encoding='utf-8')
            with self.subTest(symbol=f'{relative}:{name}'):
                self.assertFalse(hasattr(module, name), name)
                self.assertNotIn(name, source)

    def test_the_retired_names_are_top_level_declarations_not_buried_calls(self):
        # Definition was really at module level: the AST of each file no longer binds the name.
        for relative, name in RETIRED:
            tree = ast.parse((ROOT / relative).read_text(encoding='utf-8'))
            bound = {t.id for node in ast.walk(tree) if isinstance(node, ast.Assign)
                     for t in node.targets if isinstance(t, ast.Name)}
            bound |= {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
            with self.subTest(symbol=f'{relative}:{name}'):
                self.assertNotIn(name, bound)

    def test_no_production_file_mentions_a_retired_name_at_all(self):
        for path in _production_sources():
            text = path.read_text(encoding='utf-8')
            hits = sorted({name for name in GLOBAL_LOCK_NAMES
                           if re.search(r'\b' + re.escape(name) + r'\b', text)})
            with self.subTest(module=path.name):
                self.assertEqual(hits, [])

    def test_the_global_groq_key_surface_is_gone_from_the_config_module(self):
        import config
        for name in ('GROQ_KEY_FILE', 'save_groq_key', 'get_groq_key'):
            with self.subTest(symbol=name):
                self.assertFalse(hasattr(config, name), name)

    def test_the_codegen_docstring_stops_promising_an_iskelet_path(self):
        import modules.codegen as codegen
        self.assertNotIn('iskelet', codegen.__doc__ or '')


class SingleOwnerStillLiveTests(unittest.TestCase):
    """Her silinen yüzeyin sorumluluğunun tek sahibi canlı ve ölçülebilir olmalı."""

    def test_groq_keys_are_read_only_from_the_owning_user_profile(self):
        from modules import llm
        import config
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            with patch.object(config, 'DATA_DIR', data):
                (data / 'groq_key.txt').write_text('global-dead-key', encoding='utf-8')
                self.assertEqual(llm.user_groq_key(None), '')
                self.assertEqual(llm.user_groq_key('alice'), '')     # ortak fallback yok
                llm.set_user_groq_key('alice', 'ALICE-KEY')
                self.assertEqual(llm.user_groq_key('alice'), 'ALICE-KEY')
                self.assertEqual(llm.user_groq_key('bob'), '')       # kullanıcılar havuzlanmaz
                self.assertTrue((data / 'keys' / 'alice.groq.txt').is_file())
                llm.set_user_groq_key('alice', None)
                self.assertEqual(llm.user_groq_key('alice'), '')

    def test_wakeword_threshold_owner_is_the_sensitivity_setting(self):
        from modules import wakeword
        cases = (({'wake_sensitivity': 1}, 0.55), ({'wake_sensitivity': 5}, 0.10),
                 ({}, 0.18), ({'wake_sensitivity': 'bozuk'}, 0.18), ({'wake_sensitivity': 99}, 0.10))
        for settings, expected in cases:
            with self.subTest(settings=settings), patch.object(wakeword, 'load_settings', lambda: settings):
                self.assertEqual(wakeword.sensitivity_threshold(), expected)
        source = (ROOT / 'modules' / 'wakeword.py').read_text(encoding='utf-8')
        self.assertIn('max(sensitivity_threshold(), min_threshold)', source)

    def test_the_speech_request_fence_still_rejects_an_unknown_event_kind(self):
        from modules import voice_core
        request = voice_core.SpeechRequest(owner='a', request_id='r1', voice_id='v1', text='Merhaba')
        self.assertEqual(request.kind, 'reply')
        with self.assertRaises(ValueError):
            voice_core.SpeechRequest(owner='a', request_id='r2', voice_id='v1', text='Merhaba', kind='stage')
        with self.assertRaises(ValueError):
            voice_core.SpeechRequest(owner='a', request_id='r3', voice_id='v1', text='Merhaba',
                                     schema='speech.request.v1')

    def test_the_screen_preview_still_comes_from_the_multi_size_owner(self):
        from modules import vision
        with patch.object(vision, 'current_image', lambda: None):
            self.assertEqual(vision.preview_multi((480, 270)), [None])
        self.assertTrue(callable(vision._b64))
        bridge = (ROOT / 'web.py').read_text(encoding='utf-8')
        self.assertIn('vision.preview_multi', bridge)

    def test_richtext_keeps_the_surface_that_is_actually_consumed(self):
        from modules import richtext
        self.assertEqual(richtext.speakable('**kalın** ve `kod`'), 'kalın ve kod')
        blocks = richtext.split_blocks('giriş\n```python\nprint(1)\n```\nson')
        self.assertEqual([kind for kind, _lang, _text in blocks], ['text', 'code', 'text'])
        self.assertEqual(richtext.extension('Python'), '.py')
        self.assertEqual(richtext.extension('bilinmeyen'), '.txt')

    def test_codegen_still_generates_and_saves_without_the_removed_planner(self):
        from modules import codegen
        self.assertTrue(callable(codegen.generate) and callable(codegen.save))
        self.assertIn('```dil bloğunda ver', codegen.SYSTEM)

    def test_the_specialist_directory_and_durable_step_owner_are_untouched(self):
        from modules import brain_delegate, specialist_orchestrator
        for name in ('plan', 'run', 'catalog', 'assign'):
            self.assertTrue(callable(getattr(brain_delegate, name)), name)
        for name in ('validate', 'run', 'execute_step'):
            self.assertTrue(callable(getattr(specialist_orchestrator, name)), name)

    def test_when_still_resolves_weekdays_from_the_single_tuple(self):
        from modules import when
        self.assertIsNotNone(when.parse_when('yarın 14:30 su iç')[0])
        source = (ROOT / 'modules' / 'when.py').read_text(encoding='utf-8')
        self.assertIn('WEEKDAYS.index', source)
        self.assertIn('MONTHS_TITLE[d.month - 1]', source)

    def test_proactive_advisor_keeps_the_enforced_kind_set_and_priority(self):
        from modules import proactive_advisor as advisor
        item = advisor.suggest('risk', 'Yedeği kontrol et')
        self.assertEqual(item['priority'], 'low')
        self.assertEqual(advisor.render(item).startswith('Burada dikkat et: '), True)
        self.assertIsNone(advisor.suggest('bilinmeyen-tür', 'metin'))
        self.assertFalse(advisor.SuggestionPolicy.from_settings({'proactive_suggestions': False}).enabled)


class DeferredResidueIsRecordedTests(unittest.TestCase):
    """Silinmeyen caller-zero yüzeyler sessizce 'temizlendi' olamaz: kayıtta durur."""

    def test_the_open_items_document_names_each_deferred_surface(self):
        text = (ROOT / 'docs' / 'BEKLEYEN_ISLER.md').read_text(encoding='utf-8')
        for marker in ('engine_live_brain._live_command', 'specialist_orchestrator.run',
                       'local_changes.json', 'verify_synthesis', 'stt_fixes'):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)


if __name__ == '__main__':
    unittest.main()
