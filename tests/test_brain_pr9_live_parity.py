"""PR9 RED: Live commands must use the same canonical Brain entry as text/web/phone."""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import test_engine_modular as fixtures


class BrainPR9LiveParityTests(unittest.TestCase):
    def context(self):
        return fixtures.ModularEngineTests.context(self)

    def test_live_command_enters_brain_before_core_handoff(self):
        from modules import brain_entry

        runtime = self.context()
        runtime.emit = Mock()
        runtime.handle = Mock(side_effect=AssertionError("Live ham metni Brain'i atlayarak handle edemez"))
        sentinel_entry = object()
        sentinel_feedback = object()

        with patch.object(brain_entry, "prepare", return_value=sentinel_entry) as prepare, \
             patch.object(brain_entry, "handoff", return_value=("Tamam.", sentinel_feedback, None)) as handoff:
            result = runtime._live_command("hava nasıl")

        self.assertEqual(result, "Tamam.")
        prepare.assert_called_once()
        kwargs = prepare.call_args.kwargs
        self.assertEqual(kwargs["owner"], runtime.profile.slug)
        self.assertEqual(kwargs["text"], "hava nasıl")
        self.assertEqual(kwargs["source"], "ses")
        self.assertTrue(kwargs["request_id"])
        handoff.assert_called_once_with(runtime, sentinel_entry, runtime.handle, "hava nasıl")
        runtime.handle.assert_not_called()

    def test_live_command_handoff_exception_uses_existing_diagnose_fallback(self):
        from modules import brain_entry, diagnose

        runtime = self.context()
        runtime.emit = Mock()
        runtime.handle = Mock()
        sentinel_entry = object()

        with patch.object(brain_entry, "prepare", return_value=sentinel_entry), \
             patch.object(brain_entry, "handoff", side_effect=RuntimeError("boom")), \
             patch.object(diagnose, "explain", return_value="Tanı mesajı") as explain:
            result = runtime._live_command("hava nasıl")

        self.assertEqual(result, "Tanı mesajı")
        explain.assert_called_once()


if __name__ == "__main__":
    unittest.main()
