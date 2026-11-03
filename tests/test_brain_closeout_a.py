"""PR7 Closeout-A: history cap, last_property continuity, structured clarification, typo retry, real feedback."""
import tempfile
from contextlib import nullcontext
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import sys
from types import ModuleType
import test_privacy_voice_and_pending
if 'pyautogui' not in sys.modules:
    _keyboard = ModuleType('pyautogui')
    _keyboard.__getattr__ = lambda name: Mock()
    sys.modules['pyautogui'] = _keyboard
from modules import app_actions, brain_context, brain_entry, brain_gates, engine_commands, engine_runtime, requests_state, session_state
from modules.session_state import SessionState, SessionStore
from modules.brain_contracts import ConversationRelation, RequestKind
import test_brain_production_entry as fixtures


class HistoryLimitTests(unittest.TestCase):
    def build(self, **kw):
        return brain_context.build_active_context(
            owner="alice", request_id="r1", session_store=None, profile=None,
            history_reader=lambda owner, limit: [], history_filter=lambda owner, rows: rows,
            goal_reader=lambda owner: None, goal_is_open=lambda goal: False, **kw)

    def test_default_and_max_are_accepted_and_above_max_is_rejected(self):
        self.assertIsNotNone(self.build())
        self.assertIsNotNone(self.build(history_limit=brain_context._MAX_HISTORY_LIMIT))
        with self.assertRaises(ValueError):
            self.build(history_limit=brain_context._MAX_HISTORY_LIMIT + 1)
        with self.assertRaises(ValueError):
            self.build(history_limit=10_000)

    def test_production_entry_uses_bounded_default(self):
        seen = {}
        original = brain_context.build_active_context

        def spy(**kw):
            seen.update(kw)
            return original(**kw)

        runtime = SimpleNamespace(profile=SimpleNamespace(slug="alice", name="Alice", data={}), _sessions=SessionStore())
        with patch.object(brain_context, "build_active_context", side_effect=spy):
            try:
                brain_entry._build_context(runtime, "alice", "r1")
            except Exception:
                pass
        self.assertNotIn("history_limit", seen)  # caller never overrides: default 12 <= max 50
        self.assertLessEqual(brain_context._HISTORY_LIMIT, brain_context._MAX_HISTORY_LIMIT)


class LastPropertyTests(unittest.TestCase):
    def test_fresh_stale_invalid_and_unknown(self):
        state = SessionState()
        self.assertIsNone(session_state.fresh_property(state))
        session_state.remember_property(state, "volume")
        self.assertEqual(session_state.fresh_property(state), "volume")
        now = state.last_property_at
        self.assertIsNone(session_state.fresh_property(state, now + session_state.LEVEL_PROPERTY_TTL + 1))
        self.assertIsNone(session_state.fresh_property(state, now - 5))   # clock skew: invalid
        session_state.remember_property(state, "banana")                  # ignored
        self.assertEqual(state.last_property, "volume")
        state.last_property = "banana"
        self.assertIsNone(session_state.fresh_property(state))

    def test_owner_isolation(self):
        store = SessionStore()
        session_state.remember_property(store.for_owner("alice"), "brightness")
        self.assertEqual(session_state.fresh_property(store.for_owner("alice")), "brightness")
        self.assertIsNone(session_state.fresh_property(store.for_owner("bob")))

    def test_active_context_exposes_only_fresh_property(self):
        state = SessionState()
        session_state.remember_property(state, "volume")
        store = SimpleNamespace(for_owner=lambda owner: state)
        _, _, recent = brain_context._session_refs("alice", state)
        self.assertTrue(any(r.id == "last_property" and r.provenance["value"] == "volume" for r in recent))
        state.last_property_at -= session_state.LEVEL_PROPERTY_TTL + 1
        _, _, recent = brain_context._session_refs("alice", state)
        self.assertFalse(any(r.id == "last_property" for r in recent))


