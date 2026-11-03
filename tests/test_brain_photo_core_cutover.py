"""PR2: photo operation is proposed by canonical Understanding and executed by a typed Core intent.

No surface selects a photo operation from raw text; Core validates the operation and the path
against this request's canonical photo artifact before the domain executor applies it.
"""
from __future__ import annotations

import ast
import contextlib
import tempfile
import time
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_brain_closeout_a  # noqa: F401  (shared test stubs)
import test_brain_production_entry as fixtures  # noqa: F401  (import ordering fixtures)
from modules import brain_context, brain_core_map, brain_entry, brain_precedence, desktop_agent
from modules import engine_commands, engine_runtime, job_front, main_documents, personalization, requests_state
from modules import brain_understanding
from modules.brain_contracts import RequestKind
from modules.brain_gates import GateObservation

PHOTO = "C:/Users/Hamdi/Pictures/photo.jpg"
OTHER_PHOTO = "C:/Users/Hamdi/Pictures/other.jpg"
EVIL = "C:/Temp/evil.jpg"
OWNER = "hamdi"


def _isolate_profiles(case, root: Path) -> None:
    users = root / "users"
    users.mkdir(exist_ok=True)
    for target, attr, value in ((personalization, "USERS_DIR", users),
                                (personalization, "ACTIVE_FILE", root / "active_user.txt")):
        state_patch = patch.object(target, attr, value)
        state_patch.start()
        case.addCleanup(state_patch.stop)


def _source(name: str) -> str:
    path = Path(__file__).resolve().parents[1] / "modules" / f"{name}.py"
    return path.read_text(encoding="utf-8")


def _function(tree: ast.AST, name: str) -> ast.FunctionDef:
    return next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == name)


def _calls(node: ast.AST) -> list[ast.Call]:
    return [row for row in ast.walk(node) if isinstance(row, ast.Call)]


def _attr_call(call: ast.Call) -> str:
    return call.func.attr if isinstance(call.func, ast.Attribute) else (
        call.func.id if isinstance(call.func, ast.Name) else "")


class _PhotoHarness(unittest.TestCase):
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
        for target, attr, value in ((brain_context, "_default_goal_reader", None),
                                    (job_front, "observe", None),
                                    (desktop_agent, "_load", None),
                                    (brain_entry, "_install_core_guards", lambda runtime: None)):
            state_patch = patch.object(target, attr, value)
            state_patch.start()
            self.addCleanup(state_patch.stop)
        self.ctx.ask_image = Mock(return_value="GÖRSEL YANIT")
        self.ctx._add_note = Mock(return_value={"ok": True})
        self.ctx.chat = Mock(return_value="CHAT")
        for target, attr, value in ((self.ctx.privacy, "blocked", None),
                                    (self.ctx.privacy, "audit", None)):
            state_patch = patch.object(target, attr, return_value=value)
            state_patch.start()
            self.addCleanup(state_patch.stop)
        self._real_executor = main_documents._photo_action
        executor = patch.object(main_documents, "_photo_action", Mock(return_value="PHOTO OK"))
        self.executor = executor.start()
        self.addCleanup(executor.stop)

    def runtime(self):
        return self.ctx

    def _rid(self, prefix="photo") -> str:
        return f"{prefix}-" + uuid.uuid4().hex[:10]

    def prepare_initial(self, text: str, *, path: str = PHOTO, rid: str | None = None):
        rid = rid or self._rid()
        self.assertTrue(requests_state.register(self.owner, rid))
        artifact = brain_entry.photo_artifact(owner=self.owner, request_id=rid, path=path)
        with requests_state.activate(self.owner, rid, complete=False):
            entry = brain_entry.prepare(
                self.ctx, owner=self.owner, request_id=rid, text=text, source="telefon", artifact=artifact,
            )
        return entry, rid

    def prepare_pending(self, text: str, *, path: str = PHOTO, origin: str = "old-photo",
                        age_seconds: float = 0.0, owner: str | None = None):
        owner = owner or self.owner
        self.ctx._pending_photo[owner] = {
            "path": path, "t": time.time() - age_seconds, "origin_request_id": origin,
        }
        rid = self._rid("followup")
        self.assertTrue(requests_state.register(self.owner, rid))
        with requests_state.activate(self.owner, rid, complete=False):
            entry = brain_entry.prepare(
                self.ctx, owner=self.owner, request_id=rid, text=text, source="telefon",
            )
        return entry, rid

    def run_core(self, entry):
        with patch.object(brain_precedence, "claim", return_value=None), \
             requests_state.activate(entry.owner, entry.request_id):
            return brain_entry.handoff(self.ctx, entry, self.ctx.handle, entry.text)

    def handle_legacy(self, entry, text: str):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch("modules.llm.set_user_context"))
        stack.enter_context(patch("modules.command_manager.engine_control", return_value=None))
        stack.enter_context(patch("modules.job_front.wants", return_value=False))
        stack.enter_context(patch("modules.goal_executor.active", return_value=False))
        stack.enter_context(patch("modules.goal_executor.handle", return_value=None))
        stack.enter_context(patch("modules.command_execution.continue_app", return_value=None))
        stack.enter_context(patch("modules.command_manager.dispatch", return_value=None))
        stack.enter_context(requests_state.activate(entry.owner, entry.request_id))
        stack.enter_context(brain_entry.bind(entry))
        return engine_commands.handle(self.ctx, text)


