"""VOICE: explicit new independent goals must use the existing Scheduler.

The caller chooses a typed CREATE protocol ("yeni hedef: ..."), while the
free-form goal body is planned only by the already installed canonical worker.
No second engine, user-profile switch, LLM or unapproved effect executes here.
"""
from __future__ import annotations

import queue
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from modules import (
    brain_entry, canonical_planning_queue, engine_queue, execution_record,
    goal_executor, goal_state_store, llm, requests_state, task_queue,
)
from modules.engine_voice import VoiceSession


class IndependentGoalAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pc = SimpleNamespace(name="Alice", slug="alice", exists=True)
        self.bob = SimpleNamespace(name="Bob", slug="bob", exists=True)
        self.records = {}
        self.stack = self.enterContext(patch.object(goal_executor, "STORE", self.root / "goals"))
        self.enterContext(patch.object(requests_state, "_journal", self.root / "requests.json"))
        self.enterContext(patch.object(requests_state, "_records", self.records))
        self.enterContext(patch.object(task_queue, "scheduler_active", return_value=True))
        self.runtime = SimpleNamespace(
            _tr_lower=str.casefold,
            slugify=str.casefold,
            pc_profile=lambda: self.pc,
            match_user=lambda name: name if name in {"Alice", "Bob"} else None,
            _get_profile=lambda name: self.pc if name == "Alice" else self.bob,
            requests_state=requests_state,
            events=queue.Queue(),
            _emit_for=Mock(),
            _record_failure=Mock(),
            pause_listening=threading.Event(),
            stop_event=threading.Event(),
        )

    def admit(self, text, *, user="Alice", source="yazı", rid="req-1"):
        return engine_queue.submit(self.runtime, text, source=source, user=user, rid=rid)

    def journal(self, owner):
        owner_dir = self.root / "goals" / owner
        return sorted(owner_dir.glob("*.execution.json")) if owner_dir.exists() else []

    def test_independent_goal_during_legacy_foreground_no_model_or_new_scheduler(self):
        busy = threading.Event()
        release = threading.Event()
        lock = threading.RLock()
        def long_turn():
            with lock:
                busy.set()
                release.wait(3)
        thread = threading.Thread(target=long_turn)
        thread.start()
        self.assertTrue(busy.wait(1))
        request = "İstanbul belediye kararlarını iki kaynakla araştır."
        old_context = llm._key_context.get()
        try:
            with patch.object(brain_entry, "fast_lane",
                              side_effect=AssertionError("No model inference")), \
                 patch.object(task_queue, "start",
                              side_effect=AssertionError("No second Scheduler")), \
                 patch.object(goal_executor, "run",
                              side_effect=AssertionError("No legacy executor")):
                self.assertTrue(self.admit("Yeni bağımsız hedef: " + request))
            self.assertFalse(release.is_set(), "input waited for the foreground turn")
            self.assertEqual(llm._key_context.get(), old_context)
            self.assertTrue(self.runtime.events.empty())
            files = self.journal("alice")
            self.assertEqual(len(files), 1)
            job_id = files[0].name.removesuffix(".execution.json")
            record = execution_record.load(files[0].parent, "alice", job_id)
            state = goal_state_store.load(files[0].parent / (job_id + ".goalstate.json"))
            self.assertEqual(record["owner"], "alice")
            self.assertEqual(record["request"], request)
            self.assertEqual(record["request_id"], "req-1")
            self.assertEqual(record["state"], "planning_queued")
            self.assertEqual(state["state"], "pending")
            self.assertNotIn("goal_plan", state)  # no model executed on front thread
            self.assertIn("kuyruğuna aldım", self.runtime._emit_for.call_args.args[2])
            self.assertFalse(self.admit("Yeni bağımsız hedef: " + request),
                             "duplicate RID must not publish a second job")
            self.assertEqual(len(self.journal("alice")), 1)
        finally:
            release.set()
            thread.join(2)

    def test_bob_is_owner_pinned_not_current_pc_profile(self):
        old_context = llm._key_context.get()
        with patch.object(brain_entry, "fast_lane",
                          side_effect=AssertionError("Never run model in admission")):
            self.assertTrue(self.admit("Yeni hedef: Kendi belgelerimi araştır.",
                                       user="Bob", source="telefon", rid="bob-rid"))
        self.assertEqual(llm._key_context.get(), old_context)
        self.assertEqual(len(self.journal("bob")), 1)
        self.assertEqual(self.journal("alice"), [])
        self.assertEqual(self.runtime._emit_for.call_args.args[0], self.bob)
        self.assertTrue(self.runtime.events.empty())

    def test_non_registered_remote_owner_cannot_create_a_goal(self):
        self.runtime.match_user = lambda name: None
        self.assertTrue(self.admit("Yeni hedef: Gizli dosyalar.",
                                   user="Bob", source="telefon", rid="unknown-rid"))
        self.assertEqual(self.journal("bob"), [])
        self.assertEqual(self.journal("alice"), [])
        self.assertIn("Kullanıcı kimliği doğrulanamadı",
                      self.runtime._emit_for.call_args.args[2])

    def test_scheduler_down_does_not_fall_back_to_effectful_legacy_executor(self):
        with patch.object(task_queue, "scheduler_active", return_value=False), \
             patch.object(goal_executor, "run",
                          side_effect=AssertionError("No legacy fallback")):
            self.assertTrue(self.admit("Yeni hedef: Dosya hazırla.",
                                      rid="scheduler-down"))
        self.assertEqual(self.journal("alice"), [])
        self.assertTrue(self.runtime.events.empty())
        self.assertIn("hazır değil", self.runtime._emit_for.call_args.args[2])

    def test_empty_goal_is_refused_without_creating_a_job(self):
        self.assertTrue(self.admit("Yeni hedef:   ", rid="empty-goal"))
        self.assertEqual(self.journal("alice"), [])
        self.assertIn("somut", self.runtime._emit_for.call_args.args[2])

    def test_free_form_statement_without_explicit_create_stays_with_brain(self):
        with patch.object(brain_entry, "fast_lane", return_value=None):
            self.assertTrue(self.admit("Yeni bir şey araştırmak istiyorum.",
                                       rid="ambiguous-turn"))
        self.assertEqual(self.journal("alice"), [])
        self.assertEqual(self.runtime.events.get_nowait(),
                         ("command", "Yeni bir şey araştırmak istiyorum.",
                          "yazı", "Alice", "ambiguous-turn"))
        self.runtime._emit_for.assert_not_called()

    def test_voice_inline_admission_reopens_microphone_after_reply(self):
        self.runtime.submit=lambda text, source: self.admit(
            text, source=source, rid="voice-create",
        )
        session=VoiceSession.__new__(VoiceSession)
        session.runtime=self.runtime
        with patch.object(brain_entry,"fast_lane",
                          side_effect=AssertionError("No semantic front wait")):
            self.assertTrue(session.submit_voice("Yeni hedef: İki açık kaynağı karşılaştır."))
        self.assertFalse(self.runtime.pause_listening.is_set())
        self.assertEqual(len(self.journal("alice")), 1)
        self.assertTrue(self.runtime.events.empty())

    def test_duplicate_background_goal_claim_is_still_idempotent(self):
        # Two independent request IDs are two jobs; reusing one ID does not
        # re-run the provider or publish a second GoalState record.
        a="Yeni hedef: Birinci soruyu araştır."
        b="Yeni hedef: İkinci soruyu araştır."
        self.assertTrue(self.admit(a, rid="unique-a"))
        self.assertTrue(self.admit(b, rid="unique-b"))
        self.assertFalse(self.admit(a, rid="unique-a"))
        self.assertEqual(len(self.journal("alice")), 2)
        self.assertEqual(len(canonical_planning_queue.discover("alice")), 2)


if __name__ == "__main__":
    unittest.main()
