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


    def test_live_releases_physical_input_stream_when_muted(self):
        # Exercise the extracted reader rather than searching for an old comment.
        import sys
        import numpy as np
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        import test_engine_modular
        from modules import live, voice
        with patch.object(live, '_Player', return_value=Mock()), patch.object(live.threading, 'Thread'):
            obj = live.Live(Mock(), Mock(), Mock())
        self.addCleanup(obj.loop.close)
        obj.mic_on = Mock(side_effect=[True, False])
        closed = []
        class Stream:
            def __enter__(self): return self
            def read(self, count): return np.zeros((count, 1), dtype=np.int16), False
            def __exit__(self, *args):
                closed.append(True)
                obj.stop_event.set()
        sounddevice = SimpleNamespace(query_devices=lambda *args: {'name':'fake', 'default_samplerate':16000}, InputStream=Mock(return_value=Stream()))
        with patch.dict(sys.modules, {'sounddevice':sounddevice}), patch.object(voice, '_input_device', return_value=None), patch.object(live, 'enabled', return_value=True):
            obj._mic_loop()
        self.assertEqual(closed, [True])
        sounddevice.InputStream.assert_called_once()
        self.assertEqual(len(obj._outbox), 0)


    def test_emergency_uses_same_master_mic_switch(self):
        assert '_set_mic(False)' in WEB


if __name__ == "__main__":
    unittest.main()
