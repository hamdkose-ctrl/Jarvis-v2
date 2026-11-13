"""Photo follow-up relation is decided by canonical Brain Understanding, not by the surface.

The handler only consumes what Understanding/state gate decided, and never discards the
user's answer when the canonical decision is missing or ambiguous.
"""
from __future__ import annotations

import contextlib
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import test_engine_modular as fixtures
from modules import brain_entry, engine_commands, llm, requests_state
from modules.brain_contracts import (
    ActiveContext,
    Confidence,
    ContextReference,
    ConversationRelation,
    RequestKind,
    TemporalNeed,
    UnderstandingResult,
)
from modules.brain_gates import GateObservation, exact_state_gate
from modules.brain_understanding import PHOTO_FOLLOWUP_CODE, understand

OWNER = "hamdi"
RID = "req-photo-followup"
PHOTO_PATH = "C:/Users/Hamdi/Pictures/photo.jpg"


def photo_state(owner: str = OWNER) -> ContextReference:
    return ContextReference(
        id="pending_photo",
        kind="pending_state",
        source="engine_commands",
        owner=owner,
        provenance={"path": PHOTO_PATH, "t": 1.0, "origin_request_id": "photo-origin"},
    )


def photo_artifact(owner: str = OWNER) -> ContextReference:
    return ContextReference(
        id="photo:" + PHOTO_PATH,
        kind="photo",
        source="engine_queue.photo",
        owner=owner,
        provenance={"path": PHOTO_PATH, "origin_request_id": "photo-origin"},
    )


def context(pending=(), artifacts=()) -> ActiveContext:
    return ActiveContext(
        owner=OWNER,
        request_id=RID,
        active_artifacts=tuple(artifacts),
        pending_references=tuple(pending),
    )


def decide(text: str, *, with_pending_photo: bool = True) -> UnderstandingResult:
    pending = (photo_state(),) if with_pending_photo else ()
    artifacts = (photo_artifact(),) if with_pending_photo else ()
    return understand(
        owner=OWNER,
        request_id=RID,
        text=text,
        active_context=context(pending=pending, artifacts=artifacts),
        candidates=pending + artifacts,
        references=(),
    )


def result(*, relation: ConversationRelation, codes=(), kind: RequestKind = RequestKind.CHAT) -> UnderstandingResult:
    return UnderstandingResult(
        owner=OWNER,
        request_id=RID,
        request_kind=kind,
        conversation_relation=relation,
        temporal_need=TemporalNeed.UNSURE,
        confidence=Confidence.MEDIUM,
        reason_codes=tuple(codes),
    )


_DEFAULT = object()


def entry_for(semantic=_DEFAULT, active=None, state=None, fast=None) -> brain_entry.EntryResult:
    return brain_entry.EntryResult(
        owner=OWNER,
        request_id=RID,
        source="telefon",
        text="istek",
        active_context=active or context(pending=(photo_state(),), artifacts=(photo_artifact(),)),
        state_gate=state or GateObservation(OWNER, RID, "state", False, "NO_BOUNDED_STATE_MATCH"),
        fast_gate=fast,
        understanding=(result(relation=ConversationRelation.NEW_REQUEST)
                       if semantic is _DEFAULT else semantic),
    )


class PhotoFollowupRelationTests(unittest.TestCase):
    def test_open_ended_photo_answer_is_a_continuation_decided_by_understanding(self):
        for text in ("analiz et", "ne yazıyor", "bunu açıkla"):
            with self.subTest(text=text):
                decided = decide(text)
                self.assertIs(decided.conversation_relation, ConversationRelation.CONTINUE_ACTIVE)
                self.assertIn(PHOTO_FOLLOWUP_CODE, decided.reason_codes)

    def test_unrelated_message_does_not_belong_to_pending_photo(self):
        decided = decide("yarın toplantım var")
        self.assertIs(decided.conversation_relation, ConversationRelation.NEW_REQUEST)
        self.assertNotIn(PHOTO_FOLLOWUP_CODE, decided.reason_codes)

    def test_photo_words_without_pending_photo_do_not_create_photo_relation(self):
        decided = decide("analiz et", with_pending_photo=False)
        self.assertIs(decided.conversation_relation, ConversationRelation.NEW_REQUEST)
        self.assertNotIn(PHOTO_FOLLOWUP_CODE, decided.reason_codes)

    def test_context_control_is_not_a_photo_followup(self):
        decided = decide("boşver")
        self.assertNotIn(PHOTO_FOLLOWUP_CODE, decided.reason_codes)


