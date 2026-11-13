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
        assert 'abort=mic_cancel' in MAIN
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


if __name__ == "__main__":
    unittest.main()
