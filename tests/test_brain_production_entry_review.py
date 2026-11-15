from __future__ import annotations
from modules import core_brain_adapter

import contextlib
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modules import brain_entry, engine_loop
from modules.brain_contracts import ActiveContext, Confidence, ContextReference, RequestKind, TemporalNeed, UnderstandingResult
from modules.brain_gates import GateObservation, deterministic_fast_gate

OWNER = "hamdi"
RID = "req-production-review"


class _StopAfterCanonicalHandoff(BaseException):
    pass


def _context(*, pending=()) -> ActiveContext:
    return ActiveContext(owner=OWNER, request_id=RID, pending_references=tuple(pending))


def _semantic() -> UnderstandingResult:
    return UnderstandingResult(
        owner=OWNER,
        request_id=RID,
        request_kind=RequestKind.CHAT,
        arguments={"original_text": "selam"},
        temporal_need=TemporalNeed.UNSURE,
        confidence=Confidence.MEDIUM,
    )


def _entry(*, text="selam", pending=(), fast=None):
    return brain_entry.EntryResult(
        owner=OWNER,
        request_id=RID,
        source="yazı",
        text=text,
        active_context=_context(pending=pending),
        state_gate=GateObservation(OWNER, RID, "state", False, "NO_BOUNDED_STATE_MATCH"),
        fast_gate=fast or GateObservation(OWNER, RID, "fast", False, "NO_EXACT_FAST_MATCH"),
        understanding=_semantic(),
    )


def _fast(text: str, *, source: str = "yazı") -> GateObservation:
    return deterministic_fast_gate(
        owner=OWNER,
        request_id=RID,
        text=text,
        active_context=_context(),
        sleeping=False,
        source=source,
    )


