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
import test_brain_production_entry as fixtures
from modules import app_actions, brain_core_map, brain_context, brain_entry, brain_precedence, desktop_agent
from modules import brain_understanding, engine_commands, engine_runtime, goal_executor, job_front, requests_state
from modules import history as history_mod
from modules import command_manager, main_planner, messaging, nxapi, personalization, visual_chat, visual_commands
from modules.brain_contracts import ActiveContext, ConversationRelation, RequestKind
from modules.brain_gates import GateObservation
from modules.command_manager import awaiting_input
from modules.system_control import APPS as STATIC_APPS
from modules.system_control import ApplicationResult


def _isolate_profiles(case, root: Path) -> None:
    """Profile dosyaları gerçek kullanıcı klasöründe değil, testin geçici kökünde tutulur.

    `EngineContext` canlı `~/.jarvis/users` altındaki profili okumamalı; başka bir testin
    bıraktığı gerçek takvim/not kaydı test sonucunu değiştiremez."""
    users = root / "users"
    users.mkdir(exist_ok=True)
    for target, attr, value in ((personalization, "USERS_DIR", users),
                                (personalization, "ACTIVE_FILE", root / "active_user.txt")):
        state_patch = patch.object(target, attr, value)
        state_patch.start()
        case.addCleanup(state_patch.stop)



class RelationAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        _isolate_profiles(self, Path(self.temp.name))
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
        _isolate_profiles(self, Path(self.temp.name))
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

    def test_ascii_cancel_reaches_the_weather_question_owner(self):
        session = self.ctx._session()
        session.pending_weather_location = True
        self.ctx._weather = Mock(return_value="HAVA")
        entry, out, _ = self.turn("vazgec")
        self.assertEqual(entry.state_gate.protocol, "session.pending_weather_location.cancel")
        self.ctx._weather.assert_not_called()
        self.assertIs(session.pending_weather_location, False)
        self.assertEqual(out, "Hava durumu aramasını iptal ettim.")

    def test_ascii_cancel_does_not_become_a_message_body(self):
        session = self.ctx._session()
        session.pending_msg = {"to": "Ebru", "text": "", "stage": "text"}
        with patch.object(messaging, "send_whatsapp", Mock()) as sender:
            entry, out, _ = self.turn("vazgec")
        self.assertEqual(entry.state_gate.protocol, "session.pending_msg.cancel")
        sender.assert_not_called()
        self.assertIsNone(session.pending_msg)
        self.assertEqual(out, "Tamam, mesajı göndermedim.")

    def test_ascii_cancel_reaches_the_app_choice_owner(self):
        session = self.ctx._session()
        session.pending_app = {"choices": ["Chrome", "Paint"], "at": time.monotonic()}
        self.ctx.system_control.open_application = Mock()
        entry, out, _ = self.turn("vazgec")
        self.assertEqual(entry.state_gate.protocol, "session.pending_app.cancel")
        self.ctx.system_control.open_application.assert_not_called()
        self.assertIsNone(session.pending_app)
        self.assertEqual(out, "Uygulama seçimini iptal ettim.")

    def test_ascii_cancel_reaches_the_event_title_owner(self):
        from modules import main_planner
        session = self.ctx._session()
        session.pending_event_title = "Toplantı"
        with patch.object(main_planner, "_save_reminder", Mock()) as save:
            entry, out, _ = self.turn("vazgec")
        self.assertEqual(entry.state_gate.protocol, "session.pending_event_title.cancel")
        save.assert_not_called()
        self.assertIsNone(session.pending_event_title)
        self.assertEqual(out, "Tamam, eklemedim.")

    def test_visual_source_inflections_use_the_gate_selection(self):
        fake_result = SimpleNamespace(label="zihin haritası", path="C:/tmp/x.png")
        for answer, expected in (("belgeyi", "Dosyalar sayfasında"), ("konuşmayı", "Zihin haritası")):
            with self.subTest(answer=answer):
                session = self.ctx._session()
                session.pending_visual = {"text": "zihin haritası", "kind": "mindmap", "stage": "source"}
                with patch.object(visual_chat, "_history_text", Mock(return_value="konuşma")), \
                        patch.object(visual_commands, "create_visual", Mock(return_value=fake_result)) as create:
                    entry, out, _ = self.turn(answer)
                self.assertEqual(entry.state_gate.protocol, "session.pending_visual.select")
                self.assertIn(expected, out)
                self.assertNotIn("Sohbetten mi, dosyadan mı", out)
                self.assertIsNone(session.pending_visual)
                if answer == "belgeyi":
                    create.assert_not_called()
                else:
                    create.assert_called_once()

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


class CanonicalTurnOwnerTests(unittest.TestCase):
    def test_state_then_fast_then_none_is_the_single_ownership_view(self):
        active = ActiveContext(owner="alice", request_id="rel-owner")
        state = GateObservation("alice", "rel-owner", "state", True, "BOUNDED_FINAL_CONFIRM",
                                "session.pending_confirm.confirm", "yes")
        fast = GateObservation("alice", "rel-owner", "fast", True, "EXACT_LOCAL_READ", "fast.time.read", "time")
        miss = GateObservation("alice", "rel-owner", "state", False, "NO_BOUNDED_STATE", None, None)

        for state_gate, fast_gate, expected in (
            (state, fast, "session.pending_confirm.confirm"),
            (miss, fast, "fast.time.read"),
            (miss, None, None),
        ):
            with self.subTest(expected=expected):
                entry = brain_entry.EntryResult("alice", "rel-owner", "yazı", "saat kaç", active,
                                                state_gate, fast_gate)
                with brain_entry.bind(entry):
                    self.assertEqual(brain_entry.turn_protocol(), expected)
                    self.assertEqual(brain_entry.protocol_owned_by("fast.time."), expected == "fast.time.read")
                    self.assertEqual(brain_entry.protocol_owned_by("session.pending_confirm."),
                                     expected == "session.pending_confirm.confirm")
        self.assertIsNone(brain_entry.turn_protocol())


