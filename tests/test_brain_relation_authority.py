"""PR1: turn relation authority yalnız Understanding'dedir; Core slot varlığından karar taklit etmez.

Açık bir clarification (stage=clarify) yeni bir capability isteğini bloke edemez; Core plan
çalışır, sohbet yedeğine düşmez. Gerçek clarification yanıtı multi-step'i erken sürdürmez.
"""
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_brain_closeout_a  # noqa: F401  (shared test stubs)
from modules import app_actions, brain_entry, brain_precedence, engine_runtime, requests_state
from modules.command_manager import awaiting_input


class RelationAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root_logger = engine_runtime.logging.getLogger()
        previous_handlers = set(root_logger.handlers)
        with patch.object(engine_runtime, "DATA_DIR", Path(self.temp.name)):
            self.ctx = engine_runtime.EngineContext()
        def close_test_handlers():
            for handler in list(root_logger.handlers):
                if handler not in previous_handlers:
                    root_logger.removeHandler(handler)
                    handler.close()
        self.addCleanup(close_test_handlers)
        self.addCleanup(self.ctx._prefetch_pool.shutdown, wait=False, cancel_futures=True)
        self.owner = self.ctx.profile.slug
        self.ctx.system_control = Mock(windows_settings=Mock(return_value=None))
        self.ctx.chat = Mock(return_value="CHAT")
        guard = patch.object(brain_entry, "_install_core_guards", lambda runtime: None)
        guard.start()
        self.addCleanup(guard.stop)

    def turn(self, text, handler=None):
        rid = "rel-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı")
            handle = handler or Mock(wraps=self.ctx.handle)
            out, feedback, _ = brain_entry.handoff(self.ctx, entry, handle, text)
        return entry, out, handle, feedback

    def ask(self, text="aç"):
        entry, out, handle, _ = self.turn(text)
        self.assertIn("Neyi", out)
        return self.ctx._session()

    def test_open_clarification_does_not_block_an_independent_level_request(self):
        session = self.ask()
        self.assertNotEqual(getattr(session, "pending_action", None), None)
        self.ctx.system_control.set_volume = Mock(return_value=True)
        with patch.object(brain_precedence, "claim", return_value=None):
            _, out, handle, feedback = self.turn("sesi 50 yap")
        self.assertEqual(out, "Ses seviyesini yüzde 50 yaptım.")
        self.ctx.system_control.set_volume.assert_called_once_with(50)
        self.ctx.chat.assert_not_called()
        self.assertEqual(feedback.result_status, "handled")
        self.assertIsNone(session.pending_action)  # canonical supersede: açık soru yeni istekle düştü

    def test_open_clarification_does_not_block_an_independent_notes_request(self):
        self.ask()
        self.ctx._notes_text = Mock(return_value="NOTLARIM")
        with patch.object(brain_precedence, "claim", return_value=None):
            _, out, handle, feedback = self.turn("notlarımı göster")
        self.assertEqual(out, "NOTLARIM")
        self.ctx._notes_text.assert_called_once()
        self.ctx.chat.assert_not_called()
        self.assertEqual(feedback.result_status, "handled")

    def test_bare_verb_records_the_canonical_bounded_clarify_state(self):
        session = self.ask("kapat")
        pending = session.pending_action
        self.assertEqual(pending["stage"], "clarify")
        self.assertEqual(pending["owner"], self.owner)
        self.assertEqual(pending["command"], "kapat")
        self.assertEqual(pending["question"], "Neyi kapatmamı istiyorsun?")
        self.assertGreater(pending["expires"], time.time())
        self.assertFalse(hasattr(session, "pending_request"))
        self.assertTrue(awaiting_input(session))

    def test_real_clarification_answer_does_not_continue_multi_step_early(self):
        self.ctx.system_control.set_volume = Mock(return_value=True)
        _, out, _, _ = self.turn("önce kapat sonra sesi 50 yap")
        self.assertIn("yanıt veya onay bekliyor", out)
        self.ctx.system_control.set_volume.assert_not_called()
        session = self.ctx._session()
        self.assertEqual(session.pending_action["stage"], "clarify")
        self.assertTrue(awaiting_input(session))

        # A real answer is consumed as an answer, never as permission to run the remaining step.
        _, answered, _, _ = self.turn("Chrome")
        self.assertNotEqual(answered, "Ses seviyesini yüzde 50 yaptım.")
        self.ctx.system_control.set_volume.assert_not_called()
        self.assertFalse(awaiting_input(session))


class FreeFormClarifyLifecycleTests(unittest.TestCase):
    def pending(self, **extra):
        return {"stage": "clarify", "command": "aç", "question": "Neyi açmamı istiyorsun?",
                "owner": "alice", "expires": time.time() + 90, **extra}

    def test_expired_free_form_clarify_is_a_new_request_not_an_approval_failure(self):
        session = SimpleNamespace(pending_action=self.pending(expires=time.time() - 1))
        profile = SimpleNamespace(slug="alice")
        out = app_actions.continue_voice("Chrome", session, profile, Mock())
        self.assertIsNone(out)
        self.assertIsNone(session.pending_action)

    def test_expired_offered_choice_still_reports_the_expired_approval(self):
        session = SimpleNamespace(pending_action=self.pending(
            expires=time.time() - 1, resume={"action": "app_open", "params": {}, "choices": ["Paint"]}))
        profile = SimpleNamespace(slug="alice")
        out = app_actions.continue_voice("1", session, profile, Mock())
        self.assertEqual(out, "İşlem onayının süresi doldu; isteğini yeniden söyle.")
        self.assertIsNone(session.pending_action)

    def test_free_form_answer_is_not_consumed_as_an_answer(self):
        session = SimpleNamespace(pending_action=self.pending())
        profile = SimpleNamespace(slug="alice")
        out = app_actions.continue_voice("Chrome", session, profile, Mock())
        self.assertIsNone(out)
        self.assertIsNone(session.pending_action)


class NoPendingRequestSlotTests(unittest.TestCase):
    def test_production_modules_never_use_the_retired_slot(self):
        root = Path(__file__).resolve().parents[1] / "modules"
        offenders = [path.name for path in root.rglob("*.py") if "pending_request" in path.read_text(encoding="utf-8")]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
