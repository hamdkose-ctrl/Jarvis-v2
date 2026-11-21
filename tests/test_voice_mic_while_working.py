"""Ses önde: Jarvis arkada çalışırken mikrofon kapanmaz (21 Kasım isteği)."""
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules import engine_loop


class _Runtime:
    class _Rec:
        def __init__(self):
            self.calls = []

        def __call__(self, where, *a, **k):
            self.calls.append(where)

    def __init__(self):
        self.recorded = self._Rec()

    def _record_failure(self, where, *a, **k):
        self.recorded(where)


class MicWhileWorkingTests(unittest.TestCase):
    def _with_settings(self, settings):
        fake = types.ModuleType("config")
        fake.load_settings = lambda: settings
        previous = sys.modules.get("config")
        sys.modules["config"] = fake
        self.addCleanup(lambda: sys.modules.__setitem__("config", previous)
                        if previous is not None else sys.modules.pop("config", None))

    def test_microphone_stays_open_while_the_turn_works_by_default(self):
        self._with_settings({})
        self.assertTrue(engine_loop._mic_stays_listening(_Runtime()))

    def test_settings_can_restore_the_old_silent_turn(self):
        self._with_settings({"voice_mic_while_working": False})
        self.assertFalse(engine_loop._mic_stays_listening(_Runtime()))

    def test_unreadable_settings_keep_the_microphone_open(self):
        class Boom(types.ModuleType):
            def load_settings(self):
                raise RuntimeError("ayar dosyası okunamadı")

        sys.modules["config"] = Boom("config")
        self.addCleanup(lambda: sys.modules.pop("config", None))
        runtime = _Runtime()
        self.assertTrue(engine_loop._mic_stays_listening(runtime))
        self.assertIn("modules/engine_loop.py:mic_setting", runtime.recorded.calls)


if __name__ == "__main__":
    unittest.main()