class InitialPhotoCoreTests(_PhotoHarness):
    def test_initial_photo_analyze_reaches_core_plan_and_typed_executor(self):
        entry, _rid = self.prepare_initial("Bunu analiz et")
        semantic = entry.understanding
        self.assertEqual(semantic.capability_hint, brain_understanding.PHOTO_CAPABILITY)
        self.assertEqual(semantic.arguments.get("operation"), "analyze")
        plan = brain_entry.core_plan(entry)
        self.assertIsNotNone(plan)
        self.assertEqual(plan[0], "photo_action")
        self.assertEqual(plan[1].get("photo"), PHOTO)

        out, feedback, _ = self.run_core(entry)

        self.assertEqual(out, "PHOTO OK")
        self.executor.assert_called_once()
        args, kwargs = self.executor.call_args
        self.assertEqual(args[0], self.ctx)
        self.assertEqual(args[1], PHOTO)
        self.assertEqual(args[2], "analyze")
        self.assertEqual(kwargs.get("question"), "")
        self.ctx.chat.assert_not_called()
        self.assertEqual(feedback.result_status, "handled")

    def test_initial_photo_translate_uses_typed_target(self):
        entry, _rid = self.prepare_initial("İngilizceye çevir")
        semantic = entry.understanding
        self.assertEqual(semantic.capability_hint, brain_understanding.PHOTO_CAPABILITY)
        self.assertEqual(semantic.arguments.get("operation"), "translate")
        self.assertEqual(semantic.arguments.get("target"), "İngilizce")
        plan = brain_entry.core_plan(entry)
        self.assertEqual(plan[0], "photo_action")

        out, feedback, _ = self.run_core(entry)

        self.assertEqual(out, "PHOTO OK")
        args, kwargs = self.executor.call_args
        self.assertEqual((args[1], args[2]), (PHOTO, "translate"))
        self.assertEqual(kwargs.get("target"), "İngilizce")
        self.assertFalse(kwargs.get("note_text"))
        self.assertEqual(feedback.result_status, "handled")

    def test_initial_photo_note_uses_typed_note_text_without_image_analysis(self):
        entry, _rid = self.prepare_initial("bunu not et: garanti belgesi")
        semantic = entry.understanding
        self.assertEqual(semantic.arguments.get("operation"), "note")
        self.assertEqual(semantic.arguments.get("note_text"), "garanti belgesi")
        plan = brain_entry.core_plan(entry)
        self.assertEqual(plan[0], "photo_action")

        out, feedback, _ = self.run_core(entry)

        self.assertEqual(out, "PHOTO OK")
        args, kwargs = self.executor.call_args
        self.assertEqual((args[1], args[2]), (PHOTO, "note"))
        self.assertEqual(kwargs.get("note_text"), "garanti belgesi")
        self.ctx.ask_image.assert_not_called()
        self.assertEqual(feedback.result_status, "handled")

    def test_initial_photo_question_is_typed_analyze_data(self):
        entry, _rid = self.prepare_initial("Bu soruyu çöz")
        semantic = entry.understanding
        self.assertEqual(semantic.arguments.get("operation"), "analyze")
        self.assertEqual(semantic.arguments.get("question"), "Bu soruyu çöz")

        out, _feedback, _ = self.run_core(entry)

        self.assertEqual(out, "PHOTO OK")
        args, kwargs = self.executor.call_args
        self.assertEqual((args[1], args[2]), (PHOTO, "analyze"))
        self.assertEqual(kwargs.get("question"), "Bu soruyu çöz")

    def test_no_question_photo_has_no_plan_and_reports_needs_input(self):
        entry, _rid = self.prepare_initial("Fotoğraf")
        self.assertIsNone(brain_entry.core_plan(entry))
        if entry.understanding is not None:
            self.assertNotEqual(entry.understanding.capability_hint, brain_understanding.PHOTO_CAPABILITY)
        feedback = brain_entry.photo_feedback(entry, awaiting_question=True)
        self.assertEqual(feedback.result_status, "needs_input")
        self.executor.assert_not_called()
        self.ctx.ask_image.assert_not_called()
        self.ctx._add_note.assert_not_called()


