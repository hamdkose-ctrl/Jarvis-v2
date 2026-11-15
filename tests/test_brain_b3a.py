"""PR7 Closeout-B3a: clarify E2E through prepare->handoff, photo feedback, legacy front-gate precedence."""
from modules import core_brain_adapter
import inspect
import logging
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
        self.temp = temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root_logger = logging.getLogger()
        previous_handlers = set(root_logger.handlers)
        with patch.object(engine_runtime, "DATA_DIR", Path(temp.name)):
            self.ctx = engine_runtime.EngineContext()

        def close_test_handlers():
            # EngineContext kök logger'a DATA_DIR/jarvis.log handler'ı ekliyor; kapatılmazsa
            # Windows'ta tutamak açık kalır ve yukarıdaki temp.cleanup PermissionError verir.
            for handler in list(root_logger.handlers):
                if handler not in previous_handlers:
                    root_logger.removeHandler(handler)
                    handler.close()

        self.addCleanup(close_test_handlers)
        # requests_state._journal import anında canlı ~/.jarvis/requests.json'a bağlanır: turn'ler
        # testi geçici kayda yazmalı, kullanıcının günlüğünü ve arşiv SQLite'ını hiç değiştirmemeli.
        journal = patch.object(requests_state, "_journal", Path(temp.name) / "requests.json")
        journal.start()
        self.addCleanup(journal.stop)
        saved_records = dict(requests_state._records)
        requests_state._records.clear()
        self.addCleanup(requests_state._records.update, saved_records)
        self.addCleanup(self.ctx._prefetch_pool.shutdown, wait=False, cancel_futures=True)
        self.owner = self.ctx.profile.slug
        self.ctx.system_control = Mock(windows_settings=Mock(return_value=None))

    def through_brain(self, text):
        """Exactly engine_loop's text path: activate -> prepare -> handoff(runtime.handle)."""
        rid = "b3a-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı")
            handle = Mock(wraps=self.ctx.handle)
            out, feedback, _ = core_brain_adapter.handoff(self.ctx, entry, handle, text)
        return entry, out, feedback, handle


class LiveUserStateIsolationTests(_Pipeline):
    """Kanatlı test: bu dosyanın turleri kullanıcının canlı durumuna dokunamaz.

    `requests_state._journal` modül yüklenirken gerçek `~/.jarvis/requests.json`'a bağlanır;
    `_Pipeline` yalnız `engine_runtime.DATA_DIR`'i geçici yaptığı için `register()` canlı günlüğü
    ve yanındaki arşiv SQLite'ını yeniden yazıyordu. `EngineContext` ayrıca kök logger'a
    `jarvis.log` handler'ı ekliyor ve kaldıran olmadığından tutamak kapanmadan kalıcıyordu:
    Windows'ta `TemporaryDirectory` temizliği bu yüzden `PermissionError` veriyordu.
    """

    def test_a_turn_writes_only_the_case_temporary_journal(self):
        self.through_brain("hava nasıl")
        journal = Path(requests_state._journal)
        self.assertTrue(journal.is_relative_to(Path(self.temp.name)),
                        f"tur kullanıcının canlı istek günlüğüne yazdı: {journal}")

    def test_the_case_starts_from_an_empty_request_record_table(self):
        self.assertEqual(dict(requests_state._records), {},
                         "canlı kullanıcının istek kayıtları test sürecine taşındı")
        self.through_brain("hava nasıl")
        self.assertTrue(all(rid.startswith("b3a-") for _user, rid in requests_state._records),
                        f"kendi turüm dışındaki kayıtlar görünüyor: {sorted(requests_state._records)}")

    def test_the_case_leaves_no_open_log_handle_in_its_temp_root(self):
        self.through_brain("hava nasıl")
        self.doCleanups()
        self.assertFalse(Path(self.temp.name).exists(),
                         "geçici kök dizini silinemedi: kök logger'da açık kalan jarvis.log tutamağı")


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
    """Retired raw domain gates cannot steal an accepted typed Core action."""

    def test_only_exact_protocol_gates_are_exposed(self):
        source = inspect.getsource(engine_commands.handle)
        self.assertEqual(brain_precedence.FRONT_GATES, ("file_command", "macro_run"))
        self.assertNotIn("runtime._planner_command(", source)
        self.assertNotIn("runtime._user_controls(", source)
        self.assertNotIn("runtime._extra_commands(", source)
        self.assertNotIn("brain_precedence.claim_tail(", source)
        self.assertFalse(hasattr(brain_precedence, "_gates"))
        self.assertFalse(hasattr(brain_precedence, "TAIL_GATES"))
        self.assertFalse(hasattr(self.ctx, "_planner_command"))
        self.assertFalse(hasattr(self.ctx, "_user_controls"))
        self.assertFalse(hasattr(self.ctx, "_extra_commands"))

    def test_explicit_ui_file_command_is_a_bounded_owner_protocol(self):
        command = '"C:\\Temp\\report.pdf" özetle'
        self.assertIsNotNone(self.ctx._FILE_CMD.match(command))
        with patch.object(self.ctx, "_file_command", return_value="UI FILE") as file_worker:
            self.assertEqual(
                brain_precedence.claim(self.ctx, command, ("weather", {})),
                ("file_command", "UI FILE"))
        file_worker.assert_called_once_with(command)

    def test_unregistered_free_language_never_calls_file_or_macro_worker(self):
        self.ctx.profile.data["macros"] = {}
        with patch.object(self.ctx, "_file_command",
                          side_effect=AssertionError("raw file classification")) as file_worker, \
             patch.object(self.ctx, "_macro_run",
                          side_effect=AssertionError("unregistered shortcut")) as macro:
            self.assertIsNone(brain_precedence.claim(self.ctx, "hava nasıl"))
        file_worker.assert_not_called()
        macro.assert_not_called()

    def test_registered_exact_macro_does_not_match_free_text_variants(self):
        trigger = self.ctx._macro_key("sabah rutini")
        self.ctx.profile.data["macros"] = {trigger: {"actions": ["hava nasıl"]}}
        with patch.object(self.ctx, "_macro_run", return_value="MAKRO") as worker:
            self.assertEqual(
                brain_precedence.claim(self.ctx, "sabah rutini"),
                ("macro_run", "MAKRO"))
            for mention in ("sabah rutininin açıklamasını yap",
                            "sabah rutini?", '"sabah rutini"',
                            "sabah-rutini", "sabah rutini, neden?"):
                with self.subTest(mention=mention):
                    self.assertIsNone(brain_precedence.claim(self.ctx, mention))
        worker.assert_called_once_with("sabah rutini")

    def test_fast_and_state_gates_never_require_raw_precedence(self):
        with patch.object(brain_precedence, "claim",
                          side_effect=AssertionError("Fast cannot run raw claimant")):
            entry, _out, _feedback, _handler = self.through_brain("hedef durumu")
        self.assertTrue(entry.fast_gate is not None and entry.fast_gate.matched)


if __name__ == "__main__":
    unittest.main()
