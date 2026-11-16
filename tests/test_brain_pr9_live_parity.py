"""PR9 RED: Live commands must use the same canonical Brain entry as text/web/phone."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_engine_modular as fixtures
from modules.brain_contracts import BrainFeedback


class BrainPR9LiveParityTests(unittest.TestCase):
    def context(self):
        return fixtures.ModularEngineTests.context(self)

    def test_live_command_enters_brain_before_core_handoff(self):
        from modules import brain_entry, brain_core_wire, core_brain_adapter

        runtime = self.context()
        runtime.emit = Mock()
        runtime.handle = Mock(side_effect=AssertionError("Live ham metni Brain'i atlayarak handle edemez"))
        sentinel_entry = SimpleNamespace(
            stage="understanding", text="hava nasıl",
            to_handoff_json=Mock(return_value='{"wire":"test-only"}'),
        )
        projection = {"output": "Tamam.", "feedback": {"result_status": "handled"}, "job_id": None}

        with patch.object(brain_entry, "prepare", return_value=sentinel_entry) as prepare, \
             patch.object(core_brain_adapter, "handoff_json", return_value='{"result":"test-only"}') as handoff, \
             patch.object(brain_core_wire, "decode_result", return_value=projection) as decode:
            result = runtime._live_command("hava nasıl")

        self.assertEqual(result, "Tamam.")
        prepare.assert_called_once()
        kwargs = prepare.call_args.kwargs
        self.assertEqual(kwargs["owner"], runtime.profile.slug)
        self.assertEqual(kwargs["text"], "hava nasıl")
        self.assertEqual(kwargs["source"], "ses")
        self.assertTrue(kwargs["request_id"])
        handoff.assert_called_once_with(runtime, sentinel_entry.to_handoff_json.return_value,
                                        runtime.handle, "hava nasıl")
        decode.assert_called_once()
        self.assertEqual(decode.call_args.kwargs, {"owner": runtime.profile.slug,
                                                  "request_id": kwargs["request_id"]})
        runtime.handle.assert_not_called()

    def test_live_command_handoff_exception_uses_existing_diagnose_fallback(self):
        from modules import brain_entry, core_brain_adapter, diagnose

        runtime = self.context()
        runtime.emit = Mock()
        runtime.handle = Mock()
        sentinel_entry = SimpleNamespace(stage="understanding",
                                         to_handoff_json=Mock(return_value='{"wire":"test-only"}'))

        with patch.object(brain_entry, "prepare", return_value=sentinel_entry), \
             patch.object(core_brain_adapter, "handoff_json", side_effect=RuntimeError("boom")), \
             patch.object(brain_entry, "last_feedback", return_value=None), \
             patch.object(diagnose, "explain", return_value="Tanı mesajı") as explain:
            result = runtime._live_command("hava nasıl")

        self.assertEqual(result, "Tanı mesajı")
        explain.assert_called_once()


if __name__ == "__main__":
    unittest.main()
