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

    def test_live_mode_off_in_private_modes(self):
        src = (ROOT / "modules" / "live.py").read_text(encoding="utf-8")
        body = src[src.index("def enabled()"):src.index("def parse_fixes")]
        self.assertIn('return False', body)   # ses özel: Live her modda kapalı (Provider Routing Policy v1)
        try:
            from modules import live
        except Exception as exc:   # noqa: BLE001 - Gemini kütüphanesi bu ortamda yoksa yalnızca kaynak denetimi
            self.skipTest(f"live içe aktarılamadı: {exc}")
        with patch("modules.privacy.mode", return_value="yerel"):
            self.assertFalse(live.enabled())
        with patch("modules.privacy.mode", return_value="gizli"):
            self.assertFalse(live.enabled())
        with patch("modules.privacy.mode", return_value="normal"):
            self.assertFalse(live.enabled())





class StudyFallbackTests(unittest.TestCase):
    def test_book_questions_have_one_study_owner(self):
        # PR10c: "o kitaptan örnek ver" gibi adı verilmemiş cümlede kaynağı keyword kümesiyle
        # seçen düşürme kaldırıldı. Kitap/çıkmış soru kaynağını artık yalnız Çalışma domain'i seçer:
        # sesli/yazılı yol _study_intent -> hoca.handle, panel yolu web_study_sources -> study.ask.
        src = engine_source.source()
        self.assertNotIn("_study_answer", src)
        self.assertIn("_study_intent", src)
        self.assertIn("hoca", src)
        panel = (Path(__file__).resolve().parents[1] / "web_study_sources.py").read_text(encoding="utf-8")
        self.assertIn("study.ask", panel)


if __name__ == "__main__":
    unittest.main()
