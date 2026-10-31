from __future__ import annotations

import inspect
import unittest

from modules import engine_loop
from modules.brain_contracts import ActiveContext
from modules.brain_gates import deterministic_fast_gate

OWNER = "hamdi"
RID = "req-close-help-parity"


class EngineCloseHelpParityTests(unittest.TestCase):
    def _fast(self, text: str, source: str):
        return deterministic_fast_gate(
            owner=OWNER,
            request_id=RID,
            text=text,
            active_context=ActiveContext(owner=OWNER, request_id=RID),
            sleeping=False,
            source=source,
        )

    def test_bare_typed_and_voice_close_stay_fast_miss(self):
        for text, source in (("kapat", "yazı"), ("Kapat.", "ses"), ("çık", "yazı")):
            with self.subTest(text=text, source=source):
                result = self._fast(text, source)
                self.assertFalse(result.matched)
                self.assertNotEqual(result.protocol, "fast.engine.close")

    def test_explicit_target_close_remains_exact_fast_hit(self):
        result = self._fast("Jarvis'i kapat", "yazı")
        self.assertTrue(result.matched)
        self.assertEqual(result.protocol, "fast.engine.close")
        self.assertEqual(result.selection, "close")

    def test_startup_exit_help_never_advertises_bare_kapat(self):
        source = inspect.getsource(engine_loop.main)
        exit_lines = [line for line in source.splitlines() if "Çıkış:" in line]
        self.assertEqual(len(exit_lines), 2)
        for line in exit_lines:
            self.assertNotIn("'kapat'", line)

    def test_startup_exit_help_advertises_supported_explicit_self_close(self):
        source = inspect.getsource(engine_loop.main)
        exit_lines = [line for line in source.splitlines() if "Çıkış:" in line]
        self.assertEqual(len(exit_lines), 2)
        for line in exit_lines:
            self.assertIn("Jarvis'i kapat", line)


if __name__ == "__main__":
    unittest.main()