class _CanonicalTurnHarness(unittest.TestCase):
    """Üretim hattı: `prepare → handoff → ctx.handle`.

    Bekleyen state'ler geçici EngineContext oturumunda kurulur; canlı kullanıcı klasörü okunmaz,
    kişisel Goal kaydı kullanılmaz/silinmez.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        _isolate_profiles(self, Path(self.temp.name))
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
        self.ctx.desktop = Mock(system_status=Mock(return_value="SISTEM"))
        self.ctx._weather = Mock(return_value="HAVA")
        self.message_step = Mock(wraps=self.ctx._message_step)
        self.ctx._message_step = self.message_step
        # Mesaj gönderimi arka plan iş parçacığında çalışır; test effect'i başlatmaz.
        self.ctx.threading = Mock()

        goals = Path(self.temp.name) / "goals"
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
            out, _, _ = brain_entry.handoff(self.ctx, entry, self.ctx.handle, text)
        return entry, out


class FastTurnOwnershipTests(_CanonicalTurnHarness):
    """Canonical Fast Gate bir turn'ün sahibiyse legacy pending tüketicisi ham metni yeniden yorumlamaz."""

    def assert_fast_clock_turn(self, entry, out):
        self.assertEqual(entry.stage, "fast")
        self.assertTrue(entry.fast_gate.matched)
        self.assertEqual(entry.fast_gate.protocol, "fast.time.read")
        self.assertTrue(str(out).startswith("Saat "), out)

    def test_open_message_field_cannot_consume_a_fast_clock_turn(self):
        session = self.ctx._session()
        session.pending_msg = {"to": "Ebru", "text": "", "stage": "text"}
        with patch.object(messaging, "send_whatsapp", Mock()) as sender:
            entry, out = self.turn("saat kaç")
            self.assert_fast_clock_turn(entry, out)
            sender.assert_not_called()
        self.assertEqual(session.pending_msg, {"to": "Ebru", "text": "", "stage": "text"})
        self.assertNotIn("göndereyim mi", out)
        self.message_step.assert_not_called()

    def test_open_visual_source_question_cannot_consume_a_fast_clock_turn(self):
        session = self.ctx._session()
        session.pending_visual = {"text": "zihin haritası", "kind": "mindmap", "stage": "source"}
        with patch.object(visual_commands, "create_visual", Mock()) as create:
            entry, out = self.turn("saat kaç")
            self.assert_fast_clock_turn(entry, out)
            create.assert_not_called()
        self.assertNotIn("Sohbetten mi, dosyadan mı", out)
        self.assertEqual(session.pending_visual,
                         {"text": "zihin haritası", "kind": "mindmap", "stage": "source"})

    def test_open_weather_question_cannot_consume_a_fast_clock_turn(self):
        session = self.ctx._session()
        session.pending_weather_location = True
        entry, out = self.turn("saat kaç")
        self.assert_fast_clock_turn(entry, out)
        self.ctx._weather.assert_not_called()
        self.assertIs(session.pending_weather_location, True)

    def test_fast_turn_owns_neither_of_two_open_slots(self):
        session = self.ctx._session()
        session.pending_msg = {"to": "Ebru", "text": "", "stage": "text"}
        session.pending_weather_location = True
        entry, out = self.turn("saat kaç")
        self.assert_fast_clock_turn(entry, out)
        self.assertIsNone(entry.understanding)
        with brain_entry.bind(entry):
            self.assertFalse(brain_entry.pending_answer_owned("pending_msg"))
            self.assertFalse(brain_entry.pending_answer_owned("pending_weather_location"))
        self.message_step.assert_not_called()
        self.ctx._weather.assert_not_called()
        self.assertEqual(session.pending_msg, {"to": "Ebru", "text": "", "stage": "text"})
        self.assertIs(session.pending_weather_location, True)

    def test_fast_ownership_is_generic_across_date_and_status(self):
        cases = (("tarih", "fast.date.read", "Bugün "),
                 ("sistem durumu", "fast.system.status", "SISTEM"))
        for text, protocol, expected in cases:
            with self.subTest(text=text):
                session = self.ctx._session()
                session.pending_msg = {"to": "Ebru", "text": "", "stage": "text"}
                entry, out = self.turn(text)
                self.assertEqual(entry.stage, "fast")
                self.assertEqual(entry.fast_gate.protocol, protocol)
                self.assertTrue(str(out).startswith(expected), out)
                self.assertEqual(session.pending_msg, {"to": "Ebru", "text": "", "stage": "text"})

    def test_open_confirmation_is_preserved_not_consumed_by_a_fast_turn(self):
        session = self.ctx._session()
        pending = {"action": "close_app", "name": "Chrome"}
        session.pending_confirm = dict(pending)
        self.ctx.system_control.close_application = Mock()
        entry, out = self.turn("saat kaç")
        self.assert_fast_clock_turn(entry, out)
        self.ctx.system_control.close_application.assert_not_called()
        self.assertEqual(session.pending_confirm, pending)

    def test_open_level_question_is_preserved_not_consumed_by_a_fast_turn(self):
        session = self.ctx._session()
        session.pending_level = 70
        self.ctx.system_control.set_volume = Mock()
        entry, out = self.turn("saat kaç")
        self.assert_fast_clock_turn(entry, out)
        self.ctx.system_control.set_volume.assert_not_called()
        self.assertEqual(session.pending_level, 70)

    def test_open_organize_confirmation_is_preserved_not_consumed_by_a_fast_turn(self):
        session = self.ctx._session()
        pending = {"label": "İndirilenler", "plan": []}
        session.pending_organize = dict(pending)
        with patch.object(self.ctx.files, "apply_organize") as organize:
            entry, out = self.turn("saat kaç")
        self.assert_fast_clock_turn(entry, out)
        organize.assert_not_called()
        self.assertEqual(session.pending_organize, pending)

    def test_open_event_title_question_is_preserved_not_consumed_by_a_fast_turn(self):
        session = self.ctx._session()
        session.pending_event_title = "Toplantı"
        entry, out = self.turn("saat kaç")
        self.assert_fast_clock_turn(entry, out)
        self.assertEqual(session.pending_event_title, "Toplantı")

    def test_open_app_choice_is_preserved_not_consumed_by_a_fast_turn(self):
        session = self.ctx._session()
        pending = {"choices": ["Chrome", "Edge"], "at": time.monotonic()}
        session.pending_app = dict(pending)
        self.ctx.system_control.open_application = Mock()
        entry, out = self.turn("saat kaç")
        self.assert_fast_clock_turn(entry, out)
        self.ctx.system_control.open_application.assert_not_called()
        self.assertEqual(session.pending_app, pending)

    def test_open_action_offer_is_preserved_not_consumed_by_a_fast_turn(self):
        session = self.ctx._session()
        pending = {"action": "app_open", "params": {"name": "Chrome"}, "owner": self.owner,
                   "expires": time.time() + 60}
        session.pending_action = dict(pending)
        entry, out = self.turn("saat kaç")
        self.assert_fast_clock_turn(entry, out)
        self.assertEqual(session.pending_action, pending)

    def test_desktop_consent_is_not_remapped_from_fast_text(self):
        session = self.ctx._session()
        session.pending_desktop = True
        consent = Mock(return_value="PC izin ver")
        with patch.object(desktop_agent, "consent_reply", consent), \
                patch.object(desktop_agent, "handle", Mock(return_value=None)):
            entry, out = self.turn("saat kaç")
        self.assert_fast_clock_turn(entry, out)
        consent.assert_not_called()

    def test_goal_open_question_is_not_resumed_by_fast_text(self):
        self.goal(state="question", question="Hangi şehir için?")
        session = self.ctx._session()
        session.pending_msg = {"to": "Ebru", "text": "", "stage": "text"}
        entry, out = self.turn("saat kaç")
        self.assert_fast_clock_turn(entry, out)
        self.run_goal.assert_not_called()
        self.assertEqual(goal_executor.latest(self.owner)["state"], "question")
        self.assertEqual(session.pending_msg, {"to": "Ebru", "text": "", "stage": "text"})

    def test_job_route_is_not_invoked_for_fast_text(self):
        session = self.ctx._session()
        session.pending_msg = {"to": "Ebru", "text": "", "stage": "text"}
        route = Mock(return_value="JOB")
        with patch.object(job_front, "route", route):
            entry, out = self.turn("saat kaç")
        self.assert_fast_clock_turn(entry, out)
        route.assert_not_called()

    def test_open_message_flow_still_reaches_the_message_owner(self):
        session = self.ctx._session()
        session.pending_msg = {"to": "", "text": "", "stage": "to"}
        self.message_step = Mock(wraps=self.ctx._message_step)
        self.ctx._message_step = self.message_step

        entry, out = self.turn("Ebru")
        self.assertFalse(entry.fast_gate.matched)
        self.assertEqual(out, "Ebru kişisine ne yazayım?")
        self.assertEqual(session.pending_msg, {"to": "Ebru", "text": "", "stage": "text"})

        entry, out = self.turn("Yarın geliyorum")
        self.assertEqual(out, "Ebru kişisine şunu göndereyim mi: “Yarın geliyorum”? Evet ya da hayır de.")

        entry, out = self.turn("evet")
        self.assertEqual(entry.state_gate.protocol, "session.pending_msg.confirm")
        self.assertIn("gönderiyorum", out)
        self.assertIsNone(session.pending_msg)

    def test_visual_source_answer_still_reaches_the_visual_owner(self):
        session = self.ctx._session()
        session.pending_visual = {"text": "zihin haritası", "kind": "mindmap", "stage": "source"}
        result = SimpleNamespace(label="Görsel", path="C:/jarvis/gorsel.png")
        with patch.object(history_mod, "read", Mock(return_value=[{"text": "eski konuşma"}])), \
                patch.object(visual_commands, "create_visual", Mock(return_value=result)) as create:
            entry, out = self.turn("sohbet")
        self.assertEqual(entry.state_gate.protocol, "session.pending_visual.select")
        create.assert_called_once()
        self.assertIn("hazır", out)
        self.assertIsNone(session.pending_visual)

    def test_weather_location_answer_still_reaches_the_weather_owner(self):
        session = self.ctx._session()
        session.pending_weather_location = True
        entry, out = self.turn("İstanbul")
        self.assertFalse(entry.fast_gate.matched)
        self.ctx._weather.assert_called_once_with("İstanbul")
        self.assertEqual(out, "HAVA")
        self.assertIs(session.pending_weather_location, False)


