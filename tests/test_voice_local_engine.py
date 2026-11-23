"""Windows (yerel) ses motoru: SAPI hattı ve motor seçimi.

Kilitlenen davranış:
* Varsayılan motor **Edge**; ayar yoksa hiçbir şey değişmez.
* `voice_engine=windows` + kurulu Windows sesi varsa hat SAPI kataloğuna geçer.
* `voice_engine=windows` ama kurulu ses yoksa **Edge'de kalır** ve neden kaldığı
  loglanır (sessizce başka ses uydurulmaz).
* Geçersiz ayar değeri Edge sayılır (fail closed, uydurma motor yok).
* SAPI sentezi WAV döndürür; boş/kısa çıktı hata sayılır.
"""
import importlib.util
import io
import sys
import tempfile
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


class PiperCatalog(unittest.TestCase):
    def test_label_reads_speaker_and_language(self):
        self.assertEqual(voice_runtime._piper_label(Path("tr_TR-fahrettin-medium.onnx")),
                         "Yerel · Fahrettin (Türkçe)")
        self.assertEqual(voice_runtime._piper_label(Path("en_US-amy-low.onnx")),
                         "Yerel · Amy (İngilizce)")

    def test_unknown_shape_still_labelled(self):
        self.assertTrue(voice_runtime._piper_label(Path("ozel.onnx")).startswith("Yerel · "))

    def test_catalog_from_models_dir(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "voice_models"
            root.mkdir()
            (root / "tr_TR-fahrettin-medium.onnx").write_bytes(b"x")
            (root / "en_US-amy-low.onnx").write_bytes(b"x")

            class Runtime:
                DATA_DIR = Path(folder)
            catalog = voice_runtime._piper_catalog(Runtime())
        specs = catalog.choices()
        self.assertEqual(len(specs), 2)
        self.assertTrue(all(spec.backend == "piper" for spec in specs))
        self.assertEqual(specs[0].asset_id, "en_US-amy-low.onnx")

    def test_missing_dir_means_no_catalog(self):
        with tempfile.TemporaryDirectory() as folder:
            class Runtime:
                DATA_DIR = Path(folder)
            self.assertIsNone(voice_runtime._piper_catalog(Runtime()))

    def test_piper_engine_value_accepted(self):
        with patch.object(voice_runtime, "_record_failure"):
            with patch("config.load_settings", return_value={"voice_engine": "piper"}):
                self.assertEqual(voice_runtime.voice_engine(), "piper")


class PiperEngineProbe(unittest.TestCase):
    def test_cli_counts_as_available(self):
        with patch('shutil.which', return_value='/usr/bin/piper'):
            self.assertTrue(voice_runtime._piper_engine_available())

    @unittest.skipUnless(importlib.util.find_spec('piper'), 'piper paketi bu ortamda kurulu değil')
    def test_library_counts_as_available(self):
        """CLI olmasa da süreç içi paket varsa motor kullanılabilir (canlı kusur).

        CI'da piper kurulu olmayabilir; o ortamda test atlanır, sahte bir "var"
        sonucu üretilmez.
        """
        with patch('shutil.which', return_value=None):
            self.assertTrue(voice_runtime._piper_engine_available())

    def test_missing_everything_is_unavailable(self):
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *a, **kw):
            if name == 'piper' or name.startswith('piper.'):
                raise ImportError('yok')
            return real_import(name, *a, **kw)
        with patch('shutil.which', return_value=None), patch.object(builtins, '__import__', side_effect=fake_import):
            self.assertFalse(voice_runtime._piper_engine_available())


class Reconcile(unittest.TestCase):
    class _Owner:
        def __init__(self, voice):
            self.data = {"prefs": {"voice": voice}}

    class _Catalog:
        def __init__(self, keys):
            self._keys = keys
        def require(self, key):
            if key not in self._keys:
                raise ValueError("yok")
            return key
        def choices(self):
            return [VoiceSpec(k, k, "piper", k + ".onnx") for k in self._keys]

    class _Lane:
        def __init__(self, keys):
            self.catalog = Reconcile._Catalog(keys)

    def test_missing_voice_is_replaced_with_first_installed(self):
        owner = self._Owner("tr_kadin")
        lane = self._Lane(["piper_tr", "piper_en"])

        class Runtime:
            DATA_DIR = Path(".")
            def pc_profile(self):
                return owner
        with patch("modules.engine_context.set_profile_voice", return_value=(True, "x")) as setter:
            voice_runtime._reconcile_voice(Runtime(), lane)
        setter.assert_called_once()
        self.assertEqual(setter.call_args.args[1], "piper_tr")

    def test_installed_voice_is_kept(self):
        owner = self._Owner("piper_tr")
        lane = self._Lane(["piper_tr"])
        class Runtime:
            def pc_profile(self):
                return owner
        with patch("modules.engine_context.set_profile_voice") as setter:
            voice_runtime._reconcile_voice(Runtime(), lane)
        setter.assert_not_called()

    def test_empty_catalog_changes_nothing(self):
        owner = self._Owner("tr_kadin")
        lane = self._Lane([])
        class Runtime:
            def pc_profile(self):
                return owner
        with patch("modules.engine_context.set_profile_voice") as setter:
            voice_runtime._reconcile_voice(Runtime(), lane)
        setter.assert_not_called()

    def test_error_is_recorded_not_raised(self):
        class Runtime:
            def pc_profile(self):
                raise RuntimeError("profil yok")
        with patch.object(voice_runtime, "_record_failure") as record:
            voice_runtime._reconcile_voice(Runtime(), self._Lane(["a"]))
        record.assert_called()


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