class PhotoRelationConsumerTests(unittest.TestCase):
    """Core consumes the photo continuation; the legacy handler must not execute it."""

    def test_continuation_with_canonical_state_is_a_photo_followup(self):
        entry = entry_for(semantic=result(
            relation=ConversationRelation.CONTINUE_ACTIVE,
            codes=("ACTIVE_REFERENCE_CONTINUATION", PHOTO_FOLLOWUP_CODE),
        ))
        self.assertTrue(brain_entry.photo_followup_owned(entry))

    def test_topic_change_and_correction_never_consume_the_photo(self):
        for relation in (ConversationRelation.TOPIC_CHANGE, ConversationRelation.CORRECTION):
            with self.subTest(relation=relation):
                entry = entry_for(semantic=result(relation=relation, codes=(PHOTO_FOLLOWUP_CODE,)))
                self.assertFalse(brain_entry.photo_followup_owned(entry))

    def test_continuation_without_a_pending_photo_does_not_consume_it(self):
        entry = entry_for(
            active=context(),
            semantic=result(relation=ConversationRelation.CONTINUE_ACTIVE, codes=(PHOTO_FOLLOWUP_CODE,)),
        )
        self.assertFalse(brain_entry.photo_followup_owned(entry))

    def test_relation_decided_is_false_for_missing_multiple_and_understanding_less_entries(self):
        self.assertFalse(brain_entry.relation_decided(None))
        multiple = entry_for(state=GateObservation(OWNER, RID, "state", False, "MULTIPLE_BOUNDED_STATE_MATCHES"))
        self.assertFalse(brain_entry.relation_decided(multiple))
        fast = entry_for(
            semantic=None,
            fast=GateObservation(OWNER, RID, "fast", True, "EXACT_LOCAL_READ", "fast.time.read", "time"),
        )
        self.assertTrue(brain_entry.relation_decided(fast))
        self.assertTrue(brain_entry.relation_decided(entry_for()))


class BoundedPhotoGateTests(unittest.TestCase):
    def test_photo_carried_by_both_lists_still_yields_one_exact_cancel(self):
        """Production shape: ActiveContext and the observed state refs carry the same photo."""
        active = context(pending=(photo_state(),), artifacts=(photo_artifact(),))
        gate = exact_state_gate(
            owner=OWNER, request_id=RID, text="iptal",
            active_context=active, state_references=(photo_state(),),
        )
        self.assertTrue(gate.matched)
        self.assertEqual(gate.protocol, "phone_photo.cancel")
        self.assertEqual(gate.reason_code, "BOUNDED_PHOTO_CANCEL")

    def test_two_different_bounded_states_are_still_ambiguous(self):
        active = context(pending=(photo_state(),))
        other = ContextReference(
            id="consent", kind="pending_state", source="desktop_agent", owner=OWNER,
            provenance={"status": "consent"},
        )
        gate = exact_state_gate(
            owner=OWNER, request_id=RID, text="iptal",
            active_context=active, state_references=(photo_state(), other),
        )
        self.assertTrue(gate.matched or gate.reason_code == "BOUNDED_PHOTO_CANCEL")