class PendingPhotoCoreTests(_PhotoHarness):
    def test_pending_followup_analyze_runs_core_and_consumes_pending(self):
        entry, _rid = self.prepare_pending("analiz et")
        semantic = entry.understanding
        self.assertIs(semantic.conversation_relation, brain_understanding.ConversationRelation.CONTINUE_ACTIVE)
        self.assertIn(brain_understanding.PHOTO_FOLLOWUP_CODE, semantic.reason_codes)
        self.assertEqual(semantic.capability_hint, brain_understanding.PHOTO_CAPABILITY)
        self.assertEqual(semantic.arguments.get("operation"), "analyze")
        plan = brain_entry.core_plan(entry)
        self.assertEqual(plan[0], "photo_action")

        out, feedback, _ = self.run_core(entry)

        self.assertEqual(out, "PHOTO OK")
        self.assertEqual(self.executor.call_args[0][1], PHOTO)
        self.assertEqual(self.executor.call_args[0][2], "analyze")
        self.assertNotIn(self.owner, self.ctx._pending_photo)
        self.assertEqual(feedback.result_status, "handled")

    def test_pending_followup_translate_and_note_are_typed(self):
        for text, operation, key, value in (
            ("çevir", "translate", "target", "Türkçe"),
            ("Almancaya çevir", "translate", "target", "Almanca"),
            ("not olarak kaydet", "note", "note_text", "Fotoğraf"),
        ):
            with self.subTest(text=text):
                self.ctx._pending_photo.clear()
                self.executor.reset_mock()
                entry, _rid = self.prepare_pending(text)
                semantic = entry.understanding
                self.assertEqual(semantic.capability_hint, brain_understanding.PHOTO_CAPABILITY)
                self.assertEqual(semantic.arguments.get("operation"), operation)
                self.assertEqual(semantic.arguments.get(key), value)
                plan = brain_entry.core_plan(entry)
                self.assertEqual(plan[0], "photo_action")
                out, feedback, _ = self.run_core(entry)
                self.assertEqual(out, "PHOTO OK")
                self.assertEqual(self.executor.call_args[0][2], operation)
                self.assertEqual(self.executor.call_args[1].get(key), value)
                self.assertEqual(feedback.result_status, "handled")

    def test_pending_cancel_stays_in_the_state_gate_without_photo_execution(self):
        entry, _rid = self.prepare_pending("iptal")
        self.assertTrue(entry.state_gate.matched)
        self.assertEqual(entry.state_gate.protocol, "phone_photo.cancel")
        self.assertIsNone(brain_entry.core_plan(entry))

        result = self.handle_legacy(entry, "iptal")

        self.assertEqual(result, "Tamam, fotoğrafla bir şey yapmıyorum.")
        self.executor.assert_not_called()
        self.ctx.ask_image.assert_not_called()
        self.ctx._add_note.assert_not_called()
        self.assertNotIn(self.owner, self.ctx._pending_photo)

    def test_unrelated_request_drops_pending_without_photo_execution(self):
        entry, _rid = self.prepare_pending("yarın toplantım var")
        self.assertIs(entry.understanding.conversation_relation,
                      brain_understanding.ConversationRelation.NEW_REQUEST)
        self.assertIsNone(brain_entry.core_plan(entry))
        self.ctx._split_steps = Mock(return_value=("fallback-step",))
        self.ctx._run_steps = Mock(return_value="CONTINUED")

        result = self.handle_legacy(entry, "yarın toplantım var")

        self.assertEqual(result, "CONTINUED")
        self.executor.assert_not_called()
        self.assertNotIn(self.owner, self.ctx._pending_photo)

    def test_ambiguous_state_preserves_pending_and_runs_no_photo_effect(self):
        entry, rid = self.prepare_pending("analiz et")
        ambiguous = brain_entry.EntryResult(
            owner=entry.owner, request_id=rid, source=entry.source, text=entry.text,
            active_context=entry.active_context,
            state_gate=GateObservation(entry.owner, rid, "state", False, "MULTIPLE_BOUNDED_STATE_MATCHES"),
        )
        self.assertIsNone(brain_entry.core_plan(ambiguous))
        self.ctx._split_steps = Mock(return_value=("fallback-step",))
        self.ctx._run_steps = Mock(return_value="CONTINUED")

        result = self.handle_legacy(ambiguous, "analiz et")

        self.assertEqual(result, "CONTINUED")
        self.executor.assert_not_called()
        self.ctx.ask_image.assert_not_called()
        self.assertIn(self.owner, self.ctx._pending_photo)


