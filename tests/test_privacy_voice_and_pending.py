import engine_source
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Windows'taki ses kütüphaneleri test ortamında yoksa sahte modülle yer tut (testler yalnızca karar mantığını sınar)
for _name in ("edge_tts", "pyttsx3", "sounddevice", "speech_recognition"):
    try:
        importlib.import_module(_name)
    except Exception:   # noqa: BLE001
        _m = types.ModuleType(_name)
        if _name == "speech_recognition":
            _m.Recognizer = MagicMock
            _m.AudioData = MagicMock
            _m.UnknownValueError = type("UnknownValueError", (Exception,), {})
            _m.RequestError = type("RequestError", (Exception,), {})
        else:
            _m.__getattr__ = lambda attr: MagicMock()
        sys.modules[_name] = _m

ROOT = Path(__file__).resolve().parents[1]


class PrivacyVoiceTests(unittest.TestCase):
    def test_private_modes_never_send_audio_out(self):
        # Gizli / yalnızca-yerel modda ses Google'a da Gemini'ye de gitmemeli
        from modules import voice
        for mode in ("gizli", "yerel"):
            with patch.object(voice.privacy, "mode", return_value=mode):
                self.assertEqual(voice._engine(), "off")
                self.assertEqual(voice._google_text(object()), "")
                with patch.object(voice._rec, "recognize_google", side_effect=AssertionError("Google'a gitti")), \
                     patch.object(voice, "_off_notice"):
                    self.assertIsNone(voice.recognize(b"\x00\x00" * 1600))

    def test_normal_mode_keeps_cloud_engine(self):
        from modules import voice
        with patch.object(voice.privacy, "mode", return_value="normal"):
            self.assertIn(voice._engine(), ("gemini", "google"))

    def test_no_continuous_microphone_stream_can_exist(self):
        # "Ses özel" hükmü eskiden live.enabled()'in her modda False dönmesiyle korunuyordu.
        # Canlı akış hattı emekli olduktan sonra hükmün taşıyıcısı kalmamıştır: üretimde
        # sürekli mikrofon akışı üreten kod bulunamaz (tests/test_live_retirement.py).
        for name in list(sys.modules):
            if name.startswith('modules.live') or name in ('modules.voice_timing',
                                                           'modules.speech_activity',
                                                           'modules.audio_diagnostics'):
                self.fail(f'emekli olan canlı ses hattı hâlâ içe aktarılmış: {name}')
        for path in sorted((ROOT / 'modules').glob('*.py')):
            with self.subTest(module=path.name):
                self.assertNotIn('input_audio_buffer', path.read_text(encoding='utf-8'))





class StudyFallbackTests(unittest.TestCase):
    def test_book_questions_have_one_study_owner(self):
        # PR10c: "o kitaptan örnek ver" gibi adı verilmemiş cümlede kaynağı keyword kümesiyle
        # seçen düşürme kaldırıldı. Kitap/çıkmış soru kaynağını artık yalnız Çalışma domain'i seçer:
        # Text/voice now resolve through the Brain's typed Core study.read
        # or hoca.lesson.start proposal, never the deleted _study_intent parser.
        src = engine_source.source()
        self.assertNotIn("_study_answer", src)
        self.assertNotIn("_study_intent", src)
        from modules import brain_core_map
        self.assertEqual(brain_core_map.core_plan("study.read", {"view": "plan"}),
                         ("study_read", {"view": "plan"}))
        self.assertEqual(brain_core_map.core_plan("hoca.lesson.start",
                                                   {"topic": "hücre"}),
                         ("hoca_start", {"topic": "hücre"}))
        panel = (Path(__file__).resolve().parents[1] / "web_study_sources.py").read_text(encoding="utf-8")
        self.assertIn("study.ask", panel)


if __name__ == "__main__":
    unittest.main()
