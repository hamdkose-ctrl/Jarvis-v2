"""SES VE İLETİŞİM §9 — Gemini Live hattının gerçekten emekli olduğunun kanıtı.

Live motoru hiçbir modda çalışmıyordu (`enabled()` sabit False), ama dosyaları, ayar anahtarları ve
arayüz sürgüleri duruyordu. Bu dosya dört şeyi kilitler: (1) Live yığını fiziksel olarak yoktur ve
üretim kodu onu import etmez, (2) tüketicisi olmayan ayar anahtarı/sürgü kalmamıştır, (3) yaşayan
yetkiler (uyandırma, STT düzeltmeleri, sesli istek girişi) doğru bağımsız sahibe bağlıdır, (4)
Live'le birlikte çağrısı kesilen ama sahibi başka dalda kalan yüzeyler caller-zero olarak açıkça
kayıtta durur; sessizce "tamamlandı" sayılmaz.

Testler üretim fonksiyonlarını ve gerçek kaynak dosyalarını okur; mock'un kendi davranışını sınemez.
"""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RETIRED_FILES = (
    'modules/live.py', 'modules/live_audio.py', 'modules/live_microphone.py',
    'modules/live_session.py', 'modules/live_session_config.py', 'modules/live_tool_runner.py',
    'modules/live_tools.py', 'modules/live_transcripts.py', 'modules/voice_timing.py',
    'modules/speech_activity.py', 'modules/audio_diagnostics.py',
)
RETIRED_TESTS = (
    'tests/test_live_components.py', 'tests/test_live_error_messages.py',
    'tests/test_live_microphone.py', 'tests/test_live_session_components.py',
    'tests/test_live_stability.py', 'tests/test_live_audio_split.py',
    'tests/test_live_transcripts.py', 'tests/test_voice_timing.py',
)
# Yaşayan tek "live" ada sahip üretim dosyası: sesli isteğin Brain girişi.
KEPT_LIVE_FILE = 'modules/engine_live_brain.py'

RETIRED_IMPORTS = ('modules.live', 'modules.voice_timing', 'modules.speech_activity',
                   'modules.audio_diagnostics')

# Kullanıcı ayarı olarak okunup yazılan canlı konuşma anahtarları. Hiçbirinin tüketicisi kalmadı.
RETIRED_SETTING_KEYS = (
    'live_mode', 'live_voice', 'live_headphones', 'live_beep', 'live_silence_ms',
    'live_idle_seconds', 'live_model', 'live_stt_hint', 'live_stt_language',
    'live_audio_diagnostics', 'live_mic_gain', 'live_native_rate', 'live_lowcut',
    'live_compression', 'live_save_audio', 'live_send_wake', 'live_nospeech_seconds',
)


def _production_files():
    return sorted(list(ROOT.glob('*.py')) + list((ROOT / 'modules').glob('*.py')))