class PhotoFenceAndPrivacyTests(_PhotoHarness):
    def test_privacy_block_stops_typed_operations_before_any_effect(self):
        with patch.object(self.ctx.privacy, "blocked", return_value="Kamera erişimi kapalı."), \
             patch.object(main_documents, "_photo_action", self._real_executor):
            for text, operation in (("Bunu analiz et", "analyze"),
                                    ("bunu not et: garanti", "note")):
                with self.subTest(text=text):
                    self.ctx._pending_photo.clear()
                    entry, _rid = self.prepare_initial(text)
                    self.assertEqual(entry.understanding.capability_hint,
                                     brain_understanding.PHOTO_CAPABILITY)
                    self.assertEqual(entry.understanding.arguments.get("operation"), operation)
                    out, feedback, _ = self.run_core(entry)
                    self.assertEqual(out, "Kamera erişimi kapalı.")
                    self.ctx.ask_image.assert_not_called()
                    self.ctx._add_note.assert_not_called()
                    self.ctx.privacy.audit.assert_not_called()
                    self.assertEqual(feedback.result_status, "handled")

    def test_forged_artifact_path_never_becomes_a_core_plan(self):
        entry, _rid = self.prepare_initial("Bunu analiz et")
        forged = replace(entry, understanding=replace(
            entry.understanding,
            arguments={**entry.understanding.arguments, "photo": EVIL},
        ))
        self.assertIsNone(brain_entry.core_plan(forged))

        with patch.object(brain_precedence, "claim", return_value=None), \
             requests_state.activate(forged.owner, forged.request_id):
            out, feedback, _ = brain_entry.handoff(self.ctx, forged, self.ctx.handle, forged.text)

        self.assertIn("doğrulayamadım", out)
        self.executor.assert_not_called()
        self.ctx.ask_image.assert_not_called()
        self.ctx._add_note.assert_not_called()
        self.ctx.chat.assert_not_called()
        self.assertEqual(feedback.result_status, "failed")
        self.assertEqual(feedback.reason_code, "PHOTO_TARGET_NOT_VALIDATED")

    def test_another_photo_artifact_cannot_supply_the_path(self):
        entry, _rid = self.prepare_initial("Bunu analiz et")
        other = brain_entry.photo_artifact(owner=self.owner, request_id=entry.request_id, path=OTHER_PHOTO)
        active = replace(entry.active_context, active_artifacts=entry.active_context.active_artifacts + (other,))
        swapped = replace(entry, active_context=active, understanding=replace(
            entry.understanding,
            arguments={**entry.understanding.arguments, "photo": OTHER_PHOTO},
        ))
        # Two current-request photo artifacts are not a single canonical path: Core fails closed.
        self.assertIsNone(brain_entry.core_plan(swapped))

    def test_raw_operation_injection_is_rejected_before_execution(self):
        entry, _rid = self.prepare_initial("Bunu analiz et")
        for operation in ("delete", "send", "shell"):
            with self.subTest(operation=operation):
                forged = replace(entry, understanding=replace(
                    entry.understanding,
                    arguments={**entry.understanding.arguments, "operation": operation},
                ))
                self.assertIsNone(brain_entry.core_plan(forged))
                out, feedback, _ = self.run_core(forged)
                self.assertIn("doğrulayamadım", out)
                self.executor.assert_not_called()
                self.ctx.ask_image.assert_not_called()
                self.ctx._add_note.assert_not_called()
                self.ctx.chat.assert_not_called()
                self.assertEqual(feedback.result_status, "failed")

    def test_wrong_owner_photo_is_never_observed_or_executed(self):
        entry, _rid = self.prepare_pending("analiz et", owner="ebru")
        self.assertFalse(any(ref.kind == "photo" for ref in entry.active_context.active_artifacts))
        self.assertIsNone(brain_entry.core_plan(entry))
        out, _feedback, _ = self.run_core(entry)
        self.assertEqual(out, "CHAT")
        self.executor.assert_not_called()

    def test_foreign_artifact_owner_is_rejected_at_prepare(self):
        rid = self._rid()
        self.assertTrue(requests_state.register(self.owner, rid))
        artifact = brain_entry.photo_artifact(owner="ebru", request_id=rid, path=PHOTO)
        with requests_state.activate(self.owner, rid, complete=False):
            with self.assertRaises(ValueError):
                brain_entry.prepare(
                    self.ctx, owner=self.owner, request_id=rid, text="analiz et",
                    source="telefon", artifact=artifact,
                )


