import engine_source
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = (ROOT / "web.py").read_text(encoding="utf-8") + (ROOT / "modules/web_window.py").read_text(encoding="utf-8").replace("runtime.", "")
MAIN = engine_source.source()


class MicHardOffTests(unittest.TestCase):
    # Jarvis'in "GitHub'a Yükle" testi unittest ile çalışır; düz pytest fonksiyonları orada hiç çalışmıyordu
    def test_mic_master_switch_cancels_active_listens(self):
        assert 'mic_cancel = threading.Event()' in MAIN
        assert 'engine.mic_cancel.set()' in WEB
        assert 'engine.mic_cancel.clear()' in WEB
        # mic_cancel artık _AnyAbort listelerinde de taşınır: konuşma kabulü (busy)
        # bekleyen yakalamayı kesmelidir, ama anahtar kapanışı yine en öncelikli iptal
        # sinyali olarak mic_cancel ile birlikte geçer.
        assert '_AnyAbort(' in MAIN
        assert MAIN.count('mic_cancel') >= 5  # Event tanımı + 3 yakalama abort listesi + tanım kullanımları
        assert 'if kind == "listen" and not flags.get("mic", True)' in MAIN
        assert 'if not engine.flags.get("mic", True)' in WEB or "if not engine.flags.get('mic', True)" in WEB


    def test_wakeword_releases_physical_input_stream_when_mic_is_turned_off(self):
        # Yaşayan dinleyici: mikrofon anahtarı kapanınca fiziksel giriş akışı gerçekten bırakılır.
        # Eski Gemini Live okuyucusu emekli olduktan sonra bu garanti tek başına wakeword.wait'tadır.
        import sounddevice as sd
        import numpy as np
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from modules import voice, wakeword

        model = SimpleNamespace(predict=lambda _x: {}, reset=lambda: None)
        closed = []

        class Stream:
            def __enter__(s):
                return s
            def __exit__(s, *args):
                closed.append(True)
            def read(s, count):
                return np.zeros((count, 1), dtype=np.int16), False

        previous = wakeword._model
        wakeword._model = model
        self.addCleanup(setattr, wakeword, '_model', previous)
        should_stop = Mock(side_effect=[False, True])
        with patch.object(sd, 'InputStream', return_value=Stream()), \
             patch.object(voice, '_input_device', return_value=None), \
             patch.object(wakeword, 'sensitivity_threshold', return_value=0.5):
            self.assertIsNone(wakeword.wait(should_stop))
        self.assertEqual(closed, [True], 'akış kapanmadan döndü')
        self.assertTrue(should_stop.called)


    def test_emergency_uses_same_master_mic_switch(self):
        assert '_set_mic(False)' in WEB

    def wakeword_modules(self, model):
        """openwakeword replaced in sys.modules so the loader runs without an install."""
        from types import ModuleType
        package = ModuleType('openwakeword')
        package.FEATURE_MODELS = {}
        package.MODELS = {'hey_jarvis': {'download_url': 'https://example.invalid/m.onnx',
                                         'model_path': 'm.tflite'}}
        utils = ModuleType('openwakeword.utils')
        model_module = ModuleType('openwakeword.model')
        model_module.Model = model
        return {'openwakeword': package, 'openwakeword.utils': utils,
                'openwakeword.model': model_module}

    def load_state(self, model, prepare_error):
        from unittest.mock import patch
        from modules import wakeword
        previous = (wakeword._state, wakeword._error, wakeword._model)
        prepare = (patch('modules.wakeword_models.ensure_models', side_effect=prepare_error)
                   if prepare_error else patch('modules.wakeword_models.ensure_models'))
        try:
            with patch.dict('sys.modules', self.wakeword_modules(model)), prepare:
                wakeword._load()
            return wakeword.status()
        finally:
            wakeword._state, wakeword._error, wakeword._model = previous

    def test_model_prepare_failure_reason_is_not_masked(self):
        # §P2: "kurulum.bat'ı çalıştır" and "ağ yok" looked identical because the
        # download/verification error was swallowed before the model load. The
        # first cause now travels into the reported failure, still without any
        # key, token or user text.
        class Broken:
            def __init__(self, *args, **kwargs):
                raise RuntimeError('Model dosyası bulunamadı')

        status = self.load_state(Broken, OSError(13, 'Erişim engellendi: model klasörü'))
        self.assertEqual(status['state'], 'failed')
        self.assertIn('Model hazırlanamadı', status['error'])
        self.assertIn('Erişim engellendi', status['error'])
        self.assertIn('Model dosyası bulunamadı', status['error'])

    def test_already_downloaded_models_still_load_after_a_failed_download(self):
        # Offline machine: ensure_models cannot reach the network, the files are
        # already there and the loader must succeed and stay quiet.
        class Ready:
            def __init__(self, *args, **kwargs):
                pass

        status = self.load_state(Ready, OSError('internet yok'))
        self.assertEqual(status['state'], 'ready')
        self.assertEqual(status['error'], '')


if __name__ == "__main__":
    unittest.main()
