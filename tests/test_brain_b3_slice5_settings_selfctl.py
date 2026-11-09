"""BRAIN-03 slice 5: typed model proposal -> Core -> existing adapters."""
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import test_brain_closeout_a  # noqa: F401 - installs shared runtime stubs
from modules import brain_core_map, brain_entry, engine_runtime, requests_state
from modules.brain_contracts import Confidence, ConversationRelation, TemporalNeed
from modules.brain_model_understanding import ProposedAction, UnderstandingProposal


class Slice5CoreTests(unittest.TestCase):
    def test_windows_page_and_selfctl_payloads_are_closed(self):
        self.assertEqual(
            brain_core_map.core_plan("windows.settings.open", {"page": "network-wifi"}),
            ("windows_settings_open", {"page": "network-wifi"}),
        )
        self.assertIsNone(brain_core_map.core_plan("windows.settings.open", {"page": "shell:startup"}))
        self.assertEqual(
            brain_core_map.core_plan("jarvis.selfctl", {"action": {"kind": "navigate", "page": "notes"}}),
            ("selfctl", {"kind": "navigate", "page": "notes"}),
        )
        self.assertIsNone(brain_core_map.core_plan("jarvis.selfctl", {"action": {"kind": "navigate", "page": "raw sentence"}}))
        self.assertIsNone(brain_core_map.core_plan("jarvis.selfctl", {"action": {"kind": "setting", "key": "api_key", "value": "x"}}))


class Slice5ProductionSeamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        with patch.object(engine_runtime, "DATA_DIR", Path(self.temp.name)):
            self.ctx = engine_runtime.EngineContext()
        self.addCleanup(self.ctx._prefetch_pool.shutdown, wait=False, cancel_futures=True)
        self.owner = self.ctx.profile.slug
        self.ctx.emit = Mock()
        self.ctx.system_control = Mock()
        guard = patch.object(brain_entry, "_install_core_guards", lambda runtime: None)
        guard.start(); self.addCleanup(guard.stop)

    def _proposal(self, capability, arguments):
        return UnderstandingProposal(
            operation="direct_action", conversation_relation=ConversationRelation.NEW_REQUEST,
            temporal_need=TemporalNeed.UNSURE, confidence=Confidence.HIGH,
            actions=(ProposedAction("a1", capability, arguments, (), ()),),
        )

    def _through_prepare_handoff(self, text, proposal):
        rid = "b3s5-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with patch("modules.brain_model_understanding.propose", return_value=proposal) as model:
            with requests_state.activate(self.owner, rid):
                entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı", model_understanding=True)
                legacy = Mock(side_effect=AssertionError("raw legacy handler must not run"))
                out, feedback, _ = brain_entry.handoff(self.ctx, entry, legacy, text)
        model.assert_called_once()
        legacy.assert_not_called()
        return entry, out, feedback

    def test_windows_settings_reaches_adapter_from_typed_model_proposal(self):
        self.ctx.system_control.open_windows_settings.return_value = "Wi-Fi açıldı"
        entry, out, feedback = self._through_prepare_handoff(
            "wifi ayarlarını aç", self._proposal("windows.settings.open", {"page": "network-wifi"})
        )
        self.assertEqual(entry.understanding.capability_hint, "windows.settings.open")
        self.assertEqual(out, "Wi-Fi açıldı")
        self.assertEqual(feedback.result_status, "handled")
        self.ctx.system_control.open_windows_settings.assert_called_once_with("network-wifi")

    def test_selfctl_reaches_typed_adapter_without_original_sentence_reparse(self):
        entry, out, feedback = self._through_prepare_handoff(
            "notlarımı aç", self._proposal("jarvis.selfctl", {"action": {"kind": "navigate", "page": "notes"}})
        )
        self.assertEqual(entry.understanding.capability_hint, "jarvis.selfctl")
        self.assertIn("Notlar", out)
        self.assertEqual(feedback.result_status, "handled")
        self.assertIn(("nav", "tools|takvim"), [(call.args[0], call.args[1]) for call in self.ctx.emit.call_args_list])


class Slice5RetirementTests(unittest.TestCase):
    def test_no_raw_settings_or_selfctl_owner_remains_in_production_chain(self):
        root = Path(__file__).resolve().parents[1]
        sources = "\n".join((root / path).read_text(encoding="utf-8") for path in (
            "modules/engine_commands.py", "modules/brain_precedence.py", "modules/system_control.py", "modules/selfctl.py",
        ))
        self.assertNotIn("def windows_settings(", sources)
        self.assertNotIn("def handle(cmd_lower", sources)
        self.assertNotIn("selfctl.handle", sources)
        self.assertNotIn("system_control.windows_settings", sources)


if __name__ == "__main__":
    unittest.main()