class PhotoTranslationTargetParityTests(_PhotoHarness):
    """The photo cutover must keep every target the pre-cutover photo path understood."""

    TARGETS = (
        ("Japoncaya çevir", "Japonca"),
        ("Çinceye çevir", "Çince"),
        ("Koreceye çevir", "Korece"),
        ("İtalyancaya çevir", "İtalyanca"),
    )

    def test_initial_photo_translation_keeps_the_pre_cutover_targets(self):
        for text, target in self.TARGETS:
            with self.subTest(text=text):
                self.ctx._pending_photo.clear()
                self.executor.reset_mock()
                entry, _rid = self.prepare_initial(text)
                semantic = entry.understanding
                self.assertEqual(semantic.capability_hint, brain_understanding.PHOTO_CAPABILITY)
                self.assertEqual(semantic.arguments.get("operation"), "translate")
                self.assertEqual(semantic.arguments.get("target"), target)
                plan = brain_entry.core_plan(entry)
                self.assertIsNotNone(plan, text)
                self.assertEqual(plan[0], "photo_action")

                out, feedback, _ = self.run_core(entry)

                self.assertEqual(out, "PHOTO OK")
                self.assertEqual(self.executor.call_args[0][2], "translate")
                self.assertEqual(self.executor.call_args[1].get("target"), target)
                self.ctx.chat.assert_not_called()
                self.assertEqual(feedback.result_status, "handled")

    def test_pending_photo_followup_keeps_the_pre_cutover_targets(self):
        for text, target in self.TARGETS:
            with self.subTest(text=text):
                self.ctx._pending_photo.clear()
                self.executor.reset_mock()
                entry, _rid = self.prepare_pending(text)
                semantic = entry.understanding
                self.assertIs(semantic.conversation_relation,
                              brain_understanding.ConversationRelation.CONTINUE_ACTIVE)
                self.assertIn(brain_understanding.PHOTO_FOLLOWUP_CODE, semantic.reason_codes)
                self.assertEqual(semantic.capability_hint, brain_understanding.PHOTO_CAPABILITY)
                self.assertEqual(semantic.arguments.get("operation"), "translate")
                self.assertEqual(semantic.arguments.get("target"), target)
                plan = brain_entry.core_plan(entry)
                self.assertIsNotNone(plan, text)
                self.assertEqual(plan[0], "photo_action")

                out, feedback, _ = self.run_core(entry)

                self.assertEqual(out, "PHOTO OK")
                self.assertEqual(self.executor.call_args[0][1], PHOTO)
                self.assertEqual(self.executor.call_args[0][2], "translate")
                self.assertEqual(self.executor.call_args[1].get("target"), target)
                self.assertEqual(feedback.result_status, "handled")

    def test_targetless_photo_translation_keeps_the_turkish_fallback(self):
        entry, _rid = self.prepare_initial("çevir")
        semantic = entry.understanding
        self.assertEqual(semantic.capability_hint, brain_understanding.PHOTO_CAPABILITY)
        self.assertEqual(semantic.arguments.get("operation"), "translate")
        self.assertEqual(semantic.arguments.get("target"), "Türkçe")
        plan = brain_entry.core_plan(entry)
        self.assertIsNotNone(plan)

        out, _feedback, _ = self.run_core(entry)

        self.assertEqual(out, "PHOTO OK")
        self.assertEqual(self.executor.call_args[1].get("target"), "Türkçe")

    def test_unknown_explicit_language_never_silently_becomes_turkish(self):
        for text in ("Klingoncaya çevir", "Klingoncaya tercüme et"):
            for prepare in (self.prepare_initial, self.prepare_pending):
                with self.subTest(text=text, prepare=prepare.__name__):
                    self.ctx._pending_photo.clear()
                    self.executor.reset_mock()
                    entry, _rid = prepare(text)
                    semantic = entry.understanding
                    self.assertIs(semantic.request_kind, RequestKind.CLARIFY)
                    self.assertIn(brain_understanding.PHOTO_TARGET_UNRESOLVED, semantic.ambiguities)
                    self.assertNotEqual(semantic.arguments.get("target"), "Türkçe")
                    self.assertIsNone(brain_entry.core_plan(entry))

                    out, feedback, _ = self.run_core(entry)

                    self.assertNotEqual(out, "PHOTO OK")
                    self.assertIn("dil", out.casefold())
                    self.executor.assert_not_called()
                    self.ctx.ask_image.assert_not_called()
                    self.ctx.chat.assert_not_called()
                    self.assertEqual(feedback.result_status, "needs_input")


