"""PR7 Closeout-B3a: clarify E2E through prepare->handoff, photo feedback, legacy front-gate precedence."""
import inspect
import re
import tempfile
import time
from contextlib import nullcontext
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import test_brain_closeout_a  # noqa: F401  (installs the shared test stubs)
from modules import app_actions, brain_entry, brain_gates, brain_precedence, engine_commands, engine_loop, engine_runtime, requests_state
from modules.brain_contracts import ActiveContext, ContextReference

CHOICES = ["Mail – Chrome", "Plan – Chrome"]
RESUME = {"action": "pc_window", "params": {"target": "chrome", "action": "focus"}, "choices": CHOICES}


class _Pipeline(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        with patch.object(engine_runtime, "DATA_DIR", Path(temp.name)):
            self.ctx = engine_runtime.EngineContext()
        self.addCleanup(self.ctx._prefetch_pool.shutdown, wait=False, cancel_futures=True)
        self.owner = self.ctx.profile.slug
        self.ctx.system_control = Mock(windows_settings=Mock(return_value=None))
        # Core guards wrap process-global modules; keep them out of the shared test process.
        guard = patch.object(brain_entry, "_install_core_guards", lambda runtime: None)
        guard.start()
        self.addCleanup(guard.stop)

    def through_brain(self, text):
        """Exactly engine_loop's text path: activate -> prepare -> handoff(runtime.handle)."""
        rid = "b3a-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı")
            handle = Mock(wraps=self.ctx.handle)
            out, feedback, _ = brain_entry.handoff(self.ctx, entry, handle, text)
        return entry, out, feedback, handle


class ClarifyEndToEndTests(_Pipeline):
    def pending(self, resume):
        self.ctx._session().pending_action = {"stage": "clarify", "command": "x", "question": "Hangisi?",
                                              "owner": self.owner, "expires": time.time() + 90, "resume": resume}

    def run_choice(self, answer):
        calls = []

        def runner(bridge, profile, action, params, **kw):
            calls.append(dict(params))
            return {"ok": True, "message": "TAMAM"}

        self.pending(RESUME)
        with patch.object(app_actions, "run", side_effect=runner), \
             nullcontext("ikinci classifier fiziksel olarak kaldırıldı"):
            entry, out, feedback, handle = self.through_brain(answer)
        return entry, out, calls, handle

    def test_numbered_and_titled_answers_select_only_the_offered_choice(self):
        for answer in ("2", "Plan – Chrome", "plan"):
            entry, out, calls, handle = self.run_choice(answer)
            self.assertEqual(entry.state_gate.protocol, "session.pending_action.clarify_select", answer)
            self.assertEqual(out, "TAMAM")
            self.assertEqual([c["target"] for c in calls], ["Plan – Chrome"], answer)
            self.assertTrue(handle.called)
            self.assertIsNone(self.ctx._session().pending_action)

    def test_out_of_range_or_ambiguous_answer_is_not_a_selection(self):
        for answer in ("9", "chrome"):
            self.pending(RESUME)
            gate = brain_gates.exact_state_gate(owner=self.owner, request_id="r", text=answer,
                                                active_context=self._context(), state_references=())
            self.assertFalse(gate.matched, answer)

    def _context(self):
        import test_brain_production_entry as fx
        ref = ContextReference(id="pending_action", kind="pending_state", source="session_state", owner=self.owner,
                               provenance={"field": "pending_action", "value": dict(self.ctx._session().pending_action)})
        return ActiveContext(owner=self.owner, request_id="r", pending_references=(ref,))

    def test_expired_clarify_is_not_consumed(self):
        self.pending(RESUME)
        self.ctx._session().pending_action["expires"] = time.time() - 1
        gate = brain_gates.exact_state_gate(owner=self.owner, request_id="r", text="2",
                                            active_context=self._context(), state_references=())
        self.assertFalse(gate.matched)

    def test_open_ended_clarify_answer_is_a_new_request_and_never_reclassified(self):
        self.pending(None)
        with nullcontext("ikinci classifier fiziksel olarak kaldırıldı"), \
             patch.object(self.ctx, "_weather", return_value="Hava 20 derece", create=True):
            entry, out, feedback, handle = self.through_brain("hava nasıl")
        self.assertFalse(entry.state_gate.matched)
        self.assertIsNone(self.ctx._session().pending_action)   # superseded, cannot capture a later "2"
        self.assertNotIn("TAMAM", str(out))

    def test_new_request_supersedes_choice_clarify_and_later_digit_does_not_resume_it(self):
        self.pending(RESUME)
        with patch.object(app_actions, "run", side_effect=AssertionError("eski clarify çalışmamalı")):
            self.through_brain("hava nasıl")
            self.assertIsNone(self.ctx._session().pending_action)

    def test_confirmation_pending_action_still_counts_as_open_pending(self):
        self.ctx._session().pending_action = {"action": "settings_save", "params": {}, "owner": self.owner,
                                              "expires": time.time() + 90}
        rid = "b3a-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text="hava nasıl", source="yazı")
        self.assertTrue(brain_entry._has_open_pending(entry))