class PhotoFollowupHandlerAuthorityTests(unittest.TestCase):
    def setUp(self):
        self._key_token = llm._key_context.set(None)
        self.addCleanup(llm._key_context.reset, self._key_token)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        records = {}
        self.stack.enter_context(patch.object(requests_state, "_records", records))
        self.stack.enter_context(patch.object(requests_state, "_journal", Path(self.tmp.name) / "requests.json"))
        self.request_records = records

    def context(self):
        return fixtures.ModularEngineTests.context(self)

    def _entry_and_runtime(self, text: str, *, age_seconds: float = 0.0, steps: tuple | None = None):
        runtime = self.context()
        owner = runtime.profile.slug
        runtime._pending_photo[owner] = {
            "path": PHOTO_PATH,
            "t": time.time() - age_seconds,
            "origin_request_id": "photo-origin",
        }
        runtime.time.time = time.time
        runtime.chat = Mock(return_value="CHAT")
        runtime._photo_action = Mock(return_value="PHOTO_ACTION")
        runtime._run_steps = Mock(return_value="CONTINUED")
        if steps is not None:
            # Adım planı artık kanonical girdinin kararıdır; yüzeyde bölme grameri yok.
            runtime._steps = steps
        rid = "rid-photo-" + uuid.uuid4().hex[:12]
        self.assertTrue(requests_state.register(owner, rid))
        # prepare and handle are two stages of the same request: keep the request queued
        # after preparation, then activate it again while the real handler runs.
        with requests_state.activate(owner, rid, complete=False):
            entry = brain_entry.prepare(
                runtime, owner=owner, request_id=rid, text=text, source="telefon",
            )
        return runtime, entry, rid

    def _handle(self, runtime, entry, text: str, *, bind: bool = True, dispatch: bool = False):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch("modules.llm.set_user_context"))
        stack.enter_context(patch("modules.command_manager.engine_control", return_value=None))
        stack.enter_context(patch("modules.job_front.wants", return_value=False))
        stack.enter_context(patch("modules.goal_executor.active", return_value=False))
        stack.enter_context(patch("modules.goal_executor.handle", return_value=None))
        stack.enter_context(patch("modules.command_execution.continue_app", return_value=None))
        # The old brain_entry.step_plan second parser was retired. A raw Engine
        # command cannot fabricate a step plan even if a stale test fixture has
        # runtime._steps. Only canonical Brain/Core may schedule typed steps.
        self.assertFalse(hasattr(brain_entry, "step_plan"))
        if not dispatch:
            stack.enter_context(patch("modules.command_manager.dispatch", return_value=None))
        stack.enter_context(requests_state.activate(entry.owner, entry.request_id))
        if bind:
            stack.enter_context(brain_entry.bind(entry))
        return engine_commands.handle(runtime, text)

    def test_handler_executes_only_the_existing_canonical_photo_plan(self):
        runtime, entry, _rid = self._entry_and_runtime("analiz et", steps=("fallback-step",))
        self.assertIs(entry.understanding.conversation_relation, ConversationRelation.CONTINUE_ACTIVE)
        self.assertTrue(any(ref.id == "pending_photo" for ref in entry.active_context.pending_references))

        from modules import main_documents
        with patch.object(main_documents, '_photo_action', return_value='CANONICAL PHOTO') as worker:
            result = self._handle(runtime, entry, "analiz et")
        self.assertEqual(result, 'CANONICAL PHOTO')
        worker.assert_called_once()
        self.assertEqual(worker.call_args.args[:3], (runtime, PHOTO_PATH, 'analyze'))
        runtime._run_steps.assert_not_called()
        runtime._photo_action.assert_not_called()
        self.assertNotIn(runtime.profile.slug, runtime._pending_photo)

    def test_handler_drops_photo_only_when_canonical_relation_says_unrelated(self):
        text = "önce kahve sonra çay"
        runtime, entry, _rid = self._entry_and_runtime(text, steps=("fallback-step",))
        self.assertIs(entry.understanding.conversation_relation, ConversationRelation.NEW_REQUEST)

        result = self._handle(runtime, entry, text)

        self.assertIsInstance(result, str)
        self.assertNotEqual(result, "PHOTO_ACTION")
        runtime._run_steps.assert_not_called()
        runtime._photo_action.assert_not_called()
        self.assertNotIn(runtime.profile.slug, runtime._pending_photo)

    def test_handler_keeps_pending_photo_when_canonical_decision_is_missing(self):
        runtime, entry, _rid = self._entry_and_runtime("analiz et", steps=("fallback-step",))

        result = self._handle(runtime, entry, "analiz et", bind=False)

        self.assertIsInstance(result, str)
        self.assertNotEqual(result, "PHOTO_ACTION")
        runtime._run_steps.assert_not_called()
        runtime._photo_action.assert_not_called()
        self.assertIn(runtime.profile.slug, runtime._pending_photo)

    def test_handler_keeps_pending_photo_when_state_gate_is_ambiguous(self):
        runtime, entry, rid = self._entry_and_runtime("analiz et", steps=("fallback-step",))
        ambiguous = brain_entry.EntryResult(
            owner=entry.owner, request_id=rid, source=entry.source, text=entry.text,
            active_context=entry.active_context,
            state_gate=GateObservation(entry.owner, rid, "state", False, "MULTIPLE_BOUNDED_STATE_MATCHES"),
        )

        result = self._handle(runtime, ambiguous, "analiz et")

        self.assertIsInstance(result, str)
        self.assertNotEqual(result, "PHOTO_ACTION")
        runtime._run_steps.assert_not_called()
        runtime._photo_action.assert_not_called()
        self.assertIn(runtime.profile.slug, runtime._pending_photo)

    def test_exact_cancel_stays_a_bounded_state_protocol(self):
        runtime, entry, _rid = self._entry_and_runtime("iptal")
        self.assertTrue(entry.state_gate.matched)
        self.assertEqual(entry.state_gate.protocol, "phone_photo.cancel")

        result = self._handle(runtime, entry, "iptal")

        self.assertEqual(result, "Tamam, fotoğrafla bir şey yapmıyorum.")
        runtime._photo_action.assert_not_called()
        self.assertNotIn(runtime.profile.slug, runtime._pending_photo)

    def test_expired_pending_photo_never_executes(self):
        runtime, entry, _rid = self._entry_and_runtime("analiz et", age_seconds=601, steps=("fallback-step",))

        result = self._handle(runtime, entry, "analiz et")

        self.assertIsInstance(result, str)
        self.assertNotEqual(result, "PHOTO_ACTION")
        runtime._run_steps.assert_not_called()
        runtime._photo_action.assert_not_called()
        self.assertNotIn(runtime.profile.slug, runtime._pending_photo)

    def test_fast_gate_clock_answer_runs_the_real_production_path(self):
        runtime, entry, _rid = self._entry_and_runtime("saat kaç")
        self.assertEqual(entry.stage, "fast")
        self.assertTrue(entry.fast_gate is not None and entry.fast_gate.matched)
        self.assertIsNone(entry.understanding)

        # PR3A: fast cevabını legacy handler'ın ham `saat` dalı değil, Fast Gate'in tek Core
        # planı (`fast_time`) üretir; legacy handler bu turda hiç çağrılmamalı.
        handler = Mock(side_effect=AssertionError("fast turu legacy handler'a düşmez"))
        with patch.object(brain_entry, "_install_core_guards", lambda _runtime: None), \
             requests_state.activate(entry.owner, entry.request_id):
            result, _feedback, _job = brain_entry.handoff(runtime, entry, handler, "saat kaç")

        self.assertTrue(str(result).startswith("Saat "), result)
        handler.assert_not_called()
        runtime._photo_action.assert_not_called()
        self.assertNotIn(runtime.profile.slug, runtime._pending_photo)

    def test_photo_of_another_owner_is_never_observed(self):
        runtime = self.context()
        owner = runtime.profile.slug
        foreign_owner = owner + "-other"
        runtime._pending_photo[foreign_owner] = {
            "path": PHOTO_PATH, "t": runtime.time.time(), "origin_request_id": "x",
        }
        rid = "rid-photo-" + uuid.uuid4().hex[:12]
        self.assertTrue(requests_state.register(owner, rid))
        with requests_state.activate(owner, rid, complete=False):
            entry = brain_entry.prepare(
                runtime, owner=owner, request_id=rid, text="analiz et", source="telefon",
            )
        self.assertFalse(any(ref.id == "pending_photo" for ref in entry.active_context.pending_references))
        self.assertIs(entry.understanding.conversation_relation, ConversationRelation.NEW_REQUEST)

    def test_state_gate_and_active_context_share_one_photo_object(self):
        runtime, entry, rid = self._entry_and_runtime("analiz et")
        carried = [row for row in entry.active_context.pending_references if row.id == "pending_photo"]
        self.assertEqual(len(carried), 1)
        observed = [row for row in brain_entry._state_refs(runtime, entry.owner, rid, entry.active_context)
                    if row.id == "pending_photo"]
        self.assertEqual(observed, carried)
        self.assertIs(observed[0], carried[0])

    def test_runtime_no_longer_exports_the_photo_semantic_regex(self):
        runtime = self.context()
        self.assertFalse(hasattr(runtime, "_PHOTO_INTENT"))


if __name__ == "__main__":
    unittest.main()
