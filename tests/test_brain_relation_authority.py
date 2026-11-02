"""PR1: turn relation authority yalnız Understanding'dedir; Core slot varlığından karar taklit etmez.

Açık bir clarification (stage=clarify) yeni bir capability isteğini bloke edemez; Core plan
çalışır, sohbet yedeğine düşmez. Gerçek clarification yanıtı multi-step'i erken sürdürmez.
"""
import ast
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_brain_closeout_a  # noqa: F401  (shared test stubs)
from modules import app_actions, brain_core_map, brain_context, brain_entry, brain_precedence, desktop_agent
from modules import brain_understanding, engine_commands, engine_runtime, goal_executor, job_front, requests_state
from modules import history as history_mod
from modules.brain_contracts import ActiveContext, ConversationRelation, RequestKind
from modules.brain_gates import GateObservation
from modules.command_manager import awaiting_input
from modules.system_control import APPS as STATIC_APPS
from modules.system_control import ApplicationResult


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
        self.ctx.system_control = Mock(windows_settings=Mock(return_value=None), APPS=dict(STATIC_APPS))
        self.ctx.chat = Mock(return_value="CHAT")
        # Bu testler kullanıcının canlı hedef/iş/izin durumunu okumaz ve iptal/tamam
        # cevabını gerçek bounded protokole düşürmez.
        for target, attr in ((brain_context, "_default_goal_reader"),
                             (job_front, "observe"),
                             (desktop_agent, "_load")):
            state_patch = patch.object(target, attr, return_value=None)
            state_patch.start()
            self.addCleanup(state_patch.stop)
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
            entry, out, handle, feedback = self.turn("sesi 50 yap")
        self.assertIs(entry.understanding.conversation_relation, ConversationRelation.NEW_REQUEST)
        self.assertEqual(out, "Ses seviyesini yüzde 50 yaptım.")
        self.ctx.system_control.set_volume.assert_called_once_with(50)
        self.ctx.chat.assert_not_called()
        self.assertEqual(feedback.result_status, "handled")
        self.assertIsNone(session.pending_action)  # canonical supersede: açık soru yeni istekle düştü

    def test_typed_clarify_answer_opens_the_app_through_core(self):
        session = self.ask("aç")
        self.assertEqual(session.pending_action.get("proposal"), {"kind": "app.open"})
        self.ctx.system_control.open_application = Mock(
            return_value=ApplicationResult("Chrome penceresi açık; açılışını doğruladım.", ok=True))
        with patch.object(brain_precedence, "claim", return_value=None):
            entry, out, handle, feedback = self.turn("Chrome")
        self.assertIs(entry.understanding.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)
        self.assertIs(entry.understanding.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(entry.understanding.capability_hint, "app.open")
        pending = next(ref for ref in entry.active_context.pending_references if ref.id == "pending_action")
        self.assertIn("chrome", pending.provenance["targets"])  # caller-supplied canonical evidence
        self.ctx.system_control.open_application.assert_called_once_with("Chrome")
        self.assertEqual(out, "Chrome penceresi açık; açılışını doğruladım.")
        self.ctx.chat.assert_not_called()
        self.assertEqual(feedback.result_status, "handled")
        self.assertIsNone(session.pending_action)
        self.assertFalse(awaiting_input(session))

    def turn_typed_answer(self, session, answer):
        self.ctx.system_control.open_application = Mock(
            return_value=ApplicationResult("açıldı", ok=True))
        with patch.object(brain_precedence, "claim", return_value=None):
            entry, out, handle, feedback = self.turn(answer)
        return entry, out, session

    def test_expired_typed_proposal_never_reaches_the_open_owner(self):
        session = self.ask("aç")
        session.pending_action["expires"] = time.time() - 1
        entry, out, _ = self.turn_typed_answer(session, "Chrome")
        self.assertIs(entry.understanding.conversation_relation, ConversationRelation.NEW_REQUEST)
        self.ctx.system_control.open_application.assert_not_called()
        self.ctx.chat.assert_called_once()
        self.assertIsNone(session.pending_action)
        self.assertFalse(awaiting_input(session))

    def test_foreign_owner_typed_proposal_never_reaches_the_open_owner(self):
        session = self.ask("aç")
        session.pending_action["owner"] = "bob"
        self.ctx.system_control.open_application = Mock()
        with self.assertRaises(ValueError):
            self.turn("Chrome")
        self.ctx.system_control.open_application.assert_not_called()

    def test_unrelated_sentence_is_not_a_typed_app_target(self):
        session = self.ask("aç")
        entry, out, _ = self.turn_typed_answer(session, "yarın toplantım var")
        self.assertIs(entry.understanding.conversation_relation, ConversationRelation.NEW_REQUEST)
        self.assertNotEqual(entry.understanding.capability_hint, "app.open")
        self.ctx.system_control.open_application.assert_not_called()
        self.assertNotEqual(out, "açıldı")  # takvim gibi kendi deterministic sahibi cevaplar
        self.assertIsNone(session.pending_action)

    def test_capitalized_confirmation_is_not_a_typed_app_target(self):
        for answer in ("Tamam", "Olur"):
            with self.subTest(answer=answer):
                session = self.ask("aç")
                entry, out, _ = self.turn_typed_answer(session, answer)
                self.assertIs(entry.understanding.conversation_relation, ConversationRelation.NEW_REQUEST)
                self.ctx.system_control.open_application.assert_not_called()
                self.assertIsNone(session.pending_action)
        session = self.ask("aç")
        entry, out, _ = self.turn_typed_answer(session, "İptal")
        self.assertEqual(entry.state_gate.protocol, "session.pending_action.clarify_cancel")
        self.ctx.system_control.open_application.assert_not_called()
        self.assertIsNone(session.pending_action)

    def test_new_request_chat_clears_the_open_clarification(self):
        session = self.ask("aç")
        self.ctx.system_control.open_application = Mock()
        with patch.object(brain_precedence, "claim", return_value=None):
            entry, out, handle, feedback = self.turn("merhaba")
        self.assertIs(entry.understanding.conversation_relation, ConversationRelation.NEW_REQUEST)
        self.ctx.chat.assert_called_once()
        self.ctx.system_control.open_application.assert_not_called()
        self.assertIsNone(session.pending_action)
        self.assertFalse(awaiting_input(session))

    def test_single_word_unrelated_is_not_a_typed_app_target(self):
        for answer in ("yarın", "kuantum"):
            with self.subTest(answer=answer):
                session = self.ask("aç")
                entry, out, _ = self.turn_typed_answer(session, answer)
                self.assertIs(entry.understanding.conversation_relation, ConversationRelation.NEW_REQUEST)
                self.assertNotEqual(entry.understanding.capability_hint, "app.open")
                self.ctx.system_control.open_application.assert_not_called()
                self.assertIsNone(session.pending_action)
                self.assertFalse(awaiting_input(session))

    def test_fast_gate_supersedes_an_open_clarification(self):
        for text, prefix in (("saat kaç", "Saat "), ("tarih", "Bugün ")):
            with self.subTest(text=text):
                session = self.ask("aç")
                self.assertIsNotNone(session.pending_action)
                entry, out, handle, feedback = self.turn(text)
                self.assertTrue(entry.fast_gate.matched)
                self.assertTrue(out.startswith(prefix), out)
                self.assertIsNone(session.pending_action)
                self.assertFalse(awaiting_input(session))

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
        self.assertEqual(pending["proposal"], {"kind": "app.close"})
        self.assertGreater(pending["expires"], time.time())
        self.assertFalse(hasattr(session, "pending_request"))
        self.assertTrue(awaiting_input(session))

    def test_bare_verbs_without_a_bounded_owner_open_no_resumable_state(self):
        from modules import goal_executor
        for text in ("sil", "gönder", "başlat"):
            with self.subTest(text=text):
                with patch.object(goal_executor, "run", return_value="TASK") as run:
                    entry, out, handle, feedback = self.turn(text)
                run.assert_called_once()  # normal task flow, not a dead-end question
                session = self.ctx._session()
                self.assertEqual(out, "TASK")
                self.assertNotIn("Neyi", out or "")
                self.assertIsNone(session.pending_action)
                self.assertFalse(awaiting_input(session))
                self.assertNotEqual(feedback.result_status, "needs_input")

    def test_typed_close_answer_opens_the_existing_confirmation(self):
        session = self.ask("kapat")
        self.ctx.system_control.close_application = Mock(
            return_value=ApplicationResult("Chrome pencerelerinin kapandığını doğruladım.", ok=True))
        with patch.object(brain_precedence, "claim", return_value=None):
            entry, out, handle, feedback = self.turn("Chrome")
        self.assertIs(entry.understanding.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)
        self.assertIs(entry.understanding.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(entry.understanding.capability_hint, "app.close")
        # The answer resolves the target only; the effect stays behind the existing approval gate.
        self.ctx.system_control.close_application.assert_not_called()
        self.assertEqual(session.pending_confirm, {"action": "close_app", "name": "Chrome"})
        self.assertIsNone(session.pending_action)
        self.assertIn("onaylıyor musun", out)
        self.ctx.chat.assert_not_called()
        self.assertEqual(feedback.result_status, "needs_input")

    def test_close_confirmation_runs_the_existing_owner_after_approval(self):
        session = self.ask("kapat")
        result = ApplicationResult("Chrome pencerelerinin kapandığını doğruladım.", ok=True)
        self.ctx.system_control.close_application = Mock(return_value=result)
        with patch.object(brain_precedence, "claim", return_value=None):
            self.turn("Chrome")
        with patch.object(brain_precedence, "claim", return_value=None):
            entry, out, handle, feedback = self.turn("evet")
        self.assertTrue(entry.state_gate.matched)
        self.assertEqual(entry.state_gate.protocol, "session.pending_confirm.confirm")
        self.ctx.system_control.close_application.assert_called_once_with("Chrome")
        self.assertEqual(out, result)
        self.assertIsNone(session.pending_confirm)
        self.ctx.chat.assert_not_called()

    def test_close_clarification_is_not_answered_by_independent_requests(self):
        cases = (
            ("sesi 50 yap", lambda: setattr(self.ctx.system_control, "set_volume", Mock(return_value=True))),
            ("notlarımı göster", lambda: setattr(self.ctx, "_notes_text", Mock(return_value="NOTLARIM"))),
            ("saat kaç", None),
            ("merhaba", None),
        )
        for text, prepare in cases:
            with self.subTest(text=text):
                session = self.ask("kapat")
                self.ctx.system_control.close_application = Mock()
                if prepare is not None:
                    prepare()
                with patch.object(brain_precedence, "claim", return_value=None):
                    entry, out, handle, feedback = self.turn(text)
                if entry.understanding is None:
                    self.assertTrue(entry.fast_gate.matched)
                else:
                    self.assertIsNot(entry.understanding.conversation_relation,
                                     ConversationRelation.ANSWER_TO_PENDING)
                self.ctx.system_control.close_application.assert_not_called()
                self.assertIsNone(session.pending_confirm)
                self.assertIsNone(session.pending_action)

    def test_real_clarification_answer_does_not_continue_multi_step_early(self):
        self.ctx.system_control.set_volume = Mock(return_value=True)
        self.ctx.system_control.close_application = Mock(
            return_value=ApplicationResult("Chrome pencerelerinin kapandığını doğruladım.", ok=True))
        _, out, _, _ = self.turn("önce kapat sonra sesi 50 yap")
        self.assertIn("yanıt veya onay bekliyor", out)
        self.ctx.system_control.set_volume.assert_not_called()
        session = self.ctx._session()
        self.assertEqual(session.pending_action["stage"], "clarify")
        self.assertEqual(session.pending_action["proposal"], {"kind": "app.close"})
        self.assertTrue(awaiting_input(session))

        # The answer resolves step 1's target and opens its confirmation; the volume step does not run.
        entry, answered, _, _ = self.turn("Chrome")
        self.assertIs(entry.understanding.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)
        self.assertNotEqual(answered, "Ses seviyesini yüzde 50 yaptım.")
        self.ctx.system_control.set_volume.assert_not_called()
        self.ctx.system_control.close_application.assert_not_called()
        self.assertEqual(session.pending_confirm, {"action": "close_app", "name": "Chrome"})
        self.assertIsNone(session.pending_action)

        # Approval runs only the close owner; the old sequence's volume step stays unfinished.
        entry, approved, _, _ = self.turn("evet")
        self.assertEqual(entry.state_gate.protocol, "session.pending_confirm.confirm")
        self.ctx.system_control.close_application.assert_called_once_with("Chrome")
        self.assertEqual(approved, "Chrome pencerelerinin kapandığını doğruladım.")
        self.ctx.system_control.set_volume.assert_not_called()
        self.assertIsNone(session.pending_confirm)
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

    def test_typed_proposal_is_left_for_canonical_understanding(self):
        session = SimpleNamespace(pending_action=self.pending(proposal={"kind": "app.open"}))
        profile = SimpleNamespace(slug="alice")
        out = app_actions.continue_voice("Chrome", session, profile, Mock())
        self.assertIsNone(out)
        self.assertEqual(session.pending_action["proposal"], {"kind": "app.open"})

    def test_expired_typed_proposal_is_not_executed(self):
        session = SimpleNamespace(pending_action=self.pending(
            proposal={"kind": "app.open"}, expires=time.time() - 1))
        profile = SimpleNamespace(slug="alice")
        out = app_actions.continue_voice("Chrome", session, profile, Mock())
        self.assertIsNone(out)
        self.assertIsNone(session.pending_action)


class AppOpenProposalValidationTests(unittest.TestCase):
    def test_core_rejects_unbounded_or_empty_targets(self):
        self.assertIsNone(brain_core_map.core_plan("app.open", {"app": ""}))
        self.assertIsNone(brain_core_map.core_plan("app.open", {"app": "   "}))
        self.assertIsNone(brain_core_map.core_plan("app.open", {"app": "x" * 41}))
        self.assertIsNone(brain_core_map.core_plan("app.open", {"app": "chrome\x00"}))
        self.assertIsNone(brain_core_map.core_plan("app.open", {"app": "Chrome", "args": []}))

    def test_core_maps_a_bounded_target_to_the_existing_owner(self):
        self.assertEqual(brain_core_map.core_plan("app.open", {"app": "Chrome"}),
                         ("app_open", {"name": "Chrome"}))


class AppCloseProposalValidationTests(unittest.TestCase):
    def test_core_rejects_unbounded_or_empty_targets(self):
        self.assertIsNone(brain_core_map.core_plan("app.close", {"app": ""}))
        self.assertIsNone(brain_core_map.core_plan("app.close", {"app": "   "}))
        self.assertIsNone(brain_core_map.core_plan("app.close", {"app": "x" * 41}))
        self.assertIsNone(brain_core_map.core_plan("app.close", {"app": "chrome\x00"}))
        self.assertIsNone(brain_core_map.core_plan("app.close", {"app": "Chrome", "args": []}))

    def test_core_maps_a_bounded_target_to_the_close_confirmation_intent(self):
        self.assertEqual(brain_core_map.core_plan("app.close", {"app": "Chrome"}),
                         ("app_close", {"name": "Chrome"}))


class ClarifyProposalGuardTests(unittest.TestCase):
    def value(self, **overrides):
        base = {"stage": "clarify", "command": "aç", "question": "Neyi açmamı istiyorsun?",
                "owner": "hamdi", "expires": time.time() + 60, "proposal": {"kind": "app.open"}}
        base.update(overrides)
        return base

    def answer(self, text, *, active=True, aliases=tuple(sorted(STATIC_APPS)), **overrides):
        from modules.brain_contracts import ActiveContext, ContextReference
        ref = ContextReference(owner="hamdi", kind="pending_state", source="session_state",
                               id="pending_action",
                               provenance={"value": self.value(**overrides), "active": active,
                                           "targets": tuple(aliases)})
        return brain_understanding.understand(
            owner="hamdi", request_id="r", text=text,
            active_context=ActiveContext(owner="hamdi", request_id="r", pending_references=(ref,)),
            candidates=(), references=())

    def test_context_observes_owner_and_expiry_before_understanding(self):
        # Validity is observation evidence: Understanding must not read the clock itself.
        self.assertIs(self.answer("Chrome", active=False).conversation_relation,
                      ConversationRelation.NEW_REQUEST)
        self.assertIs(self.answer("Chrome", owner="bob").conversation_relation,
                      ConversationRelation.NEW_REQUEST)
        self.assertIs(self.answer("Chrome").conversation_relation,
                      ConversationRelation.ANSWER_TO_PENDING)

    def test_only_canonical_alias_evidence_is_an_app_target(self):
        for text in ("Chrome", "Google Chrome", "hesap makinesi", "not defteri"):
            with self.subTest(text=text):
                self.assertIs(self.answer(text).conversation_relation,
                              ConversationRelation.ANSWER_TO_PENDING)
        for text in ("yarın", "kuantum", "evdeyim", "toplantı", "yarın toplantım var"):
            with self.subTest(text=text):
                self.assertIs(self.answer(text).conversation_relation,
                              ConversationRelation.NEW_REQUEST)

    def test_missing_evidence_fails_closed(self):
        self.assertIs(self.answer("Chrome", aliases=()).conversation_relation,
                      ConversationRelation.NEW_REQUEST)

    def test_close_proposal_is_a_typed_capability(self):
        result = self.answer("Chrome", proposal={"kind": "app.close"})
        self.assertIs(result.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)
        self.assertEqual(result.capability_hint, "app.close")
        self.assertEqual(result.arguments.get("app"), "Chrome")


class UnderstandingArchitectureGuardTests(unittest.TestCase):
    def test_understanding_reads_no_clock_or_effect_domain(self):
        tree = ast.parse(Path(brain_understanding.__file__).read_text(encoding="utf-8-sig"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
                imported.update(f"{node.module}.{alias.name}" for alias in node.names)
        self.assertNotIn("time", imported)
        offenders = sorted(
            name for name in imported
            if name == "system_control" or name.startswith("modules.system_control")
        )
        self.assertEqual(offenders, [])


class NoPendingRequestSlotTests(unittest.TestCase):
    def test_production_modules_never_use_the_retired_slot(self):
        root = Path(__file__).resolve().parents[1] / "modules"
        offenders = [path.name for path in root.rglob("*.py") if "pending_request" in path.read_text(encoding="utf-8")]
        self.assertEqual(offenders, [])


class StatePrecedenceTests(unittest.TestCase):
    """Açık foreground etkileşim çıplak cevabı sahiplenir; uzun ömürlü Goal çalamaz.

    Goal kayıtları gerçek üretim yoluyla (`goal_executor._save`) geçici bir STORE'a yazılır;
    canlı kullanıcı klasörü okunmaz ve mevcut kişisel kayıtlar silinmez.
    """

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
        self.ctx.system_control = Mock(windows_settings=Mock(return_value=None), APPS=dict(STATIC_APPS))
        self.ctx.chat = Mock(return_value="CHAT")

        goals = Path(self.temp.name) / "goals"
        # Boş geçici kök: varsayılan okuyucu canlı geçmişi/kişisel hedefleri görmez.
        history_root = Path(self.temp.name) / "history"
        for target, attr, value in ((goal_executor, "STORE", goals), (history_mod, "DIR", history_root)):
            state_patch = patch.object(target, attr, value)
            state_patch.start()
            self.addCleanup(state_patch.stop)
        for target, attr in ((job_front, "observe"), (desktop_agent, "_load")):
            state_patch = patch.object(target, attr, return_value=None)
            state_patch.start()
            self.addCleanup(state_patch.stop)
        guard = patch.object(brain_entry, "_install_core_guards", lambda runtime: None)
        guard.start()
        self.addCleanup(guard.stop)
        self.run_goal = Mock(return_value="GOAL_RUN")
        run_patch = patch.object(goal_executor, "run", self.run_goal)
        run_patch.start()
        self.addCleanup(run_patch.stop)

    def goal(self, *, state: str, **extra):
        job = {
            "id": uuid.uuid4().hex[:16], "owner": self.owner, "request": "test hedefi",
            "state": state, "goals": [], "steps": [], "outputs": {},
            "created": time.time(), "updated": time.time(),
        }
        job.update(extra)
        goal_executor._save(job)
        return job

    def turn(self, text):
        rid = "rel-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı")
            with patch.object(brain_precedence, "claim", return_value=None):
                out, feedback, _ = brain_entry.handoff(self.ctx, entry, self.ctx.handle, text)
        return entry, out, feedback

    def ask(self, text="aç"):
        entry, out, feedback = self.turn(text)
        self.assertIn("Neyi", out)
        return self.ctx._session()

    def test_foreground_clarify_cancel_is_not_goal_cancel(self):
        for token in ("iptal", "vazgeç", "boşver"):
            with self.subTest(token=token):
                self.goal(state="running")
                session = self.ask("aç")
                self.assertIsNotNone(session.pending_action)
                entry, out, feedback = self.turn(token)
                self.assertTrue(entry.state_gate.matched)
                self.assertEqual(entry.state_gate.protocol, "session.pending_action.clarify_cancel")
                self.assertEqual(goal_executor.latest(self.owner)["state"], "running")
                self.assertIsNone(session.pending_action)
                self.ctx.system_control.open_application.assert_not_called()
                self.assertIn("iptal", out)
                self.assertFalse(awaiting_input(session))
        self.run_goal.assert_not_called()

    def test_foreground_close_confirmation_is_not_goal_approval(self):
        self.goal(state="approval", steps=[{"id": "s1", "tool": "manual"}], waiting="s1")
        session = self.ask("kapat")
        self.ctx.system_control.close_application = Mock(
            return_value=ApplicationResult("Chrome pencerelerinin kapandığını doğruladım.", ok=True))
        entry, out, _ = self.turn("Chrome")
        self.assertIs(entry.understanding.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)
        self.assertEqual(session.pending_confirm, {"action": "close_app", "name": "Chrome"})

        entry, out, feedback = self.turn("evet")
        self.assertTrue(entry.state_gate.matched)
        self.assertEqual(entry.state_gate.protocol, "session.pending_confirm.confirm")
        self.ctx.system_control.close_application.assert_called_once_with("Chrome")
        self.run_goal.assert_not_called()
        self.assertEqual(goal_executor.latest(self.owner)["state"], "approval")
        self.assertIsNone(session.pending_confirm)
        self.assertFalse(awaiting_input(session))
        self.assertEqual(out, "Chrome pencerelerinin kapandığını doğruladım.")
        self.ctx.chat.assert_not_called()

    def test_explicit_goal_controls_keep_their_state(self):
        self.goal(state="running")
        session = self.ask("aç")
        entry, out, _ = self.turn("hedef iptal")
        self.assertEqual(entry.state_gate.protocol, "goal.cancel")
        self.assertEqual(goal_executor.latest(self.owner)["state"], "cancelled")
        self.assertIsNone(session.pending_action)
        self.ctx.system_control.open_application.assert_not_called()
        self.ctx.chat.assert_not_called()
        self.run_goal.assert_not_called()

        self.goal(state="running")
        self.ask("aç")
        entry, out, _ = self.turn("hedef devam")
        self.assertEqual(entry.state_gate.protocol, "goal.resume")
        self.run_goal.assert_called_once()

        self.goal(state="approval", steps=[{"id": "s1", "tool": "manual"}], waiting="s1")
        self.ask("aç")
        entry, out, _ = self.turn("hedef onayla")
        self.assertEqual(entry.state_gate.protocol, "goal.approval")
        self.assertEqual(self.run_goal.call_count, 2)

    def test_two_equal_priority_foreground_states_fail_closed(self):
        session = self.ctx._session()
        session.pending_confirm = {"action": "close_app", "name": "Chrome"}
        session.pending_msg = {"to": "Ali", "text": "Selam", "stage": "confirm"}
        self.ctx.system_control.close_application = Mock()
        entry, out, feedback = self.turn("evet")
        self.assertFalse(entry.state_gate.matched)
        self.assertEqual(entry.state_gate.reason_code, "MULTIPLE_BOUNDED_STATE_MATCHES")
        self.assertIn("Birden fazla", out)
        self.assertEqual(feedback.result_status, "needs_input")
        self.ctx.system_control.close_application.assert_not_called()
        self.assertEqual(session.pending_confirm, {"action": "close_app", "name": "Chrome"})
        self.assertEqual(session.pending_msg["stage"], "confirm")

    def test_foreground_photo_cancel_is_not_goal_cancel(self):
        session = self.ctx._session()
        self.ctx._pending_photo[self.owner] = {"path": "C:/photo.jpg", "t": time.time()}
        self.goal(state="running")
        entry, out, _ = self.turn("iptal")
        self.assertEqual(entry.state_gate.protocol, "phone_photo.cancel")
        self.assertEqual(goal_executor.latest(self.owner)["state"], "running")
        self.assertNotIn(self.owner, self.ctx._pending_photo)
        self.assertIn("fotoğraf", out)
        self.run_goal.assert_not_called()

    def test_open_message_cancel_is_not_goal_cancel(self):
        session = self.ctx._session()
        session.pending_msg = {"to": "Ebru", "text": "", "stage": "text"}
        self.goal(state="running")
        entry, out, _ = self.turn("iptal")
        self.assertEqual(entry.state_gate.protocol, "session.pending_msg.cancel")
        self.assertEqual(goal_executor.latest(self.owner)["state"], "running")
        self.assertIsNone(session.pending_msg)
        self.assertEqual(out, "Tamam, mesajı göndermedim.")
        self.run_goal.assert_not_called()

    def test_open_weather_question_is_not_reclaimed_as_goal_cancel(self):
        session = self.ctx._session()
        session.pending_weather_location = True
        self.goal(state="running")
        entry, out, _ = self.turn("boşver")
        self.assertFalse(entry.state_gate.matched)
        self.assertEqual(goal_executor.latest(self.owner)["state"], "running")
        self.run_goal.assert_not_called()
        self.ctx.chat.assert_not_called()

    def test_open_visual_question_does_not_steal_another_owner(self):
        session = self.ctx._session()
        session.pending_visual = {"text": "zihin haritası", "kind": "mindmap", "stage": "source"}
        session.pending_msg = {"to": "Ebru", "text": "", "stage": "text"}
        self.goal(state="running")
        entry, out, _ = self.turn("iptal")
        self.assertEqual(entry.state_gate.protocol, "session.pending_msg.cancel")
        self.assertIsNone(session.pending_msg)
        self.assertEqual(out, "Tamam, mesajı göndermedim.")
        self.assertIsNotNone(session.pending_visual)
        self.assertEqual(goal_executor.latest(self.owner)["state"], "running")
        self.run_goal.assert_not_called()

    def test_open_message_field_does_not_swallow_a_final_confirmation(self):
        session = self.ctx._session()
        session.pending_msg = {"to": "Ebru", "text": "", "stage": "text"}
        session.pending_confirm = {"action": "close_app", "name": "Chrome"}
        self.ctx.system_control.close_application = Mock(
            return_value=ApplicationResult("Chrome pencerelerinin kapandığını doğruladım.", ok=True))
        entry, out, _ = self.turn("evet")
        self.assertEqual(entry.state_gate.protocol, "session.pending_confirm.confirm")
        self.ctx.system_control.close_application.assert_called_once_with("Chrome")
        self.assertEqual(session.pending_msg, {"to": "Ebru", "text": "", "stage": "text"})
        self.assertIsNone(session.pending_confirm)
        self.assertEqual(out, "Chrome pencerelerinin kapandığını doğruladım.")

    def test_canonical_final_confirmation_is_not_remapped_to_desktop_consent(self):
        session = self.ctx._session()
        session.pending_desktop = True
        session.pending_confirm = {"action": "close_app", "name": "Chrome"}
        self.ctx.system_control.close_application = Mock(
            return_value=ApplicationResult("Chrome pencerelerinin kapandığını doğruladım.", ok=True))
        with patch.object(desktop_agent, "consent_reply", return_value="PC izin ver") as consent:
            entry, out, _ = self.turn("evet")
        self.assertEqual(entry.state_gate.protocol, "session.pending_confirm.confirm")
        consent.assert_not_called()
        self.ctx.system_control.close_application.assert_called_once_with("Chrome")
        self.assertEqual(out, "Chrome pencerelerinin kapandığını doğruladım.")


class BoundedJobLegacyGuardTests(unittest.TestCase):
    def test_canonical_non_job_state_cannot_be_reclaimed_by_job_route(self):
        active = ActiveContext(owner="alice", request_id="rel-guard")
        def entry(protocol: str, reason: str):
            return brain_entry.EntryResult(
                "alice", "rel-guard", "yazı", "iptal", active,
                GateObservation("alice", "rel-guard", "state", True, reason, protocol, "cancel"),
            )

        probe = Mock(return_value="JOB")
        saved_route = job_front.route
        saved_flag = getattr(job_front, "_brain_gate_guard_installed", False)
        saved_legacy = getattr(job_front, "_brain_legacy_route", None)
        job_front.route = probe
        job_front._brain_gate_guard_installed = False
        try:
            brain_entry._install_job_guard()
            guarded = job_front.route
            with brain_entry.bind(entry("session.pending_confirm.confirm", "BOUNDED_FINAL_CONFIRM")):
                self.assertIsNone(guarded("alice", lambda *a: None, "iptal", SimpleNamespace()))
            with brain_entry.bind(entry("job.cancel", "BOUNDED_JOB_CANCEL")):
                self.assertEqual(guarded("alice", lambda *a: None, "iptal", SimpleNamespace()), "JOB")
            self.assertEqual(probe.call_count, 1)
        finally:
            job_front.route = saved_route
            job_front._brain_gate_guard_installed = saved_flag
            job_front._brain_legacy_route = saved_legacy


class StateAuthorityArchitectureGuardTests(unittest.TestCase):
    def test_goal_legacy_bare_rebinding_is_fenced_before_it_can_mutate_state(self):
        tree = ast.parse(Path(goal_executor.__file__).read_text(encoding="utf-8-sig"))
        handle = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.FunctionDef) and node.name == "handle")

        def is_fence_call(node):
            return (isinstance(node, ast.Call)
                    and ((isinstance(node.func, ast.Attribute) and node.func.attr == "allow_legacy_goal_control")
                         or (isinstance(node.func, ast.Name) and node.func.id == "allow_legacy_goal_control")))

        fences = [
            node.lineno for node in ast.walk(handle)
            if isinstance(node, ast.If) and any(is_fence_call(child) for child in ast.walk(node.test))
            and any(isinstance(child, ast.Return) for child in node.body)
        ]
        rebinding = [
            node.lineno for node in ast.walk(handle)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "low" for target in node.targets)
            and isinstance(node.value, ast.Constant)
            and node.value.value in {"hedef onayla", "hedef iptal"}
        ]
        self.assertTrue(fences, "Goal çıplak token çevirimi canonical kapıyla çitlenmeli.")
        self.assertTrue(rebinding)
        self.assertLess(min(fences), min(rebinding))

    def test_open_message_field_is_fenced_by_canonical_ownership(self):
        tree = ast.parse(Path(engine_commands.__file__).read_text(encoding="utf-8-sig"))
        handle = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.FunctionDef) and node.name == "handle")

        def is_pending_msg_test(node):
            return (isinstance(node, ast.Compare)
                    and isinstance(node.left, ast.Attribute) and node.left.attr == "pending_msg")

        branches = [node for node in ast.walk(handle)
                    if isinstance(node, ast.If) and is_pending_msg_test(node.test)]
        self.assertTrue(branches, "Açık pending_msg dalı bulunmalı.")
        branch = branches[0]
        calls = [node for node in ast.walk(branch) if isinstance(node, ast.Call)]
        providers = [node for node in calls
                     if isinstance(node.func, ast.Attribute) and node.func.attr == "state_protocol"]
        steps = [node for node in calls
                 if isinstance(node.func, ast.Attribute) and node.func.attr == "_message_step"]
        self.assertTrue(providers, "Mesaj alanı canonical sahiplik kaynağıyla çitlenmeli.")
        self.assertTrue(steps)
        self.assertLess(min(node.lineno for node in providers),
                        min(node.lineno for node in steps))
        fenced = [
            node for node in ast.walk(branch)
            if isinstance(node, ast.If)
            and any(isinstance(child, ast.Name) and child.id == "owned" for child in ast.walk(node.test))
            and any(isinstance(child, ast.Attribute) and child.attr == "_message_step"
                    for child in ast.walk(node))
        ]
        self.assertTrue(fenced, "_message_step canonical sahiplik seçimine bağlı çitte çalışmalı.")


if __name__ == "__main__":
    unittest.main()