class BareLevelTests(unittest.TestCase):
    """Ham "70 yap" artık kendi başına etki seçmiyor: cümle yalnız üretim zincirinden geçer.

    Hedef söylenmemişse sorunun tek yazarı Understanding (`level target unspecified`), söylenen
    cevabın tek yürütücüsü State Gate `session.pending_level.select` -> Core `level_set`'tir.
    """

    def build(self, state_setup=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        # test_engine_modular.context kalıbı: bu turda açılan kök log tutucusu kapanmadan
        # geçici klasör silinmez (Windows'ta jarvis.log kilidi).
        root_logger = engine_runtime.logging.getLogger()
        previous_handlers = set(root_logger.handlers)
        with patch.object(engine_runtime, "DATA_DIR", Path(temp.name)):
            context = engine_runtime.EngineContext()

        def close_test_handlers():
            for handler in list(root_logger.handlers):
                if handler not in previous_handlers:
                    root_logger.removeHandler(handler)
                    handler.close()

        self.addCleanup(close_test_handlers)
        self.addCleanup(context._prefetch_pool.shutdown, wait=False, cancel_futures=True)
        context.system_control = Mock(set_volume=Mock(return_value=True), set_brightness_verified=Mock(return_value=True),
                                      windows_settings=Mock(return_value=None))
        if state_setup:
            state_setup(context._session())
        return context

    def turn(self, context, text):
        """engine_loop'un yazı yolu: activate -> prepare -> handoff(runtime.handle)."""
        owner = context.profile.slug
        rid = "closeout-a-" + uuid.uuid4().hex[:8]
        guard = patch.object(brain_entry, "_install_core_guards", lambda runtime: None)
        with guard, patch.object(context, "route", side_effect=AssertionError("model/router çağrılmamalı"), create=True):
            requests_state.register(owner, rid)
            with requests_state.activate(owner, rid):
                entry = brain_entry.prepare(context, owner=owner, request_id=rid, text=text, source="yazı")
                out, _feedback, _ = brain_entry.handoff(context, entry, context.handle, text)
        return out

    def run_pipeline(self, text, state_setup=None):
        context = self.build(state_setup)
        return context, self.turn(context, text)

    def test_last_volume_sets_volume(self):
        context, reply = self.run_pipeline("70 yap", lambda s: session_state.remember_property(s, "volume"))
        context.system_control.set_volume.assert_called_once_with(70)
        self.assertIn("yüzde 70", reply)

    def test_last_brightness_sets_brightness(self):
        context, reply = self.run_pipeline("70 yap", lambda s: session_state.remember_property(s, "brightness"))
        context.system_control.set_brightness_verified.assert_called_once_with(70)
        self.assertIn("parlaklığını yüzde 70", reply)

    def test_no_property_still_asks(self):
        context, reply = self.run_pipeline("70 yap")
        self.assertEqual(reply, "Yüzde 70, ses mi parlaklık mı?")
        context.system_control.set_volume.assert_not_called()
        context.system_control.set_brightness_verified.assert_not_called()

    def test_stale_or_invalid_property_asks_again(self):
        def stale(state):
            session_state.remember_property(state, "volume")
            state.last_property_at -= session_state.LEVEL_PROPERTY_TTL + 1
        context, reply = self.run_pipeline("70 yap", stale)
        self.assertEqual(reply, "Yüzde 70, ses mi parlaklık mı?")
        context, reply = self.run_pipeline("70 yap", lambda s: setattr(s, "last_property", "banana"))
        self.assertEqual(reply, "Yüzde 70, ses mi parlaklık mı?")

    def test_successful_answer_to_question_becomes_last_property(self):
        context, _ = self.run_pipeline("70 yap")
        reply = self.turn(context, "ses")
        self.assertEqual(session_state.fresh_property(context._session()), "volume")
        context.system_control.set_volume.assert_called_once_with(70)

    def test_future_dated_property_asks_in_pipeline(self):
        def future(state):
            session_state.remember_property(state, "volume")
            state.last_property_at += 3600
        context, reply = self.run_pipeline("70 yap", future)
        self.assertEqual(reply, "Yüzde 70, ses mi parlaklık mı?")
        context.system_control.set_volume.assert_not_called()

    def test_failed_set_is_not_remembered(self):
        context, reply = self.run_pipeline("70 yap", lambda s: session_state.remember_property(s, "volume"))
        context.system_control.set_volume.return_value = False
        before = context._session().last_property_at
        context._session().pending_level = None
        self.turn(context, "80 yap")
        self.assertEqual(context._session().last_property_at, before)


class StructuredClarificationTests(unittest.TestCase):
    def setUp(self):
        self.profile = SimpleNamespace(slug="alice", data={})
        self.state = SessionState()
        self.emitted = []

    def pending(self, resume):
        self.state.pending_action = {"stage": "clarify", "command": "x", "question": "Hangisi?", "owner": "alice",
                                     "expires": 10**12, "resume": resume}

    def run_resume(self, answer, runner):
        with patch.object(app_actions, "_owned") as owned, patch.object(app_actions, "run", side_effect=runner), \
             nullcontext("ikinci classifier fiziksel olarak kaldırıldı"):
            owned.return_value.__enter__ = lambda s: Mock()
            owned.return_value.__exit__ = lambda s, *a: False
            return app_actions.continue_voice(answer, self.state, self.profile, lambda *a: self.emitted.append(a))

    def test_choice_by_number_and_title_resumes_without_router(self):
        for answer in ("2", "Plan – Chrome", "plan"):
            calls = []
            self.pending({"action": "pc_window", "params": {"target": "chrome", "action": "focus"},
                          "choices": ["Mail – Chrome", "Plan – Chrome"]})

            def runner(bridge, profile, action, params, **kw):
                calls.append(params)
                return {"ok": True, "message": "Tamam."}

            self.assertEqual(self.run_resume(answer, runner), "Tamam.")
            self.assertEqual(calls[0]["target"], "Plan – Chrome")
            self.assertEqual(calls[0]["action"], "focus")

    def test_unrelated_or_ambiguous_answer_falls_through_as_new_request(self):
        for answer in ("hava nasıl", "chrome", "9"):
            self.pending({"action": "pc_window", "params": {"target": "chrome", "action": "focus"},
                          "choices": ["Mail – Chrome", "Plan – Chrome"]})
            self.assertIsNone(self.run_resume(answer, AssertionError))
            self.assertIsNone(self.state.pending_action)

    def test_free_form_question_without_resume_never_reclassifies(self):
        self.pending(None)
        self.assertIsNone(self.run_resume("evet o", AssertionError))
        self.assertIsNone(self.state.pending_action)

    def test_second_ambiguity_keeps_structured_resume(self):
        self.pending({"action": "pc_window", "params": {"target": "chrome", "action": "focus"}, "choices": ["A – Chrome", "B – Chrome"]})
        reply = self.run_resume("1", lambda *a, **k: {"ok": False, "needs_clarification": True, "message": "Hangisi?", "choices": ["A1", "A2"]})
        self.assertEqual(reply, "Hangisi?")
        self.assertEqual(self.state.pending_action["resume"]["choices"], ["A1", "A2"])

    def test_router_classify_is_no_longer_referenced_by_app_actions(self):
        import inspect
        self.assertNotIn("router.classify", inspect.getsource(app_actions.continue_voice))
        self.assertNotIn("router", inspect.getsource(app_actions._resume_clarification))


class TypoRetryTests(unittest.TestCase):
    def runtime(self, results):
        calls = []
        rt = SimpleNamespace(_typo_pass=False, _typo_orig="")
        rt.handle = Mock(side_effect=AssertionError("runtime.handle özyinelemeli çağrılmamalı"))

        def one_pass(runtime, command):
            calls.append((command, runtime._typo_pass, runtime._typo_orig))
            return results.pop(0)

        return rt, calls, one_pass

    def test_retry_runs_once_with_flags_and_resets(self):
        rt, calls, one_pass = self.runtime([engine_commands._TypoRetry("duzeltilmis"), "Cevap"])
        with patch.object(engine_commands, "handle", one_pass):
            self.assertEqual(engine_commands.handle_request(rt, " yanlis "), "Cevap")
        self.assertEqual(calls, [(" yanlis ", False, ""), ("duzeltilmis", True, "yanlis")])
        self.assertEqual((rt._typo_pass, rt._typo_orig), (False, ""))
        rt.handle.assert_not_called()

    def test_second_retry_is_refused_and_flags_reset(self):
        rt, calls, one_pass = self.runtime([engine_commands._TypoRetry("a"), engine_commands._TypoRetry("b")])
        with patch.object(engine_commands, "handle", one_pass):
            with self.assertRaises(RuntimeError):
                engine_commands.handle_request(rt, "x")
        self.assertEqual((rt._typo_pass, rt._typo_orig), (False, ""))
        self.assertEqual(len(calls), 2)

    def test_no_typo_single_pass(self):
        rt, calls, one_pass = self.runtime(["Tamam"])
        with patch.object(engine_commands, "handle", one_pass):
            self.assertEqual(engine_commands.handle_request(rt, "merhaba"), "Tamam")
        self.assertEqual(len(calls), 1)

    def test_handle_source_does_not_recurse_into_runtime_handle(self):
        import inspect
        self.assertNotIn("runtime.handle(fixed)", inspect.getsource(engine_commands.handle))


class GoalStatusRecognizerTests(unittest.TestCase):
    def test_exact_phrases_only(self):
        self.assertEqual(brain_gates.goal_status_selection("Hedef durumu."), "summary")
        self.assertEqual(brain_gates.goal_status_selection("işin durumu"), "summary")
        self.assertEqual(brain_gates.goal_status_selection("hedef ayrıntıları"), "details")
        self.assertIsNone(brain_gates.goal_status_selection("hedef durumu nedir acaba"))
        self.assertIsNone(brain_gates.goal_status_selection(None))

    def test_fast_gate_uses_same_recognizer(self):
        active = fixtures.context()
        hit = brain_gates.deterministic_fast_gate(owner=fixtures.OWNER, request_id=fixtures.RID, text="hedef durumu", active_context=active)
        self.assertTrue(hit.matched)
        self.assertEqual(hit.protocol, "fast.goal.status")


class RealFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.module = brain_entry
        self.entry = fixtures.entry(brain_entry, semantic=fixtures.understanding(kind=RequestKind.CAPABILITY))

    def runtime(self, pending=None):
        state = SessionState()
        rt = SimpleNamespace(profile=SimpleNamespace(slug=fixtures.OWNER, name="X", data={}), _sessions=object(), _session=lambda: state)
        return rt, state

    def handoff(self, handler, runtime=None):
        rt = runtime or self.runtime()[0]
        with patch.object(brain_entry, "_install_core_guards"), patch.object(brain_entry, "_correlated_job_id", return_value=None):
            return brain_entry.handoff(rt, self.entry, handler, "işlem")

    def test_handled(self):
        _, fb, _ = self.handoff(Mock(return_value="tamam"))
        self.assertEqual((fb.result_status, fb.reason_code, fb.needs_input), ("handled", "CORE_HANDOFF_RETURNED", False))
        self.assertIs(brain_entry.last_feedback(), fb)

    def test_core_opening_pending_is_needs_input(self):
        rt, state = self.runtime()

        def handler(command):
            state.pending_app = {"name": "x"}
            return "Hangi uygulama?"

        _, fb, _ = self.handoff(handler, rt)
        self.assertEqual((fb.result_status, fb.needs_input, fb.reason_code), ("needs_input", True, "CORE_AWAITING_INPUT"))
        self.assertEqual(fb.ambiguities, ("core pending: pending_app",))

    def test_preexisting_pending_is_not_new_input(self):
        rt, state = self.runtime()
        state.pending_app = {"name": "x"}
        _, fb, _ = self.handoff(Mock(return_value="tamam"), rt)
        self.assertEqual(fb.result_status, "handled")

    def test_failure_and_cancel_are_recorded_then_reraised(self):
        from modules import requests_state
        with self.assertRaises(ValueError):
            self.handoff(Mock(side_effect=ValueError("secret detail")))
        fb = brain_entry.last_feedback()
        self.assertEqual((fb.result_status, fb.reason_code), ("failed", "CORE_HANDLER_FAILED"))
        self.assertNotIn("secret", repr(fb))
        with self.assertRaises(requests_state.Cancelled):
            self.handoff(Mock(side_effect=requests_state.Cancelled("iptal")))
        self.assertEqual(brain_entry.last_feedback().result_status, "cancelled")

    def test_dead_canonical_fallback_removed(self):
        self.assertFalse(hasattr(brain_entry, "canonical_fallback"))


class CloseoutAEdgeCaseTests(unittest.TestCase):
    """Reviewer-added edge cases: history cap types, last_property owner/skew, continue_voice guards, feedback precedence."""

    def test_history_limit_invalid_values_rejected(self):
        h = HistoryLimitTests()
        for bad in (0, -1, True, 50.0, "12", None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                h.build(history_limit=bad)

    def test_property_with_bad_timestamp_types_is_invalid(self):
        for bad in (True, None, "1", float("nan"), float("inf"), float("-inf")):
            state = SessionState()
            state.last_property = "volume"
            state.last_property_at = bad
            self.assertIsNone(session_state.fresh_property(state), repr(bad))
        state = SessionState()
        session_state.remember_property(state, "volume")
        self.assertEqual(session_state.fresh_property(state, state.last_property_at + session_state.LEVEL_PROPERTY_TTL), "volume")
        self.assertIsNone(session_state.fresh_property(state, state.last_property_at + session_state.LEVEL_PROPERTY_TTL + 0.01))

    def test_other_owner_property_never_used_in_pipeline_or_context(self):
        alice, bob = SessionState(), SessionState()
        session_state.remember_property(alice, "volume")
        _, _, recent_bob = brain_context._session_refs("bob", bob)
        self.assertFalse(any(r.id == "last_property" for r in recent_bob))
        _, _, recent_alice = brain_context._session_refs("alice", alice)
        self.assertTrue(any(r.id == "last_property" and r.owner == "alice" for r in recent_alice))

    def test_continue_voice_guards(self):
        profile, state = SimpleNamespace(slug="alice", data={}), SessionState()
        base = {"stage": "clarify", "command": "x", "question": "?", "owner": "alice", "expires": 10**12,
                "resume": {"action": "pc_window", "params": {"target": "c"}, "choices": ["A – X", "B – X"]}}
        with nullcontext("ikinci classifier fiziksel olarak kaldırıldı"), \
             patch.object(app_actions, "run", side_effect=AssertionError("must not run")):
            state.pending_action = dict(base, owner="bob")
            self.assertIn("süresi doldu", app_actions.continue_voice("1", state, profile, lambda *a: None))
            state.pending_action = dict(base, expires=0)
            self.assertIn("süresi doldu", app_actions.continue_voice("1", state, profile, lambda *a: None))
            state.pending_action = dict(base)
            self.assertIn("iptal", app_actions.continue_voice("vazgeç", state, profile, lambda *a: None))
            for answer in ("0", "-1", "3", "", "  ", "ab"):
                state.pending_action = dict(base)
                self.assertIsNone(app_actions.continue_voice(answer, state, profile, lambda *a: None), repr(answer))
                self.assertIsNone(state.pending_action)

    def test_entry_clarification_wins_and_keyboard_interrupt_is_failed(self):
        t = RealFeedbackTests()
        t.setUp()
        rt, state = t.runtime()
        with self.assertRaises(KeyboardInterrupt):
            t.handoff(Mock(side_effect=KeyboardInterrupt()), rt)
        self.assertEqual(brain_entry.last_feedback().result_status, "failed")
        _, fb, _ = t.handoff(Mock(return_value="ok"), rt)
        self.assertIs(brain_entry.last_feedback(), fb)
        self.assertEqual(fb.result_status, "handled")   # stale failure feedback is reset per handoff


if __name__ == "__main__":
    unittest.main()