class CanonicalTranslationTargetValidationTests(unittest.TestCase):
    def test_core_photo_validator_accepts_exactly_the_canonical_registry(self):
        from modules import translation_targets
        for target in translation_targets.display_names():
            with self.subTest(target=target):
                plan = brain_core_map.core_plan(
                    brain_understanding.PHOTO_CAPABILITY,
                    {"operation": "translate", "photo": PHOTO, "target": target},
                )
                self.assertIsNotNone(plan)
                self.assertEqual(plan[1]["target"], target)
        for target in ("Klingonca", "japonca", "", None):
            with self.subTest(target=target):
                self.assertIsNone(brain_core_map.core_plan(
                    brain_understanding.PHOTO_CAPABILITY,
                    {"operation": "translate", "photo": PHOTO, "target": target},
                ))

    def test_core_file_validator_accepts_exactly_the_canonical_registry(self):
        from modules import translation_targets
        with patch.object(brain_core_map, "_validated_file_path", return_value="C:/Temp/report.docx"):
            for target in translation_targets.display_names():
                with self.subTest(target=target):
                    plan = brain_core_map.core_plan(
                        "files.read",
                        {"operation": "translate", "path": "C:/Temp/report.docx", "target": target},
                    )
                    self.assertIsNotNone(plan)
                    self.assertEqual(plan[1]["target"], target)
            for target in ("Klingonca", "japonca", "", None):
                with self.subTest(target=target):
                    self.assertIsNone(brain_core_map.core_plan(
                        "files.read",
                        {"operation": "translate", "path": "C:/Temp/report.docx", "target": target},
                    ))


