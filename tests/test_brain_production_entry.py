from __future__ import annotations

import importlib
import inspect
import queue
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modules.brain_contracts import (
    ActiveContext,
    Confidence,
    ContextReference,
    ConversationRelation,
    RequestKind,
    TemporalNeed,
    UnderstandingResult,
)
from modules.brain_gates import GateObservation, deterministic_fast_gate
from modules import engine_loop, engine_queue

OWNER = "hamdi"
RID = "req-production-entry-1"
_RESERVED = {
    "allowed", "permission", "permission_granted", "approved", "authorized",
    "completed", "done", "effect_allowed", "execute",
}


def context(*, owner: str = OWNER, request_id: str = RID, pending=(), goals=(), tasks=(), artifacts=()) -> ActiveContext:
    return ActiveContext(
        owner=owner,
        request_id=request_id,
        pending_references=tuple(pending),
        active_goal_references=tuple(goals),
        active_task_references=tuple(tasks),
        active_artifacts=tuple(artifacts),
    )


def understanding(*, owner: str = OWNER, request_id: str = RID,
                  kind: RequestKind = RequestKind.CHAT,
                  relation: ConversationRelation = ConversationRelation.NEW_REQUEST,
                  hint: str | None = None, needs_input: bool = False,
                  ambiguities=(), pending_owner: str | None = None) -> UnderstandingResult:
    return UnderstandingResult(
        owner=owner,
        request_id=request_id,
        request_kind=kind,
        capability_hint=hint,
        arguments={"original_text": "istek"},
        conversation_relation=relation,
        temporal_need=TemporalNeed.UNSURE,
        confidence=Confidence.LOW if needs_input else Confidence.MEDIUM,
        ambiguities=tuple(ambiguities),
        needs_input=needs_input,
        pending_owner=pending_owner,
    )


def door(text: str, *, owner: str = OWNER, request_id: str = RID):
    """Cümlenin canonical kapı kararı: Understand -> tek sınıflandırılmış-istek kapısı.

    Model sınıfleyicisi yoktur; kapı yalnız bu turn'ün bağlı kararını izdüşürür.
    Dönüş: (UnderstandingResult, decision dict)."""
    import dataclasses

    from modules import brain_entry, brain_understanding

    semantic = brain_understanding.understand(owner=owner, request_id=request_id, text=text,
                                              active_context=ActiveContext(owner=owner, request_id=request_id),
                                              candidates=(), references=())
    row = dataclasses.replace(entry(brain_entry, semantic=semantic), text=text)
    runtime = SimpleNamespace()
    with brain_entry.bind(row):
        return semantic, brain_entry.route_command(runtime, text)


def entry(module, *, semantic=None, active=None, state=None, fast=None):
    return module.EntryResult(
        owner=OWNER,
        request_id=RID,
        source="yazı",
        text="istek",
        active_context=active or context(),
        state_gate=state or GateObservation(OWNER, RID, "state", False, "NO_BOUNDED_STATE_MATCH"),
        fast_gate=fast or GateObservation(OWNER, RID, "fast", False, "NO_EXACT_FAST_MATCH"),
        candidates=(),
        references=(),
        understanding=semantic or understanding(),
    )