def _imported_modules(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.level == 0:
                names.add(node.module)
                names.update(f'{node.module}.{alias.name}' for alias in node.names)
    return names


class LiveStackIsGoneTests(unittest.TestCase):
    def test_the_live_files_are_physically_removed(self):
        for relative in RETIRED_FILES:
            with self.subTest(path=relative):
                self.assertFalse((ROOT / relative).exists())

    def test_only_the_brain_voice_entry_keeps_a_live_name(self):
        survivors = sorted(p.name for p in (ROOT / 'modules').glob('*.py')
                           if re.match(r'^live(_|$)', p.stem) or p.stem == 'voice_timing')
        self.assertEqual(survivors, [])
        self.assertTrue((ROOT / KEPT_LIVE_FILE).is_file())

    def test_no_production_module_imports_the_live_stack(self):
        for path in _production_files():
            names = _imported_modules(ast.parse(path.read_text(encoding='utf-8')))
            hits = sorted(n for n in names
                          if any(n == prefix or n.startswith(prefix + '.') for prefix in RETIRED_IMPORTS))
            with self.subTest(module=path.name):
                self.assertEqual(hits, [])


class InertSettingsGoneTests(unittest.TestCase):
    def test_no_retired_live_setting_key_survives_in_production(self):
        sources = [(path.name, path) for path in _production_files()]
        sources += [(relative, ROOT / relative) for relative in ('webui/nx.js', 'webui/nx.css')]
        for label, path in sources:
            text = path.read_text(encoding='utf-8')
            hits = sorted({key for key in RETIRED_SETTING_KEYS if re.search(r'\b' + key + r'\b', text)})
            with self.subTest(module=label):
                self.assertEqual(hits, [])

    def test_the_retired_live_tests_are_not_in_the_suite(self):
        for relative in RETIRED_TESTS:
            with self.subTest(path=relative):
                self.assertFalse((ROOT / relative).exists())

    def test_the_selfctl_promise_cannot_reappear(self):
        # selfctl eskiden "cevap hızı / açık kalma süresi" ayarlıyormuş gibi söylüyor, yazdigi
        # anahtarın hiçbir tüketicisi yoktu. Yetki envanteri de o anahtarları taşımaz.
        selfctl = (ROOT / 'modules' / 'selfctl.py').read_text(encoding='utf-8')
        core_map = (ROOT / 'modules' / 'brain_core_map.py').read_text(encoding='utf-8')
        model_doc = (ROOT / 'modules' / 'brain_model_understanding.py').read_text(encoding='utf-8')
        for text, name in ((selfctl, 'selfctl'), (core_map, 'brain_core_map'), (model_doc, 'brain_model_understanding')):
            with self.subTest(owner=name):
                for word in ('response_speed', 'idle_seconds', 'live_mode', 'Canlı konuşmayı'):
                    self.assertNotIn(word, text)

    def test_the_meter_cannot_offer_a_call_it_never_measured(self):
        # 'gemini-live' etiketi kota sayacına hiç üreticisi olmadan girmişti (tek dokunuş:
        # 71846bd). Live hattı emekli olurken ölü sözlük girdisi de kalktı; eski bir kayıt
        # kalırsa rapor çıplak adı gösterir (_LABEL.get), çökmez.
        meter = (ROOT / 'modules' / 'usage_meter.py').read_text(encoding='utf-8')
        self.assertNotIn('gemini-live', meter)
        self.assertNotIn('Gemini Live', meter)


class LivingAuthorityKeptTests(unittest.TestCase):
    def test_living_stt_fix_helpers_have_an_independent_owner(self):
        from modules import stt_fixes
        fixes = (ROOT / 'modules' / 'stt_fixes.py').read_text(encoding='utf-8')
        self.assertNotIn('import live', fixes)
        pairs = stt_fixes.parse_fixes('ışık=ışık kapat')
        self.assertEqual(pairs, [('ışık', 'ışık kapat')])
        self.assertEqual(stt_fixes.format_fixes(pairs), 'ışık=ışık kapat')
        # Varsayılan liste okunur ve arayüz onu ilk açılışta gösterir.
        self.assertIn('Hey Jarvis', stt_fixes.DEFAULT_FIXES)
        bridge = (ROOT / 'web.py').read_text(encoding='utf-8')
        self.assertIn('stt_fixes.DEFAULT_FIXES', bridge)
        learner = (ROOT / 'modules' / 'learning.py').read_text(encoding='utf-8')
        self.assertIn('stt_fixes.parse_fixes', learner)

    def test_the_voice_request_entry_still_goes_through_the_canonical_brain_gate(self):
        from modules import brain_entry, engine_live_brain
        source = Path(engine_live_brain.__file__).read_text(encoding='utf-8')
        self.assertIn('brain_entry.prepare', source)
        self.assertIn('brain_entry.handoff', source)
        self.assertTrue(callable(brain_entry.prepare) and callable(engine_live_brain._live_command))

    def test_wakeword_local_stt_and_single_voice_owner_are_untouched(self):
        for relative in ('modules/wakeword.py', 'modules/local_stt.py', 'modules/stt_guard.py',
                         'modules/voice_core.py', 'modules/voice_runtime.py', 'modules/voice_edge.py',
                         'modules/voice_offline.py', 'modules/stt_fixes.py'):
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_file())


class CallerZeroResidueTests(unittest.TestCase):
    """Emeklilikle üretim çağrısı kesilen, sahibi bu dalda olmayan yüzeyler.

    Kod duruyor ama kimse çağırmıyor: bu "temizlendi" demek değildir. Kayıt bu testte ve
    docs/agents/ses-video.md + docs/architecture/JARVIS_VOICE_COMM_V3_DEVIR.md içinde; sahibi
    Brain ve learning. Test, yüzey sessizce "yaşıyor" gibi kalmasın diye caller-zero
    durumunu açıkça kanıtlar.
    """

    def _call_sites(self, pattern: str):
        return [f'{path.name}:{line.strip()}'
                for path in _production_files()
                for line in path.read_text(encoding='utf-8').splitlines()
                if re.search(pattern, line)]

    def test_the_brain_voice_entry_has_no_production_caller(self):
        # engine_live_brain._live_command BRAIN-MIG-079'da KEEP_EXECUTION: bu dal silmez,
        # ama Live araç yürütücüsü gidince üretim çağrısı da kalmadı.
        self.assertEqual(self._call_sites(r'(?:runtime|self|engine_live_brain)\._live_command\s*\('), [])

    def test_the_pending_fact_reminder_has_no_production_trigger(self):
        # Onay bekleyen bilgileri soran not yalnız canlı oturum talimatına eklenirdi.
        self.assertEqual(self._call_sites(r'learning\.pending_prompt\s*\('), [])

    def test_the_raw_microphone_save_opt_in_cannot_come_back(self):
        # Ham mikrofon sesi varsayılan ve istemle diske yazılmaz: kayıt yardımcısı da anahtarı da yok.
        text = '\n'.join(path.read_text(encoding='utf-8') for path in _production_files())
        self.assertNotIn('son_ses', text)
        self.assertNotIn('_save_sent', text)


if __name__ == '__main__':
    unittest.main()