class PhotoStructuralGuardTests(unittest.TestCase):
    def test_engine_loop_never_calls_the_domain_executor_with_raw_text(self):
        tree = ast.parse(_source("engine_loop"))
        main = _function(tree, "main")
        self.assertFalse([call for call in _calls(main) if _attr_call(call) == "_photo_action"])
        self.assertGreaterEqual(
            len([call for call in _calls(main) if _attr_call(call) == "handoff"]), 2,
            "photo turn must use the shared canonical handoff",
        )

    def test_engine_commands_never_calls_the_domain_executor_with_raw_text(self):
        tree = ast.parse(_source("engine_commands"))
        handle = _function(tree, "handle")
        self.assertFalse([call for call in _calls(handle) if _attr_call(call) == "_photo_action"])

    def test_photo_executor_has_no_raw_operation_selection(self):
        tree = ast.parse(_source("main_documents"))
        executor = _function(tree, "_photo_action")
        self.assertFalse([call for call in _calls(executor)
                          if _attr_call(call) in {"search", "match", "fullmatch", "sub", "compile", "_tr_lower"}])

    def test_photo_capability_is_in_the_core_allowlist(self):
        self.assertIn(brain_understanding.PHOTO_CAPABILITY, brain_core_map.CORE_INTENTS)

    def test_developer_surface_is_explicit_and_never_runs_photo_actions(self):
        tree = ast.parse(_source("engine_loop"))
        main = _function(tree, "main")
        branches = []
        for node in ast.walk(main):
            if not isinstance(node, ast.If) or not isinstance(node.test, ast.BoolOp):
                continue
            if not isinstance(node.test.op, ast.And):
                continue
            keys = set()
            for part in node.test.values:
                if (isinstance(part, ast.Subscript) and isinstance(part.value, ast.Name)
                        and part.value.id == "development"
                        and isinstance(part.slice, ast.Constant)
                        and isinstance(part.slice.value, str)):
                    keys.add(part.slice.value)
            if keys == {"enabled", "unlocked"}:
                branches.append(node)
        self.assertEqual(len(branches), 1, "developer surface must be gated by enabled and unlocked")
        names = {_attr_call(call) for node in branches[0].body for call in _calls(node)}
        self.assertIn("handle", names)
        self.assertNotIn("handoff", names)
        self.assertNotIn("_photo_action", names)

    def test_core_plan_fences_the_photo_path_to_canonical_artifacts(self):
        tree = ast.parse(_source("brain_entry"))
        plan = _function(tree, "core_plan")
        names = {call.func.id for call in _calls(plan) if isinstance(call.func, ast.Name)}
        self.assertIn("_canonical_photo_path", names)

    def test_photo_plan_is_not_shadowed_by_legacy_raw_text_gates(self):
        runtime = SimpleNamespace(_tr_lower=lambda text: text.casefold())

        def gate(*_a, **_k):
            raise AssertionError("legacy gate must not run for a validated photo plan")

        for name in ("_file_command", "_user_command", "_planner_command", "_macro_teach",
                     "_macro_manage", "_macro_run", "_extra_commands"):
            setattr(runtime, name, gate)
        runtime.system_control = SimpleNamespace(windows_settings=gate)
        runtime.emit = lambda *a, **k: None
        self.assertIsNone(brain_precedence.claim(runtime, "analiz et", ("photo_action", {"photo": PHOTO})))

    def test_no_module_keeps_a_second_language_registry(self):
        banned = {"_PHOTO_LANGUAGES", "_FILE_LANGUAGES", "_TRANSLATE_LANGS"}
        for name in ("brain_core_map", "brain_understanding", "translation_request"):
            tree = ast.parse(_source(name))
            for node in tree.body:
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                assigned = {item.id for item in targets if isinstance(item, ast.Name)}
                with self.subTest(module=name, assigned=sorted(assigned & banned)):
                    self.assertFalse(assigned & banned)
                if "_TARGETS" in assigned:
                    self.assertIsInstance(node.value, ast.Attribute)
                    self.assertEqual(getattr(node.value.value, "id", ""), "translation_targets")

    def test_photo_and_file_validators_use_the_canonical_membership_check(self):
        from modules import translation_targets
        tree = ast.parse(_source("brain_core_map"))
        language_names = set(translation_targets.display_names())
        for fn_name in ("_photo_args", "_file_args"):
            fn = _function(tree, fn_name)
            with self.subTest(function=fn_name):
                self.assertIn("is_supported_target", {_attr_call(call) for call in _calls(fn)})
                literals = {node.value for node in ast.walk(fn) if isinstance(node, ast.Constant)}
                self.assertFalse(literals & language_names, "validator must not embed its own language list")

    def test_photo_proposal_uses_the_canonical_target_parser(self):
        tree = ast.parse(_source("brain_understanding"))
        photo = _function(tree, "_photo_proposal")
        attrs = {call.func.attr for call in _calls(photo) if isinstance(call.func, ast.Attribute)}
        self.assertIn("target_from_command", attrs)
        self.assertIn("explicit_target_unresolved", attrs)


if __name__ == "__main__":
    unittest.main()