class BrainProductionEntryTests(unittest.TestCase):
    def module(self):
        return importlib.import_module("modules.brain_entry")

    def runtime(self, owner: str = OWNER):
        return SimpleNamespace(
            profile=SimpleNamespace(slug=owner, name=owner.title(), data={}),
            _sessions=object(),
            flags={"sleep": False},
            _pending_photo={},
            event_log=[],
        )

    def test_text_command_runs_brain_after_request_activation_before_core_handoff(self):
        source = inspect.getsource(engine_loop.main)
        command = source.index("_, cmd, source")
        activate = source.index("requests_state.activate", command)
        brain = source.index("brain_entry.prepare", activate)
        handoff = source.index("brain_entry.handoff", brain)
        self.assertLess(command, activate)
        self.assertLess(activate, brain)
        self.assertLess(brain, handoff)

    def test_audio_stt_handoff_preserves_same_rid_for_shared_text_entry(self):
        events = queue.Queue()
        activation = Mock(return_value=nullcontext())
        check = Mock()
        cancel = Mock()
        runtime = SimpleNamespace(
            slugify=lambda value: value.casefold(),
            pc_profile=lambda: SimpleNamespace(name="Hamdi"),
            requests_state=SimpleNamespace(
                is_cancelled=lambda *args: False,
                activate=activation,
                check=check,
                cancel=cancel,
                Cancelled=RuntimeError,
            ),
            as_user=lambda user: nullcontext(),
            llm_transcribe=Mock(return_value="notlarımı göster"),
            _tr_lower=lambda value: value.casefold(),
            emit=Mock(),
            events=events,
            pause_listening=SimpleNamespace(clear=Mock()),
            richtext=SimpleNamespace(speakable=lambda text: text),
            submit=Mock(),
            privacy=SimpleNamespace(audit=Mock()),
            os=SimpleNamespace(remove=Mock()),
        )
        engine_loop._queued_audio(runtime, ("audio", "clip.wav", "telefon", "Hamdi", RID))
        self.assertEqual(events.get_nowait(), ("command", "notlarımı göster", "telefon", "Hamdi", RID))
        activation.assert_called_once_with("hamdi", RID, complete=False)
        check.assert_called()
        cancel.assert_not_called()

    def test_phone_photo_queue_creates_registers_and_carries_canonical_rid(self):
        events = queue.Queue()
        register = Mock(return_value=True)
        runtime = SimpleNamespace(
            pc_profile=lambda: SimpleNamespace(name="Hamdi"),
            slugify=lambda value: value.casefold(),
            secrets=SimpleNamespace(token_hex=lambda size: "photo-rid"),
            requests_state=SimpleNamespace(register=register),
            events=events,
        )
        self.assertTrue(engine_queue.submit_photo(runtime, "photo.jpg", "buna bak"))
        register.assert_called_once_with("hamdi", "photo-rid")
        self.assertEqual(events.get_nowait(), ("photo", "photo.jpg", "buna bak", "telefon", "Hamdi", "photo-rid"))

    def test_photo_loop_activates_same_rid_before_brain_entry(self):
        source = inspect.getsource(engine_loop.main)
        photo = source.index('if kind == "photo"')
        activate = source.index("requests_state.activate", photo)
        brain = source.index("brain_entry.prepare", activate)
        self.assertLess(photo, activate)
        self.assertLess(activate, brain)
        self.assertIn("request_id=rid", source[brain:brain + 400])

    def test_prepare_owner_mismatch_fails_closed(self):
        module = self.module()
        with self.assertRaises(ValueError):
            module.prepare(self.runtime("other"), owner=OWNER, request_id=RID, text="merhaba", source="yazı")

    def test_prepare_request_id_mismatch_fails_closed(self):
        module = self.module()
        wrong = context(request_id="other")
        with patch.object(module.brain_context, "build_active_context", return_value=wrong):
            with self.assertRaises(ValueError):
                module.prepare(self.runtime(), owner=OWNER, request_id=RID, text="merhaba", source="yazı")

    def test_exact_state_gate_runs_before_fast_and_understanding(self):
        module = self.module()
        order = []
        hit = GateObservation(OWNER, RID, "state", True, "BOUNDED_JOB_RESUME", "job.resume", "resume")
        with patch.object(module, "_build_context", side_effect=lambda *a, **k: (order.append("context") or context())), \
             patch.object(module, "_state_refs", return_value=()), \
             patch.object(module, "exact_state_gate", side_effect=lambda **k: (order.append("state") or hit)), \
             patch.object(module, "deterministic_fast_gate", side_effect=lambda **k: (order.append("fast") or None)), \
             patch.object(module, "understand", side_effect=lambda **k: (order.append("understanding") or understanding())):
            result = module.prepare(self.runtime(), owner=OWNER, request_id=RID, text="devam", source="yazı")
        self.assertEqual(order, ["context", "state"])
        self.assertTrue(result.state_gate.matched)

    def test_fast_gate_runs_before_understanding_and_short_circuits_semantics(self):
        module = self.module()
        order = []
        state_miss = GateObservation(OWNER, RID, "state", False, "NO_BOUNDED_STATE_MATCH")
        fast_hit = GateObservation(OWNER, RID, "fast", True, "EXACT_LOCAL_READ", "fast.time.read", "time")
        with patch.object(module, "_build_context", return_value=context()), \
             patch.object(module, "_state_refs", return_value=()), \
             patch.object(module, "exact_state_gate", side_effect=lambda **k: (order.append("state") or state_miss)), \
             patch.object(module, "deterministic_fast_gate", side_effect=lambda **k: (order.append("fast") or fast_hit)), \
             patch.object(module, "understand", side_effect=lambda **k: (order.append("understanding") or understanding())):
            result = module.prepare(self.runtime(), owner=OWNER, request_id=RID, text="saat kaç", source="yazı")
        self.assertEqual(order, ["state", "fast"])
        self.assertTrue(result.fast_gate.matched)

    def test_state_and_fast_miss_reach_candidate_reference_understanding(self):
        module = self.module()
        order = []
        miss_state = GateObservation(OWNER, RID, "state", False, "NO_BOUNDED_STATE_MATCH")
        miss_fast = GateObservation(OWNER, RID, "fast", False, "NO_EXACT_FAST_MATCH")
        candidate = ContextReference(id="n1", kind="note", source="profile.items", owner=OWNER, provenance={"text": "Pompa"})
        semantic = understanding(kind=RequestKind.CAPABILITY, hint="notes.read")
        with patch.object(module, "_build_context", return_value=context()), \
             patch.object(module, "_state_refs", return_value=()), \
             patch.object(module, "exact_state_gate", side_effect=lambda **k: (order.append("state") or miss_state)), \
             patch.object(module, "deterministic_fast_gate", side_effect=lambda **k: (order.append("fast") or miss_fast)), \
             patch.object(module, "build_candidates", side_effect=lambda **k: (order.append("candidates") or (candidate,))), \
             patch.object(module, "resolve_references", side_effect=lambda **k: (order.append("references") or ())), \
             patch.object(module, "understand", side_effect=lambda **k: (order.append("understanding") or semantic)):
            result = module.prepare(self.runtime(), owner=OWNER, request_id=RID, text="notlarımı göster", source="yazı")
        self.assertEqual(order, ["state", "fast", "candidates", "references", "understanding"])
        self.assertIs(result.understanding, semantic)

    def test_model_understanding_runs_once_after_final_candidate_resolution(self):
        module = self.module()
        order = []
        miss_state = GateObservation(OWNER, RID, "state", False, "NO_BOUNDED_STATE_MATCH")
        miss_fast = GateObservation(OWNER, RID, "fast", False, "NO_EXACT_FAST_MATCH")
        candidate = ContextReference(
            id="file-1", kind="file", source="files", owner=OWNER,
            provenance={"path": "C:/Users/hamdi/Documents/rapor.pdf", "name": "rapor.pdf"},
        )
        semantic = understanding(kind=RequestKind.CAPABILITY, hint="files.read")
        with patch.object(module, "_build_context", return_value=context()), \
             patch.object(module, "_state_refs", return_value=()), \
             patch.object(module, "exact_state_gate", return_value=miss_state), \
             patch.object(module, "deterministic_fast_gate", return_value=miss_fast), \
             patch.object(module, "build_candidates", side_effect=lambda **k: (order.append("candidates") or (candidate,))), \
             patch.object(module, "resolve_references", side_effect=lambda **k: (order.append("references") or (candidate,))), \
             patch.object(module, "understand", side_effect=lambda **k: (order.append("understand") or semantic)), \
             patch.object(module, "apply_model_understanding", side_effect=lambda value, text, **kwargs: (order.append("model") or value)) as propose:
            result = module.prepare(
                self.runtime(), owner=OWNER, request_id=RID, text="şu raporu incele",
                source="yazı", model_understanding=True,
            )
        self.assertIs(result.understanding, semantic)
        self.assertEqual(order, ["candidates", "references", "understand", "model"])
        propose.assert_called_once_with(semantic, "şu raporu incele", active_context=context())

    def test_needs_input_short_circuits_core_handler_and_worker_effects(self):
        module = self.module()
        result = entry(module, semantic=understanding(
            kind=RequestKind.CLARIFY, needs_input=True, ambiguities=("multiple target references",)
        ))
        handler = Mock(side_effect=AssertionError("effect/worker çalışmamalı"))
        output, brain_feedback, job_id = module.handoff(self.runtime(), result, handler, "onu aç")
        handler.assert_not_called()
        self.assertIn("netleştir", output.casefold())
        self.assertEqual(brain_feedback.request_id, RID)
        self.assertIsNone(job_id)

    def test_capability_hint_is_advisory_and_never_authority(self):
        module = self.module()
        result = entry(module, semantic=understanding(kind=RequestKind.CAPABILITY, hint="notes.read"))
        proposal = module.core_proposal(result)
        self.assertFalse(_RESERVED.intersection(proposal))
        self.assertEqual(proposal["capability_hint"], "notes.read")
        self.assertIsNone(proposal["manifest_capability_id"])

    def test_canonical_request_does_not_call_legacy_semantic_classifier_twice(self):
        module = self.module()
        legacy = Mock(return_value={"intent": "legacy", "args": {}})
        runtime = self.runtime()
        runtime.route = legacy
        result = entry(module, semantic=understanding())
        with module.bind(result):
            self.assertEqual(module.route_command(runtime, "istek")["intent"], "chat")
            self.assertEqual(module.route_command(runtime, "adım metni")["intent"], "clarify")
        # Kapı yalnız bağlı turn'ün kendi kararını izdüşürür; runtime'e bağlı bir yoruma gitmez.
        legacy.assert_not_called()
        self.assertEqual(module.route_command(runtime, "legacy request")["intent"], "clarify")
        legacy.assert_not_called()

    def test_feedback_and_core_handoff_keep_same_request_identity(self):
        module = self.module()
        result = entry(module, semantic=understanding(kind=RequestKind.CAPABILITY))
        handler = Mock(return_value="Core sonucu")
        with patch.object(module, "_install_core_guards"), patch.object(module, "_correlated_job_id", return_value=None):
            output, brain_feedback, job_id = module.handoff(self.runtime(), result, handler, "işlem")
        handler.assert_called_once_with("işlem")
        self.assertEqual(output, "Core sonucu")
        self.assertEqual(brain_feedback.owner, OWNER)
        self.assertEqual(brain_feedback.request_id, RID)
        self.assertIsNone(job_id)

    def test_execution_metadata_uses_same_rid_and_has_no_authority(self):
        module = self.module()
        result = entry(module, semantic=understanding(kind=RequestKind.CAPABILITY, hint="files.read"))
        with module.bind(result):
            metadata = module.execution_metadata(OWNER)
        self.assertEqual(metadata["request_id"], RID)
        self.assertFalse(_RESERVED.intersection(metadata))

    def test_goal_execution_save_guard_adds_metadata_not_goal_authority(self):
        module = self.module()
        from modules import goal_executor
        result = entry(module, semantic=understanding(kind=RequestKind.CAPABILITY))
        original = goal_executor._save
        marker = Mock()
        had_flag = getattr(goal_executor, "_brain_save_guard_installed", False)
        had_legacy = hasattr(goal_executor, "_brain_legacy_save")
        old_legacy = getattr(goal_executor, "_brain_legacy_save", None)
        old_flag = getattr(goal_executor, "_brain_gate_guard_installed", None)
        try:
            if hasattr(goal_executor, "_brain_save_guard_installed"):
                delattr(goal_executor, "_brain_save_guard_installed")
            goal_executor._save = marker
            module._install_goal_save_guard()
            job = {"id": "0" * 16, "owner": OWNER, "request": "x", "state": "running", "goals": [], "steps": [], "outputs": {}}
            with module.bind(result):
                goal_executor._save(job)
            self.assertEqual(job["brain"]["request_id"], RID)
            self.assertFalse(_RESERVED.intersection(job["brain"]))
            marker.assert_called_once_with(job)
        finally:
            goal_executor._save = original
            if hasattr(goal_executor, "_brain_save_guard_installed"):
                delattr(goal_executor, "_brain_save_guard_installed")
            if had_flag:
                goal_executor._brain_save_guard_installed = True
            if had_legacy:
                goal_executor._brain_legacy_save = old_legacy
            elif hasattr(goal_executor, "_brain_legacy_save"):
                delattr(goal_executor, "_brain_legacy_save")
            if old_flag is not None:
                goal_executor._brain_gate_guard_installed = old_flag

    def test_photo_artifact_cannot_cross_owner(self):
        module = self.module()
        photo = module.photo_artifact(owner="other", request_id=RID, path="C:/photo.jpg")
        with self.assertRaises(ValueError):
            module.prepare(self.runtime(), owner=OWNER, request_id=RID, text="buna bak", source="telefon", artifact=photo)

    def test_weather_pending_does_not_steal_job_continue(self):
        module = self.module()
        weather = ContextReference(
            id="pending_weather_location", kind="pending_state", source="session_state", owner=OWNER,
            provenance={"field": "pending_weather_location", "value": True},
        )
        job = ContextReference(
            id="job-1", kind="task_job", source="task_agents", owner=OWNER,
            provenance={"state": "incomplete", "updated": 1},
        )
        active = context(pending=(weather,))
        with patch.object(module, "_build_context", return_value=active), patch.object(module, "_state_refs", return_value=(job,)):
            result = module.prepare(self.runtime(), owner=OWNER, request_id=RID, text="devam", source="yazı")
        self.assertTrue(result.state_gate.matched)
        self.assertEqual(result.state_gate.protocol, "job.resume")

    def test_fast_gate_suffix_regression_stays_closed(self):
        result = deterministic_fast_gate(
            owner=OWNER, request_id=RID, text="Jarvis'i kapatma", active_context=context(), source="yazı"
        )
        self.assertFalse(result.matched)
        self.assertNotEqual(result.protocol, "fast.engine.close")

    def test_entry_and_feedback_contracts_never_expose_authority_fields(self):
        module = self.module()
        result = entry(module)
        self.assertFalse(_RESERVED.intersection(result.to_dict()))
        brain_feedback = module.feedback(result, result_status="handled", reason_code="CORE_HANDOFF_RETURNED")
        self.assertEqual(brain_feedback.request_id, RID)
        self.assertFalse(_RESERVED.intersection(brain_feedback.to_dict()))


if __name__ == "__main__":
    unittest.main()