class PhotoFeedbackTests(unittest.TestCase):
    def entry(self):
        import test_brain_production_entry as fx
        return fx.entry(brain_entry, semantic=None)

    def test_outcomes(self):
        entry = self.entry()
        self.assertEqual(brain_entry.photo_feedback(entry).result_status, "handled")
        waiting = brain_entry.photo_feedback(entry, awaiting_question=True)
        self.assertEqual((waiting.result_status, waiting.needs_input, waiting.reason_code), ("needs_input", True, "PHOTO_AWAITING_QUESTION"))
        failed = brain_entry.photo_feedback(entry, error=RuntimeError("boom"))
        self.assertEqual((failed.result_status, failed.reason_code), ("failed", "PHOTO_HANDLER_FAILED"))
        cancelled = brain_entry.photo_feedback(entry, error=requests_state.Cancelled("iptal"))
        self.assertEqual((cancelled.result_status, cancelled.reason_code), ("cancelled", "PHOTO_CANCELLED"))
        self.assertEqual(brain_entry.last_feedback().result_status, "cancelled")

    def test_photo_loop_reports_each_real_outcome(self):
        source = inspect.getsource(engine_loop.main)
        self.assertIn("awaiting_question = True", source)
        self.assertIn("photo_feedback(entry, awaiting_question=awaiting_question)", source)
        self.assertIn("photo_feedback(entry, error=exc)", source)
        self.assertNotIn('feedback(entry, result_status="handled", reason_code="PHOTO_CORE_HANDOFF_RETURNED")', source)


class FrontGatePrecedenceTests(_Pipeline):
    def spy_dispatch(self):
        return patch("modules.engine_intents.dispatch", return_value="CORE")

    def test_contract_names_match_engine_commands_order(self):
        source = inspect.getsource(engine_commands.handle)
        markers = {
            "file_command": "runtime._file_command(",
            "windows_settings": "system_control.windows_settings(",
            "selfctl": "selfctl.handle(",
            "user_command": "runtime._user_command(",
            "planner_command": "runtime._planner_command(",
            "macro_teach": "runtime._macro_teach",
            "macro_manage": "runtime._macro_manage",
            "macro_run": "runtime._macro_run",
            "extra_commands": "runtime._extra_commands",
        }
        positions = [source.index(markers[name]) for name in brain_precedence.FRONT_GATES]
        self.assertEqual(positions, sorted(positions))

    def test_each_front_gate_beats_core_weather(self):
        for gate in brain_precedence.FRONT_GATES:
            with self.subTest(gate=gate), self.spy_dispatch() as dispatch:
                reply = f"{gate}-reply"
                with patch.object(brain_precedence, "_gates", side_effect=lambda r, c, l, p=None, g=gate: {
                        n: (lambda n=n: reply if n == g else None) for n in brain_precedence.FRONT_GATES}):
                    entry, out, feedback, handle = self.through_brain("hava nasıl")
                self.assertEqual(out, reply)
                dispatch.assert_not_called()

    def test_core_level_also_yields_to_front_gates(self):
        with self.spy_dispatch() as dispatch, patch.object(brain_precedence, "claim", return_value=("macro_run", "MAKRO")):
            entry, out, feedback, handle = self.through_brain("sesi 70 yap")
        self.assertEqual(out, "MAKRO")
        dispatch.assert_not_called()

    def test_gate_order_is_first_match_wins(self):
        seen = []
        table = {n: (lambda n=n: seen.append(n)) for n in brain_precedence.FRONT_GATES}
        table["selfctl"] = lambda: (seen.append("selfctl"), "S")[1]
        with patch.object(brain_precedence, "_gates", return_value=table):
            self.assertEqual(brain_precedence.claim(self.ctx, "x"), ("selfctl", "S"))
        self.assertEqual(seen, ["file_command", "windows_settings", "selfctl"])

    def test_real_windows_settings_gate_is_consulted_before_core(self):
        self.ctx.system_control.windows_settings.return_value = "Ayarlar açıldı"
        with self.spy_dispatch() as dispatch:
            entry, out, feedback, handle = self.through_brain("hava nasıl")
        self.assertEqual(out, "Ayarlar açıldı")
        dispatch.assert_not_called()

    def test_no_gate_claims_core_runs(self):
        with self.spy_dispatch() as dispatch, patch.object(brain_precedence, "claim", return_value=None):
            entry, out, feedback, handle = self.through_brain("hava nasıl")
        self.assertEqual(out, "CORE")
        dispatch.assert_called_once()
        self.assertEqual(dispatch.call_args[0][1], "weather")

    def test_fast_and_state_gates_still_precede_precedence(self):
        with patch.object(brain_precedence, "claim", side_effect=AssertionError("claim yalnız Core planı için")):
            entry, out, feedback, handle = self.through_brain("hedef durumu")
        self.assertTrue(entry.fast_gate is not None and entry.fast_gate.matched)


if __name__ == "__main__":
    unittest.main()
