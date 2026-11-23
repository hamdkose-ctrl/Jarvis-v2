"""Windows (yerel) ses motoru: SAPI hattı ve motor seçimi.

Kilitlenen davranış:
* Varsayılan motor **Edge**; ayar yoksa hiçbir şey değişmez.
* `voice_engine=windows` + kurulu Windows sesi varsa hat SAPI kataloğuna geçer.
* `voice_engine=windows` ama kurulu ses yoksa **Edge'de kalır** ve neden kaldığı
  loglanır (sessizce başka ses uydurulmaz).
* Geçersiz ayar değeri Edge sayılır (fail closed, uydurma motor yok).
* SAPI sentezi WAV döndürür; boş/kısa çıktı hata sayılır.
"""
import io
import sys
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from modules import voice_runtime, voice_sapi
from modules.voice_core import VoiceSpec


class Description(unittest.TestCase):
    def test_turkish_description(self):
        name, lang = voice_sapi._split_description("Microsoft Tolga - Turkish (Turkey)")
        self.assertEqual(name, "Tolga")
        self.assertEqual(lang, "Türkçe")

    def test_english_description(self):
        name, lang = voice_sapi._split_description("Microsoft Zira Desktop - English (United States)")
        self.assertEqual(name, "Zira Desktop")
        self.assertEqual(lang, "İngilizce")

    def test_unknown_shape_kept_readable(self):
        name, lang = voice_sapi._split_description("Özel Ses")
        self.assertEqual(name, "Özel Ses")
        self.assertEqual(lang, "")

    def test_keys_are_prefixed_and_stable(self):
        self.assertTrue(voice_sapi._key("Zira Desktop", 0).startswith("win_"))
        self.assertEqual(voice_sapi._key("Zira Desktop", 0), voice_sapi._key("Zira Desktop", 5))


class EngineChoice(unittest.TestCase):
    def test_default_is_edge(self):
        with patch.object(voice_runtime, "_record_failure"):
            with patch("config.load_settings", return_value={}):
                self.assertEqual(voice_runtime.voice_engine(), "edge")

    def test_invalid_value_falls_back_to_edge(self):
        with patch.object(voice_runtime, "_record_failure"):
            with patch("config.load_settings", return_value={"voice_engine": "bulut"}):
                self.assertEqual(voice_runtime.voice_engine(), "edge")

    def test_windows_selected(self):
        with patch.object(voice_runtime, "_record_failure"):
            with patch("config.load_settings", return_value={"voice_engine": "windows"}):
                self.assertEqual(voice_runtime.voice_engine(), "windows")

    def test_read_error_keeps_edge(self):
        with patch.object(voice_runtime, "_record_failure"):
            with patch("config.load_settings", side_effect=OSError("okunamadı")):
                self.assertEqual(voice_runtime.voice_engine(), "edge")


class Catalog(unittest.TestCase):
    def test_no_voices_means_no_catalog(self):
        with patch.object(voice_sapi, "installed_voices", return_value=[]):
            self.assertIsNone(voice_runtime._sapi_catalog(object()))

    def test_catalog_carries_sapi_backend(self):
        rows = [("win_zira", "Windows · Zira (İngilizce)", "Microsoft Zira - English"),
                ("win_tolga", "Windows · Tolga (Türkçe)", "Microsoft Tolga - Turkish")]
        with patch.object(voice_sapi, "installed_voices", return_value=rows):
            catalog = voice_runtime._sapi_catalog(object())
        specs = catalog.choices()
        self.assertEqual(len(specs), 2)
        self.assertTrue(all(spec.backend == "sapi" for spec in specs))
        self.assertEqual(specs[1].asset_id, "Microsoft Tolga - Turkish")

    def test_catalog_is_capped(self):
        rows = [(f"win_{i}", f"Ses {i}", f"Voice {i}") for i in range(20)]
        with patch.object(voice_sapi, "installed_voices", return_value=rows):
            catalog = voice_runtime._sapi_catalog(object())
        self.assertLessEqual(len(catalog.choices()), 6)


class Synthesis(unittest.TestCase):
    def _spec(self):
        return VoiceSpec("win_test", "Windows · Test", "sapi", "Microsoft Test - Turkish")

    def test_wrong_backend_refused(self):
        synth = voice_sapi.SapiSynthesizer()
        with self.assertRaises(Exception):
            synth(VoiceSpec("tr_kadin", "Kadın", "edge", "tr-TR-EmelNeural"), "merhaba", threading.Event())

    def test_missing_comtypes_refused(self):
        synth = voice_sapi.SapiSynthesizer()
        with patch.object(voice_sapi, "_comtypes", return_value=None):
            with self.assertRaises(Exception):
                synth(self._spec(), "merhaba", threading.Event())

    def test_cancel_returns_empty_without_work(self):
        synth = voice_sapi.SapiSynthesizer()
        cancel = threading.Event()
        cancel.set()
        self.assertEqual(synth(self._spec(), "merhaba", cancel), b"")

    def test_empty_text_returns_empty(self):
        self.assertEqual(voice_sapi.SapiSynthesizer()(self._spec(), "   ", threading.Event()), b"")

    def test_wav_bytes_returned(self):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16000)
            handle.writeframes(b"\x01\x00" * 1600)
        payload = buf.getvalue()
        synth = voice_sapi.SapiSynthesizer()
        with patch.object(voice_sapi, "_comtypes", return_value=True), \
             patch.object(voice_sapi, "_speak_to_file", side_effect=lambda name, text, path: Path(path).write_bytes(payload)):
            out = synth(self._spec(), "merhaba", threading.Event())
        self.assertTrue(out.startswith(b"RIFF"))
        self.assertEqual(out, payload)

    def test_non_wav_output_is_rejected(self):
        synth = voice_sapi.SapiSynthesizer()
        with patch.object(voice_sapi, "_comtypes", return_value=True), \
             patch.object(voice_sapi, "_speak_to_file", side_effect=lambda name, text, path: Path(path).write_bytes(b"x" * 100)):
            with self.assertRaises(Exception):
                synth(self._spec(), "merhaba", threading.Event())

    def test_empty_file_is_rejected(self):
        synth = voice_sapi.SapiSynthesizer()
        with patch.object(voice_sapi, "_comtypes", return_value=True), \
             patch.object(voice_sapi, "_speak_to_file", side_effect=lambda name, text, path: Path(path).write_bytes(b"RIFF")):
            with self.assertRaises(Exception):
                synth(self._spec(), "merhaba", threading.Event())


class Platform(unittest.TestCase):
    def test_non_windows_has_no_voices(self):
        with patch.object(voice_sapi.sys, "platform", "linux"):
            self.assertEqual(voice_sapi.installed_voices(), [])

    def test_preload_counts_installed(self):
        rows = [("win_a", "Windows · A", "A")]
        with patch.object(voice_sapi, "installed_voices", return_value=rows):
            self.assertEqual(voice_sapi.SapiSynthesizer().preload_all(), 1)


if __name__ == "__main__":
    unittest.main()