class PlanEligibilityTests(_CanonicalTurnHarness):
    """Pending slot varlığı relation authority değildir.

    Canonical Understanding NEW_REQUEST + CAPABILITY dediğinde, başka bir açık pending state'in
    yalnızca varlığı Core planını veto edemez ve istek sessizce chat'e dönüşemez. Üretim hattı
    (`prepare → handoff → ctx.handle`) kullanılır; state'ler geçici oturumda kurulur.
    """

    def assert_notes_capability(self, entry, out):
        self.assertEqual(entry.understanding.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(entry.understanding.conversation_relation, ConversationRelation.NEW_REQUEST)
        self.assertEqual(entry.understanding.capability_hint, "notes.read")
        self.assertEqual(out, self.ctx._notes_text())
        self.ctx.chat.assert_not_called()

    def test_message_draft_cannot_veto_an_independent_notes_request(self):
        session = self.ctx._session()
        pending = {"to": "Ebru", "text": "", "stage": "text"}
        session.pending_msg = dict(pending)
        with patch.object(messaging, "send_whatsapp", Mock()) as sender:
            entry, out = self.turn("notlarımı göster")
            sender.assert_not_called()
        self.assert_notes_capability(entry, out)
        self.message_step.assert_not_called()
        self.assertEqual(session.pending_msg, pending)
        self.assertIsNone(entry.understanding.pending_owner)

    def test_pending_confirmation_cannot_veto_notes_and_is_not_consumed(self):
        session = self.ctx._session()
        pending = {"action": "close_app", "name": "Chrome"}
        session.pending_confirm = dict(pending)
        close = Mock(return_value=ApplicationResult("kapandı", ok=True))
        self.ctx.system_control.close_application = close
        entry, out = self.turn("notlarımı göster")
        self.assert_notes_capability(entry, out)
        close.assert_not_called()
        self.assertEqual(session.pending_confirm, pending)

    def test_open_weather_question_cannot_veto_notes(self):
        session = self.ctx._session()
        session.pending_weather_location = True
        entry, out = self.turn("notlarımı göster")
        self.assert_notes_capability(entry, out)
        self.ctx._weather.assert_not_called()
        self.assertIs(session.pending_weather_location, True)

    def test_open_visual_question_cannot_veto_notes(self):
        session = self.ctx._session()
        pending = {"text": "zihin haritası", "kind": "mindmap", "stage": "source"}
        session.pending_visual = dict(pending)
        with patch.object(visual_commands, "create_visual", Mock()) as create:
            entry, out = self.turn("notlarımı göster")
            create.assert_not_called()
        self.assert_notes_capability(entry, out)
        self.assertNotIn("Sohbetten mi, dosyadan mı", out)
        self.assertEqual(session.pending_visual, pending)

    def test_open_organize_confirmation_cannot_veto_notes(self):
        session = self.ctx._session()
        pending = {"label": "İndirilenler", "plan": []}
        session.pending_organize = dict(pending)
        with patch.object(self.ctx.files, "apply_organize") as organize:
            entry, out = self.turn("notlarımı göster")
            organize.assert_not_called()
        self.assert_notes_capability(entry, out)
        self.assertEqual(session.pending_organize, pending)

    def test_open_pending_does_not_veto_other_canonical_capability_classes(self):
        self.ctx.system_control.set_volume = Mock(return_value=True)
        cases = (
            ("hava nasıl", lambda: self.ctx._weather.assert_called_once_with(None)),
            ("sesi 50 yap", lambda: self.ctx.system_control.set_volume.assert_called_once_with(50)),
        )
        for text, verify in cases:
            with self.subTest(text=text):
                session = self.ctx._session()
                session.pending_msg = {"to": "Ebru", "text": "", "stage": "text"}
                self.ctx.chat.reset_mock()
                entry, out = self.turn(text)
                self.assertEqual(entry.understanding.request_kind, RequestKind.CAPABILITY)
                self.assertEqual(entry.understanding.conversation_relation, ConversationRelation.NEW_REQUEST)
                self.ctx.chat.assert_not_called()
                self.message_step.assert_not_called()
                self.assertEqual(session.pending_msg, {"to": "Ebru", "text": "", "stage": "text"})
                verify()

    def test_weather_status_phrase_is_canonical_capability_not_a_pending_answer(self):
        # Ayrım özel bir pending-owner regex'inden değil, Understanding'in canonical capability
        # kararından gelir; "hava durumuna bak" açık taslağın cevabı değildir.
        session = self.ctx._session()
        pending = {"to": "Ebru", "text": "", "stage": "text"}
        session.pending_msg = dict(pending)
        entry, out = self.turn("hava durumuna bak")
        self.assertEqual(entry.understanding.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(entry.understanding.conversation_relation, ConversationRelation.NEW_REQUEST)
        self.assertIsNone(entry.understanding.pending_owner)
        self.ctx._weather.assert_called_once_with(None)
        self.assertEqual(out, "HAVA")
        self.message_step.assert_not_called()
        self.assertEqual(session.pending_msg, pending)

    def test_screenshot_phrase_is_canonical_capability_not_a_pending_answer(self):
        session = self.ctx._session()
        pending = {"to": "Ebru", "text": "", "stage": "text"}
        session.pending_msg = dict(pending)
        self.ctx.desktop.screenshot = Mock(return_value="EKRAN")
        entry, out = self.turn("ekran görüntüsü al")
        self.assertEqual(entry.understanding.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(entry.understanding.conversation_relation, ConversationRelation.NEW_REQUEST)
        self.assertIsNone(entry.understanding.pending_owner)
        self.ctx.desktop.screenshot.assert_called_once()
        self.assertEqual(out, "EKRAN")
        self.message_step.assert_not_called()
        self.ctx.chat.assert_not_called()
        self.assertEqual(session.pending_msg, pending)

    def test_new_request_chat_is_not_turned_into_a_pending_answer(self):
        session = self.ctx._session()
        session.pending_msg = {"to": "Ebru", "text": "", "stage": "text"}
        entry, out = self.turn("merhaba")
        self.assertEqual(entry.understanding.request_kind, RequestKind.CHAT)
        self.assertEqual(entry.understanding.conversation_relation, ConversationRelation.NEW_REQUEST)
        self.assertEqual(out, "CHAT")
        self.message_step.assert_not_called()
        self.assertEqual(session.pending_msg, {"to": "Ebru", "text": "", "stage": "text"})

    def test_context_control_is_not_executed_as_a_pending_answer_or_capability(self):
        session = self.ctx._session()
        session.pending_weather_location = True
        entry, out = self.turn("boşver")
        self.assertEqual(entry.understanding.request_kind, RequestKind.CONTEXT_CONTROL)
        self.message_step.assert_not_called()
        self.ctx._weather.assert_not_called()
        self.ctx.chat.assert_not_called()
        self.assertIs(session.pending_weather_location, True)
        self.assertIn("Tamam", out)

    def test_multi_step_request_with_a_draft_open_is_refused_without_partial_effect(self):
        session = self.ctx._session()
        pending = {"to": "Ebru", "text": "", "stage": "text"}
        session.pending_msg = dict(pending)
        self.ctx._notes_text = Mock(return_value="NOTLARIM")
        self.ctx.system_control.set_volume = Mock(return_value=True)
        entry, out = self.turn("önce notlarımı göster sonra sesi 50 yap")
        self.assertEqual(entry.understanding.conversation_relation, ConversationRelation.NEW_REQUEST)
        # Adım sahibi çiti korunur: cümle sohbete çevrilmez, ama açık alan varken adım zinciri
        # başlamaz ve ham cümle tek bir adımı kısmen çalıştırmaz.
        self.ctx._notes_text.assert_not_called()
        self.ctx.system_control.set_volume.assert_not_called()
        self.message_step.assert_not_called()
        self.ctx.chat.assert_not_called()
        self.assertIn("çok adımlı komutu başlatmadım", out)
        self.assertEqual(session.pending_msg, pending)

    def test_level_answer_variants_still_reach_the_level_owner(self):
        session = self.ctx._session()
        session.pending_level = 70
        self.ctx.system_control.set_volume = Mock(return_value=True)
        entry, out = self.turn("sesi")
        self.assertEqual(entry.state_gate.protocol, "session.pending_level.select")
        self.ctx.system_control.set_volume.assert_called_once_with(70)
        self.assertIsNone(session.pending_level)

    def test_visual_source_answer_variants_still_reach_the_visual_owner(self):
        session = self.ctx._session()
        session.pending_visual = {"text": "zihin haritası", "kind": "mindmap", "stage": "source"}
        result = SimpleNamespace(label="Görsel", path="C:/jarvis/gorsel.png")
        with patch.object(history_mod, "read", Mock(return_value=[{"text": "eski konuşma"}])), \
                patch.object(visual_commands, "create_visual", Mock(return_value=result)) as create:
            entry, out = self.turn("sohbetten")
        self.assertEqual(entry.state_gate.protocol, "session.pending_visual.select")
        create.assert_called_once()
        self.assertIn("hazır", out)
        self.assertIsNone(session.pending_visual)

    def test_weather_question_cancel_still_closes_the_question(self):
        session = self.ctx._session()
        session.pending_weather_location = True
        entry, out = self.turn("iptal")
        self.assertEqual(entry.state_gate.protocol, "session.pending_weather_location.cancel")
        self.assertIn("iptal ettim", out)
        self.assertIs(session.pending_weather_location, False)

    def test_reminder_when_answer_still_completes_the_open_event_title(self):
        session = self.ctx._session()
        session.pending_event_title = "ilaç"
        entry, out = self.turn("yarın 10'da")
        self.assertEqual(entry.state_gate.protocol, "session.pending_event_title.answer")
        self.assertTrue(str(out).startswith("Takvime ekledim: ilaç"), out)
        self.assertIsNone(session.pending_event_title)
        self.assertEqual([event["title"] for event in self.ctx.profile.data["events"]], ["ilaç"])

    def test_open_event_title_cannot_capture_an_independent_weather_request(self):
        session = self.ctx._session()
        session.pending_event_title = "ilaç"
        entry, out = self.turn("hava nasıl")
        self.assertTrue(str(entry.understanding.capability_hint).startswith("weather.read"))
        self.ctx._weather.assert_called_once_with(None)
        self.assertEqual(out, "HAVA")
        self.assertEqual(session.pending_event_title, "ilaç")


class PendingAnswerOwnershipTests(unittest.TestCase):
    """Consumer fence contract: a slot owns a turn only when the canonical chain says so."""

    def owned(self, entry, field):
        with brain_entry.bind(entry):
            return brain_entry.pending_answer_owned(field)

    FIELDS = ("pending_msg", "pending_confirm", "pending_level", "pending_weather_location",
              "pending_visual", "pending_organize", "pending_event_title", "pending_action")

    def test_unbound_consumer_keeps_its_legacy_behavior(self):
        self.assertTrue(brain_entry.pending_answer_owned("pending_msg"))

    def test_new_request_capability_is_not_any_pending_answer(self):
        entry = fixtures.entry(
            brain_entry,
            semantic=fixtures.understanding(kind=RequestKind.CAPABILITY, hint="notes.read"),
        )
        for field in self.FIELDS:
            self.assertFalse(self.owned(entry, field), field)

    def test_answer_to_pending_owns_only_the_selected_canonical_owner(self):
        cases = (
            ("session.pending_weather_location", "pending_weather_location"),
            ("session.pending_msg.to", "pending_msg"),
            ("session.pending_msg.text", "pending_msg"),
            ("session.pending_action.clarify", "pending_action"),
        )
        for owner, owner_field in cases:
            with self.subTest(owner=owner):
                entry = fixtures.entry(
                    brain_entry,
                    semantic=fixtures.understanding(kind=RequestKind.CHAT,
                                                    relation=ConversationRelation.ANSWER_TO_PENDING,
                                                    pending_owner=owner),
                )
                for field in self.FIELDS:
                    self.assertEqual(self.owned(entry, field), field == owner_field,
                                     (owner, field))

    def test_answer_to_pending_without_a_single_owner_owns_no_field(self):
        entry = fixtures.entry(
            brain_entry,
            semantic=fixtures.understanding(kind=RequestKind.CHAT,
                                            relation=ConversationRelation.ANSWER_TO_PENDING,
                                            needs_input=True,
                                            ambiguities=("MULTIPLE_PENDING_ANSWER_OWNERS",)),
        )
        for field in self.FIELDS:
            self.assertFalse(self.owned(entry, field), field)

    def test_fast_turn_owns_no_pending_field(self):
        entry = fixtures.entry(
            brain_entry,
            semantic=fixtures.understanding(kind=RequestKind.CAPABILITY, hint="notes.read"),
            fast=GateObservation(fixtures.OWNER, fixtures.RID, "fast", True, "EXACT",
                                 protocol="fast.time.read", selection="time"),
        )
        for field in self.FIELDS:
            self.assertFalse(self.owned(entry, field), field)

    def test_state_protocol_owns_only_its_own_field(self):
        entry = fixtures.entry(
            brain_entry,
            semantic=fixtures.understanding(kind=RequestKind.CHAT),
            state=GateObservation(fixtures.OWNER, fixtures.RID, "state", True,
                                  "BOUNDED_MESSAGE_CONFIRM", protocol="session.pending_msg.confirm",
                                  selection="yes"),
        )
        self.assertTrue(self.owned(entry, "pending_msg"))
        self.assertFalse(self.owned(entry, "pending_confirm"))
        desktop = fixtures.entry(
            brain_entry,
            semantic=fixtures.understanding(kind=RequestKind.CHAT),
            state=GateObservation(fixtures.OWNER, fixtures.RID, "state", True,
                                  "BOUNDED_DESKTOP_CONSENT", protocol="desktop.consent",
                                  selection="yes"),
        )
        self.assertTrue(self.owned(desktop, "pending_desktop"))
        self.assertFalse(self.owned(desktop, "pending_msg"))


class PendingOwnerSelectionTests(_CanonicalTurnHarness):
    """ANSWER_TO_PENDING tek canonical pending owner taşır; iki slot aynı ham metni sahiplenemez.

    Üretim hattı: `prepare → handoff → ctx.handle`. Owner seçimi consumer sırasına değil,
    Understanding'in kanıt/özgüllük kararına bağlıdır.
    """

    WEATHER_OWNER = "session.pending_weather_location"
    MESSAGE_TO_OWNER = "session.pending_msg.to"
    MESSAGE_TEXT_OWNER = "session.pending_msg.text"
    APP_CLARIFY_OWNER = "session.pending_action.clarify"
    AMBIGUOUS = "MULTIPLE_PENDING_ANSWER_OWNERS"

    def open_slots(self, stage: str):
        session = self.ctx._session()
        pending = {"to": "" if stage == "to" else "Ebru", "text": "", "stage": stage}
        session.pending_msg = dict(pending)
        session.pending_weather_location = True
        return session, pending

    def clarify_pending(self):
        return {
            "stage": "clarify", "command": "aç", "question": "Neyi açmamı istiyorsun?",
            "owner": self.owner, "expires": time.time() + 60,
            "proposal": {"kind": "app.open"},
        }

    def test_weather_owner_takes_the_city_and_leaves_the_message_draft_untouched(self):
        session, pending = self.open_slots("text")
        with patch.object(messaging, "send_whatsapp", Mock()) as sender:
            entry, out = self.turn("İstanbul")
            sender.assert_not_called()
        self.assertEqual(entry.understanding.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)
        self.assertEqual(entry.understanding.pending_owner, self.WEATHER_OWNER)
        self.ctx._weather.assert_called_once_with("İstanbul")
        self.message_step.assert_not_called()
        self.assertIs(session.pending_weather_location, False)
        self.assertEqual(session.pending_msg, pending)
        self.assertEqual(out, "HAVA")

    def test_city_that_could_be_a_recipient_fails_closed_without_any_effect(self):
        session, pending = self.open_slots("to")
        with patch.object(messaging, "send_whatsapp", Mock()) as sender:
            entry, out = self.turn("İstanbul")
            sender.assert_not_called()
        self.assertEqual(entry.understanding.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)
        self.assertIsNone(entry.understanding.pending_owner)
        self.assertEqual(entry.understanding.request_kind, RequestKind.CLARIFY)
        self.assertIn(self.AMBIGUOUS, entry.understanding.ambiguities)
        self.assertIn("netleştir", out)
        self.ctx._weather.assert_not_called()
        self.message_step.assert_not_called()
        self.ctx.chat.assert_not_called()
        self.assertIs(session.pending_weather_location, True)
        self.assertEqual(session.pending_msg, pending)

    def test_typed_app_clarify_owner_outranks_an_open_weather_question(self):
        session = self.ctx._session()
        session.pending_action = self.clarify_pending()
        session.pending_weather_location = True
        self.ctx.system_control.open_application = Mock(
            return_value=ApplicationResult("Chrome penceresi açık; açılışını doğruladım.", ok=True))
        with patch.object(brain_precedence, "claim", return_value=None):
            entry, out = self.turn("Chrome")
        self.assertEqual(entry.understanding.pending_owner, self.APP_CLARIFY_OWNER)
        self.assertEqual(entry.understanding.capability_hint, "app.open")
        self.ctx.system_control.open_application.assert_called_once_with("Chrome")
        self.ctx._weather.assert_not_called()
        self.message_step.assert_not_called()
        self.assertIsNone(session.pending_action)
        self.assertIs(session.pending_weather_location, True)

    def test_non_alias_answer_belongs_to_the_weather_question_not_the_clarify(self):
        session = self.ctx._session()
        session.pending_action = self.clarify_pending()
        session.pending_weather_location = True
        self.ctx.system_control.open_application = Mock()
        entry, out = self.turn("İstanbul")
        self.assertEqual(entry.understanding.pending_owner, self.WEATHER_OWNER)
        self.ctx._weather.assert_called_once_with("İstanbul")
        self.ctx.system_control.open_application.assert_not_called()
        self.message_step.assert_not_called()
        self.assertIs(session.pending_weather_location, False)

    def test_exact_confirmation_owner_runs_and_preserves_the_message_draft(self):
        session = self.ctx._session()
        session.pending_confirm = {"action": "close_app", "name": "Chrome"}
        pending = {"to": "Ebru", "text": "", "stage": "text"}
        session.pending_msg = dict(pending)
        close = Mock(return_value=ApplicationResult("kapandı", ok=True))
        self.ctx.system_control.close_application = close
        entry, out = self.turn("evet")
        self.assertEqual(entry.state_gate.protocol, "session.pending_confirm.confirm")
        self.assertIsNone(entry.understanding)
        close.assert_called_once_with("Chrome")
        self.assertIsNone(session.pending_confirm)
        self.assertEqual(session.pending_msg, pending)
        self.message_step.assert_not_called()


class PendingCapabilityAuthorityTests(_CanonicalTurnHarness):
    """Açık mesaj taslağı canonical capability turn'ünü mesaj gövdesine çeviremez.

    Capability kararı Understanding'de bir kez üretilir; pending-owner seçimi bu kararı
    yalnız tüketir, kendi grammar'ıyla yeniden sınıflandırmaz.
    """

    def setUp(self):
        super().setUp()
        self.file = Path(self.temp.name) / "rapor.docx"
        self.file.write_text("içerik", encoding="utf-8")
        original = brain_entry.build_candidates
        rows = [{"path": str(self.file), "name": "rapor.docx", "ext": ".docx"}]
        candidate_patch = patch.object(
            brain_entry,
            "build_candidates",
            lambda **kw: original(**{**kw, "file_reader": lambda *, limit: rows[:limit]}),
        )
        candidate_patch.start()
        self.addCleanup(candidate_patch.stop)
        roots = patch.object(nxapi, "_roots", return_value=[Path(self.temp.name)])
        roots.start()
        self.addCleanup(roots.stop)

    def open_draft(self):
        session = self.ctx._session()
        draft = {"to": "Ebru", "text": "", "stage": "text"}
        session.pending_msg = dict(draft)
        return session, draft

    def run_capability(self, text):
        session, draft = self.open_draft()
        self.ctx.chat.reset_mock()
        with patch.object(brain_precedence, "claim", return_value=None), \
             patch("modules.engine_intents.dispatch", return_value="CORE") as dispatch, \
             patch.object(messaging, "send_whatsapp", Mock()) as sender:
            entry, out = self.turn(text)
            sender.assert_not_called()
        self.assertEqual(session.pending_msg, draft)
        self.message_step.assert_not_called()
        self.ctx.chat.assert_not_called()
        self.assertIs(entry.understanding.conversation_relation, ConversationRelation.NEW_REQUEST)
        self.assertIsNone(entry.understanding.pending_owner)
        self.assertIs(entry.understanding.request_kind, RequestKind.CAPABILITY)
        return entry, out, dispatch

    def test_translation_capability_is_never_the_open_draft_body(self):
        entry, out, dispatch = self.run_capability("iyi günler İngilizceye çevir")
        self.assertEqual(entry.understanding.capability_hint, brain_understanding.TRANSLATE_CAPABILITY)
        self.assertEqual(dispatch.call_args[0][1], "translate")
        self.assertEqual(dispatch.call_args[0][2]["origin"], "inline")
        self.assertIn("iyi günler", dispatch.call_args[0][2]["text"])
        self.assertEqual(out, "CORE")

    def test_file_translation_capability_is_never_the_open_draft_body(self):
        entry, out, dispatch = self.run_capability("rapor.docx dosyasını İngilizceye çevir")
        self.assertEqual(entry.understanding.capability_hint, "files.read")
        self.assertEqual(dispatch.call_args[0][1], "file_action")
        self.assertEqual(dispatch.call_args[0][2],
                         {"operation": "translate", "path": str(self.file), "target": "İngilizce"})
        self.assertEqual(out, "CORE")

    def test_file_analysis_capability_is_never_the_open_draft_body(self):
        _entry, _out, dispatch = self.run_capability("rapor.docx dosyasını incele")
        self.assertEqual(dispatch.call_args[0][1], "file_action")
        self.assertEqual(dispatch.call_args[0][2],
                         {"operation": "analyze", "path": str(self.file), "format": "docx"})

    def test_file_conversion_capability_is_never_the_open_draft_body(self):
        _entry, _out, dispatch = self.run_capability("rapor.docx dosyasını PDF'e dönüştür")
        self.assertEqual(dispatch.call_args[0][1], "file_action")
        self.assertEqual(dispatch.call_args[0][2],
                         {"operation": "convert", "path": str(self.file), "format": "pdf"})

    def test_every_capability_family_stays_independent_of_the_open_draft(self):
        self.ctx._notes_text = Mock(return_value="NOTLARIM")
        self.ctx.system_control.set_volume = Mock(return_value=True)
        self.ctx.desktop.screenshot = Mock(return_value="EKRAN")
        texts = (
            "notlarımı göster",                    # notes
            "hava nasıl",                          # weather
            "sesi 50 yap",                         # level
            "ekran görüntüsü al",                  # screen/desktop (legacy owner)
            "iyi günler İngilizceye çevir",        # translation
            "rapor.docx dosyasını incele",         # file operation
            "rapor.docx dosyasını PDF'e dönüştür", # file conversion
        )
        for text in texts:
            with self.subTest(text=text):
                entry, _out, _dispatch = self.run_capability(text)
                self.assertIs(entry.understanding.request_kind, RequestKind.CAPABILITY)
                self.assertIsNone(entry.understanding.pending_owner)

    def test_typed_app_continuation_is_not_wrongly_excluded_as_independent(self):
        session, draft = self.open_draft()
        session.pending_action = {
            "stage": "clarify", "command": "aç", "question": "Neyi açmamı istiyorsun?",
            "owner": self.owner, "expires": time.time() + 60,
            "proposal": {"kind": "app.open"},
        }
        self.ctx.system_control.open_application = Mock(
            return_value=ApplicationResult("Chrome penceresi açık; açılışını doğruladım.", ok=True))
        with patch.object(brain_precedence, "claim", return_value=None):
            entry, out = self.turn("Chrome")
        self.assertIs(entry.understanding.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)
        self.assertEqual(entry.understanding.pending_owner, "session.pending_action.clarify")
        self.assertIs(entry.understanding.request_kind, RequestKind.CAPABILITY)
        self.ctx.system_control.open_application.assert_called_once_with("Chrome")
        self.message_step.assert_not_called()
        self.assertIsNone(session.pending_action)
        self.assertEqual(session.pending_msg, draft)
        self.assertEqual(out, "Chrome penceresi açık; açılışını doğruladım.")

    def test_free_text_still_answers_the_open_draft(self):
        session, _draft = self.open_draft()
        with patch.object(messaging, "send_whatsapp", Mock()) as sender:
            entry, out = self.turn("Yarın geliyorum")
            sender.assert_not_called()
        self.assertIs(entry.understanding.conversation_relation, ConversationRelation.ANSWER_TO_PENDING)
        self.assertEqual(entry.understanding.pending_owner, "session.pending_msg.text")
        self.message_step.assert_called_once()
        self.assertEqual(session.pending_msg["text"], "Yarın geliyorum")
        self.assertIn("göndereyim mi", out)


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
    # (modül, fonksiyon, bekleyen alan, o alanın ham metni tüketen çağrısı)
    CONSUMERS = (
        (engine_commands, "handle", "pending_msg", "_message_step"),
        (engine_commands, "handle", "pending_confirm", "decision"),
        (engine_commands, "handle", "pending_level", "set_volume"),
        (engine_commands, "handle", "pending_organize", "apply_organize"),
        (engine_commands, "handle", "pending_weather_location", "_weather"),
        (engine_commands, "handle", None, "continue_app"),
        (main_planner, "_planner_command", "pending_event_title", "_reminder_or_confirm"),
        (command_manager, "dispatch", "pending_action", "continue_voice"),
        (command_manager, "dispatch", "pending_desktop", "consent_reply"),
    )

    @staticmethod
    def _func(module, name):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8-sig"))
        return tree, next(node for node in ast.walk(tree)
                          if isinstance(node, ast.FunctionDef) and node.name == name)

    @staticmethod
    def _name(node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def _calls(self, node, name):
        return [n for n in ast.walk(node) if isinstance(n, ast.Call) and self._name(n.func) == name]

    def _mentions(self, node, name):
        return any(self._name(child) == name for child in ast.walk(node))

    @staticmethod
    def _parents(tree):
        parents = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        return parents

    def _fence(self, parents, func, call):
        """Nearest enclosing If that asks the canonical State/Fast owner about this turn."""
        providers = {"turn_protocol", "protocol_owned_by", "pending_answer_owned"}
        has_owned = any(
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "owned" for target in node.targets)
            and isinstance(node.value, ast.Call)
            and self._name(node.value.func) in providers
            for node in ast.walk(func)
        )
        node = parents.get(call)
        while node is not None:
            if isinstance(node, ast.If):
                names = {self._name(child) for child in ast.walk(node.test)}
                if names & providers:
                    return node
                if has_owned and "owned" in names:
                    return node
            node = parents.get(node)
        return None

    def test_core_plan_eligibility_is_relation_driven_not_slot_inventory(self):
        _tree, func = self._func(brain_entry, "core_plan")
        names = {self._name(node.func) for node in ast.walk(func) if isinstance(node, ast.Call)}
        self.assertNotIn("_has_open_pending", names,
                         "core_plan plan eligibility'yi genel pending envanterine bağlayamaz.")
        self.assertIn("_pending_owns_turn", names,
                      "core_plan yalnız canonical relation/state sahipliğini okuyan kapıyı kullanmalı.")

    def test_existing_handler_eligibility_uses_the_relation_owner(self):
        _tree, func = self._func(brain_entry, "_use_existing_handler")
        names = {self._name(node.func) for node in ast.walk(func) if isinstance(node, ast.Call)}
        self.assertIn("_pending_owns_turn", names,
                      "NEW_REQUEST + CAPABILITY açık bir slot yüzünden handler'dan düşmemeli.")

    def test_plan_blocker_reads_canonical_relation_not_raw_text(self):
        _tree, func = self._func(brain_entry, "_pending_owns_turn")
        calls = {self._name(node.func) for node in ast.walk(func) if isinstance(node, ast.Call)}
        self.assertIn("_has_open_pending", calls)
        attrs = {node.attr for node in ast.walk(func) if isinstance(node, ast.Attribute)}
        self.assertTrue({"state_gate", "fast_gate", "understanding", "conversation_relation"}.issubset(attrs))
        self.assertFalse([node for node in ast.walk(func)
                          if isinstance(node, ast.Attribute) and node.attr == "text"],
                         "Plan kapısı ham metni yeniden yorumlamamalı.")

    def test_semantic_pending_answer_ownership_requires_the_typed_owner(self):
        _tree, func = self._func(brain_entry, "pending_answer_owned")
        attrs = {node.attr for node in ast.walk(func) if isinstance(node, ast.Attribute)}
        self.assertIn("pending_owner", attrs,
                      "Semantik dal field bağımsız relation bool'una bağlanamaz; owner kimliği okunmalı.")
        self.assertNotIn("conversation_relation", attrs,
                         "ANSWER_TO_PENDING tek başına her field'a tüketici sahipliği veremez.")
        calls = {self._name(node.func) for node in ast.walk(func) if isinstance(node, ast.Call)}
        self.assertIn("pending_owner_matches", calls,
                      "Field→owner eşleşmesi tek canonical mapping üzerinden yapılmalı.")

    def test_semantic_pending_owner_mapping_is_field_and_stage_scoped(self):
        self.assertTrue(brain_entry.pending_owner_matches("pending_msg", "session.pending_msg.to"))
        self.assertTrue(brain_entry.pending_owner_matches("pending_msg", "session.pending_msg.text"))
        self.assertTrue(brain_entry.pending_owner_matches(
            "pending_weather_location", "session.pending_weather_location"))
        self.assertTrue(brain_entry.pending_owner_matches(
            "pending_action", "session.pending_action.clarify"))
        self.assertFalse(brain_entry.pending_owner_matches(
            "pending_msg", "session.pending_weather_location"))
        self.assertFalse(brain_entry.pending_owner_matches(
            "pending_confirm", "session.pending_msg.text"))
        self.assertFalse(brain_entry.pending_owner_matches("pending_weather_location", None))

    CAPABILITY_CLASSIFIERS = {
        "_looks_like_capability",
        "_explicit_capability_shape",
        "_is_weather_request",
        "_weather_status_request",
        "_screenshot_request",
        "_file_operation",
        "_translate_proposal",
        "_screen_arguments",
        "_desktop_window_arguments",
        "_level_request",
    }

    def test_pending_owner_selection_consumes_the_canonical_capability_decision(self):
        _tree, func = self._func(brain_understanding, "_pending_answer_owners")
        keywords = [arg.arg for arg in func.args.kwonlyargs]
        self.assertIn("independent_capability", keywords,
                      "Pending owner seçimi canonical capability kararını caller'dan almalı.")
        calls = {self._name(node.func) for node in ast.walk(func) if isinstance(node, ast.Call)}
        self.assertFalse(calls & self.CAPABILITY_CLASSIFIERS,
                         "Pending owner seçici capability intent'ini yeniden sınıflandıramaz.")

    def test_pending_answer_candidate_is_structural_not_a_capability_classifier(self):
        _tree, func = self._func(brain_understanding, "_pending_answer_candidate")
        calls = {self._name(node.func) for node in ast.walk(func) if isinstance(node, ast.Call)}
        self.assertFalse(calls & self.CAPABILITY_CLASSIFIERS,
                         "Pending-answer adayı yalnız yapısal sınırları değerlendirir.")

    def test_pending_owner_layer_has_no_inline_capability_regex(self):
        # Yeni bir domain capability'si buraya satır içi regex olarak sızamaz: yalnız canonical
        # karar ve pending evidence okunur.
        for name in ("_pending_answer_owners", "_pending_answer_candidate"):
            with self.subTest(function=name):
                _tree, func = self._func(brain_understanding, name)
                inline = [node for node in ast.walk(func)
                          if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                          and node.func.attr in {"search", "match", "fullmatch", "compile"}]
                self.assertFalse(inline,
                                 f"{name} satır içi regex ile capability sınıflandıramaz.")

    def test_canonical_capability_decision_is_passed_into_owner_selection(self):
        _tree, func = self._func(brain_understanding, "understand")
        calls = [node for node in ast.walk(func)
                 if isinstance(node, ast.Call) and self._name(node.func) == "_pending_answer_owners"]
        self.assertTrue(calls, "understand canonical owner seçimini çağırmalı.")
        passed = {keyword.arg for keyword in calls[0].keywords}
        self.assertIn("independent_capability", passed,
                      "Capability kararı pending owner seçimine parametre olarak geçmeli.")

    def test_goal_legacy_text_is_fenced_before_any_state_rebinding(self):
        _tree, handle = self._func(goal_executor, "handle")
        fences = [node for node in ast.walk(handle)
                  if isinstance(node, ast.If) and self._mentions(node.test, "allow_legacy_goal_control")
                  and any(isinstance(child, ast.Return) for child in ast.walk(node))]
        self.assertTrue(fences, "Goal ham metni canonical sahiplik çitiyle çitlenmeli.")
        self.assertTrue(any(statement is fences[0] for statement in handle.body[:3]),
                        "Goal çiti durum okumasından önce, fonksiyonun başında olmalı.")
        state_reads = self._calls(handle, "latest")
        self.assertTrue(state_reads)
        self.assertLess(min(node.lineno for node in fences), min(node.lineno for node in state_reads))
        rebinding = [
            node.lineno for node in ast.walk(handle)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "low" for target in node.targets)
            and isinstance(node.value, ast.Constant)
            and node.value.value in {"hedef onayla", "hedef iptal"}
        ]
        self.assertTrue(rebinding)
        self.assertLess(min(node.lineno for node in fences), min(rebinding))

    def test_every_legacy_pending_consumer_is_fenced_by_the_canonical_turn_owner(self):
        for module, func_name, field, consumer in self.CONSUMERS:
            with self.subTest(module=module.__name__, consumer=consumer):
                tree, func = self._func(module, func_name)
                parents = self._parents(tree)
                if field is None:
                    calls = self._calls(func, consumer)
                else:
                    branches = [node for node in ast.walk(func)
                                if isinstance(node, ast.If) and self._mentions(node.test, field)]
                    # Yalnız dalın kendi gövdesi: eşleşmeyen başka bir isteğin `else` zinciri sayılmaz.
                    calls = [call for branch in branches for statement in branch.body
                             for call in self._calls(statement, consumer)]
                self.assertTrue(calls, f"{module.__name__}.{func_name}: {consumer} tüketicisi bulunmalı.")
                for call in calls:
                    fence = self._fence(parents, func, call)
                    self.assertIsNotNone(
                        fence,
                        f"{module.__name__}.{func_name}:{call.lineno} {consumer} canonical sahiplik çiti dışında.")
                    self.assertLessEqual(fence.lineno, call.lineno)

    def test_visual_source_question_is_fenced_before_it_can_claim_a_turn(self):
        _tree, handle = self._func(visual_chat, "handle")
        branches = [node for node in ast.walk(handle)
                    if isinstance(node, ast.If)
                    and any(isinstance(child, ast.Constant) and child.value == "source"
                            for child in ast.walk(node.test))]
        self.assertTrue(branches, "Görsel kaynak sorusu dalı bulunmalı.")
        branch = branches[0]
        providers = self._calls(branch, "pending_answer_owned") or self._calls(branch, "turn_protocol")
        generated = self._calls(branch, "_generate")
        self.assertTrue(providers, "Görsel sorusu canonical sahiplik kaynağıyla çitlenmeli.")
        self.assertTrue(generated)
        self.assertLess(min(node.lineno for node in providers), min(node.lineno for node in generated))
        fence_returns = [
            node for node in ast.walk(branch)
            if isinstance(node, ast.If) and self._mentions(node.test, "pending_answer_owned")
            and any(isinstance(child, ast.Return) for child in ast.walk(node))
        ]
        self.assertTrue(fence_returns, "Sahibi başkasıysa görsel sorusu erken dönüşle çekilmeli.")
        question_returns = [node.lineno for node in ast.walk(branch) if isinstance(node, ast.Return)]
        self.assertLess(min(node.lineno for node in fence_returns), max(question_returns))

    def test_production_modules_never_use_the_retired_state_protocol_helper(self):
        root = Path(__file__).resolve().parents[1] / "modules"
        offenders = [path.name for path in root.rglob("*.py")
                     if "state_protocol" in path.read_text(encoding="utf-8")]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