class BrainProductionEntryReviewTests(unittest.TestCase):
    def test_plain_chat_without_open_pending_uses_existing_core_handler(self):
        runtime = SimpleNamespace(profile=SimpleNamespace(slug=OWNER))
        handler = Mock(return_value="Merhaba")
        row = _entry()
        with patch.object(core_brain_adapter, "_correlated_job_id", return_value=None), \
             patch("modules.engine_intents.dispatch", side_effect=AssertionError("normal CHAT existing handler'ı bypass etmemeli")):
            output, feedback, job_id = core_brain_adapter.handoff(runtime, row, handler, "selam")
        handler.assert_called_once_with("selam")
        self.assertEqual(output, "Merhaba")
        self.assertEqual(feedback.request_id, RID)
        self.assertIsNone(job_id)

    def test_open_pending_slot_does_not_veto_the_handler_and_its_consumer_stays_fenced(self):
        pending = ContextReference(
            id="pending_weather_location",
            kind="pending_state",
            source="session_state",
            owner=OWNER,
            provenance={"field": "pending_weather_location", "value": True},
        )
        row = _entry(pending=(pending,))
        # Slot presence is inventory, not relation authority: an independent chat keeps the
        # existing handler path (Brain-unmapped legacy owners such as weather/screenshot live there).
        self.assertTrue(brain_entry._use_existing_handler(row))
        # Safety comes from the canonical consumer fence, not from blocking the whole handler.
        with brain_entry.bind(row):
            self.assertFalse(brain_entry.pending_answer_owned("pending_weather_location"))

    def test_bound_fast_miss_does_not_reenable_legacy_engine_control(self):
        row = _entry(text="Jarvis'i kapatma")
        self.assertFalse(brain_entry.allow_legacy_engine_control(row))

        close_hit = GateObservation(
            OWNER, RID, "fast", True, "EXACT_ENGINE_CONTROL", "fast.engine.close", "close"
        )
        self.assertTrue(brain_entry.allow_legacy_engine_control(_entry(text="Jarvis'i kapat", fast=close_hit)))

    def test_installed_engine_control_guard_obeys_canonical_fast_observation(self):
        from modules import command_manager
        close = Mock(return_value='legacy effect')
        original = command_manager.engine_control
        self.assertFalse(hasattr(brain_entry, "_install_engine_control_guard"))
        self.assertIs(command_manager.engine_control, original)
        with brain_entry.bind(_entry(text="Jarvis'i kapatma")):
            self.assertIsNone(original("jarvis'i kapatma", source='yazı', sleeping=False,
                                       close=close, set_sleep=Mock()))
        close.assert_not_called()
        hit = GateObservation(OWNER, RID, 'fast', True, 'EXACT_ENGINE_CONTROL', 'fast.engine.close', 'close')
        with brain_entry.bind(_entry(text="Jarvis'i kapat", fast=hit)):
            self.assertEqual(original("jarvis'i kapat", source='yazı', sleeping=False,
                                      close=close, set_sleep=Mock()), 'legacy effect')
        close.assert_called_once()

    def _assert_loop_fast_miss_reaches_handoff_without_close_effect(self, command: str, source: str = "yazı") -> None:
        import test_engine_modular

        runtime = test_engine_modular.ModularEngineTests.context(self)
        user = runtime.profile.name
        runtime.list_users = lambda: [user]
        runtime.requests_state = SimpleNamespace(
            is_cancelled=lambda *args: False,
            activate=lambda *args, **kwargs: contextlib.nullcontext(),
            Cancelled=type("Cancelled", (Exception,), {}),
        )
        runtime.as_user = lambda selected: contextlib.nullcontext()
        runtime.emit = Mock()
        runtime._finalize = lambda text: text
        runtime._emit_route = Mock()
        runtime._start_hang_watch = Mock()
        runtime.profile.log_agent = Mock()
        runtime.threading = SimpleNamespace(Thread=Mock(), Timer=Mock())
        runtime.time = SimpleNamespace(
            time=time.time,
            sleep=lambda seconds: None,
            strftime=time.strftime,
            localtime=time.localtime,
        )
        runtime._llm = SimpleNamespace(set_history_seed=Mock(), take_route=Mock())
        runtime.events.put(("command", command, source, user, RID))
        voice = SimpleNamespace(
            manual_local_stt=False,
            listening_enabled=False,
            speak_enabled=False,
            state={},
            speak=Mock(),
            read_keyboard=Mock(),
        )
        handoff = Mock()

        def stop_after_handoff(*args, **kwargs):
            self.assertFalse(runtime.stop_event.is_set(), f"{command!r} canonical handoff öncesi stop_event set edilmemeli")
            raise _StopAfterCanonicalHandoff()

        handoff.side_effect = stop_after_handoff
        with patch("modules.engine_voice.VoiceSession", return_value=voice), \
             patch("instance.take_over", return_value=False), \
             patch("updater.pop_notice", return_value=None), \
             patch("modules.perf.start"), \
             patch("modules.task_queue.start"), \
             patch("modules.webhook_server.start"), \
             patch("release_guard.ready"), \
             patch.object(brain_entry, "prepare", return_value=_entry(text=command)), \
             patch.object(core_brain_adapter, "handoff", handoff):
            with self.assertRaises(_StopAfterCanonicalHandoff):
                engine_loop.main(runtime, ui=Mock())
        handoff.assert_called_once()

    def test_typed_bare_kapat_fast_miss_reaches_canonical_handoff_without_direct_stop(self):
        self.assertFalse(_fast("kapat", source="yazı").matched)
        self._assert_loop_fast_miss_reaches_handoff_without_close_effect("kapat", "yazı")

    def test_typed_bare_cik_fast_miss_reaches_canonical_handoff_without_direct_stop(self):
        self.assertFalse(_fast("çık", source="yazı").matched)
        self._assert_loop_fast_miss_reaches_handoff_without_close_effect("çık", "yazı")

    def test_close_fast_grammar_stays_exact_and_preserves_phone_voice_boundaries(self):
        for text, source in (
            ("kapat", "yazı"),
            ("çık", "yazı"),
            ("kapat", "ses"),
            ("Jarvis'i kapatma", "yazı"),
            ("Jarvis'i kapatmak", "yazı"),
            ("Jarvis kapanma", "yazı"),
            ("Jarvis çıkma", "yazı"),
            ("Jarvis sonlandırma", "yazı"),
            ("Jarvis'i kapat", "telefon"),
        ):
            with self.subTest(text=text, source=source):
                self.assertFalse(_fast(text, source=source).matched)

        hit = _fast("Jarvis'i kapat", source="yazı")
        self.assertTrue(hit.matched)
        self.assertEqual(hit.protocol, "fast.engine.close")
        self.assertEqual(hit.selection, "close")


if __name__ == "__main__":
    unittest.main()
