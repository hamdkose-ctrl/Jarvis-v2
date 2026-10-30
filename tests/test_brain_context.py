from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from modules.brain_contracts import ActiveContext
from modules.brain_context import build_active_context


class _SessionStore:
    def __init__(self, states=None):
        self._states = dict(states or {})
        self._lock = threading.RLock()
        self.get = Mock(side_effect=AssertionError("builder SessionStore.get çağırmamalı"))
        self.for_owner = Mock(side_effect=AssertionError("builder SessionStore.for_owner çağırmamalı"))


class BrainContextTests(unittest.TestCase):
    def _profile(self, owner="hamdi", *, city="İstanbul", hoca=None):
        data = {"prefs": {"city": city} if city else {}}
        if hoca is not None:
            data["hoca"] = {"lesson": hoca}
        return SimpleNamespace(slug=owner, data=data, save=Mock())

    def _build(self, **kwargs):
        defaults = {
            "owner": "hamdi",
            "request_id": "req-17",
            "history_reader": lambda owner, limit: [],
            "history_filter": lambda owner, rows: list(rows),
            "goal_reader": lambda owner: None,
            "goal_is_open": lambda row: False,
        }
        defaults.update(kwargs)
        return build_active_context(**defaults)

    @staticmethod
    def _all_refs(context):
        return (
            context.active_goal_references
            + context.active_task_references
            + context.recent_references
            + context.active_artifacts
            + context.pending_references
            + context.memory_references
        )

    def test_empty_owner_is_rejected(self):
        with self.assertRaises(ValueError):
            self._build(owner="")

    def test_empty_request_id_is_rejected(self):
        with self.assertRaises(ValueError):
            self._build(request_id="")

    def test_existing_request_id_is_preserved_exactly(self):
        context = self._build(request_id="rid-from-caller-001")
        self.assertEqual(context.request_id, "rid-from-caller-001")

    def test_cross_owner_state_cannot_enter_snapshot(self):
        other = SimpleNamespace(pending_request={"question": "başkasının"})
        store = _SessionStore({"hasan": other})
        context = self._build(session_store=store)
        self.assertFalse(context.pending_references)

        with self.assertRaises(ValueError):
            self._build(
                history_reader=lambda owner, limit: [
                    {"id": "h-1", "owner": "hasan", "role": "user", "text": "gizli", "ts": "2026-10-30 10:00:00"}
                ]
            )

    def test_session_pending_state_becomes_read_only_reference(self):
        session = SimpleNamespace(pending_request={"question": "Hangi dosya?", "original": "onu aç"})
        context = self._build(session_store=_SessionStore({"hamdi": session}))
        ref = context.pending_references[0]
        self.assertEqual((ref.id, ref.kind, ref.source, ref.owner), ("pending_request", "pending_state", "session_state", "hamdi"))
        self.assertEqual(ref.provenance["field"], "pending_request")
        self.assertEqual(ref.provenance["value"]["question"], "Hangi dosya?")

    def test_session_last_artifact_has_real_source_and_provenance(self):
        session = SimpleNamespace(last_doc=("özet metni", "C:/docs/a.pdf", "ozet"), last_visual=None, last_command="")
        context = self._build(session_store=_SessionStore({"hamdi": session}))
        ref = context.active_artifacts[0]
        self.assertEqual((ref.id, ref.kind, ref.source), ("last_doc", "artifact", "session_state"))
        self.assertEqual(ref.provenance["field"], "last_doc")
        self.assertEqual(ref.provenance["path"], "C:/docs/a.pdf")
        self.assertEqual(ref.provenance["label"], "ozet")

    def test_open_goalstate_is_exposed_as_read_only_reference(self):
        job = {"id": "goal-abc", "state": "running", "updated": 1234}
        context = self._build(goal_reader=lambda owner: job, goal_is_open=lambda row: True)
        ref = context.active_goal_references[0]
        self.assertEqual((ref.id, ref.kind, ref.source), ("goal-abc", "goal", "goal_state"))
        self.assertEqual(ref.provenance["state"], "running")

    def test_stale_or_closed_goalstate_is_not_exposed_as_active(self):
        for state in ("done", "cancelled", "running"):
            with self.subTest(state=state):
                job = {"id": "goal-abc", "state": state}
                context = self._build(goal_reader=lambda owner, row=job: row, goal_is_open=lambda row: False)
                self.assertFalse(context.active_goal_references)

    def test_history_before_reset_is_not_returned(self):
        rows = [
            {"id": "old", "role": "user", "text": "eski", "ts": "2026-10-29 10:00:00"},
            {"id": "new", "role": "assistant", "text": "yeni", "ts": "2026-10-30 10:00:00"},
        ]
        seen = {}

        def reader(owner, limit):
            seen["limit"] = limit
            return rows

        context = self._build(history_reader=reader, history_filter=lambda owner, values: [values[-1]])
        self.assertEqual(seen["limit"], 12)
        self.assertEqual([ref.id for ref in context.recent_references], ["new"])

    def test_active_hoca_lesson_is_read_only_context(self):
        lesson = {
            "topic": "Hücre",
            "active": 0,
            "done": False,
            "steps": [{"title": "Hücre nedir", "goal": "Temeli öğren"}],
            "pending": {"step": 0, "question": "Hücrenin temel birimi nedir?"},
        }
        profile = self._profile(hoca=lesson)
        context = self._build(profile=profile)
        lesson_ref = next(ref for ref in context.active_task_references if ref.source == "profile.hoca")
        pending_ref = next(ref for ref in context.pending_references if ref.source == "profile.hoca")
        self.assertEqual(lesson_ref.id, "lesson")
        self.assertEqual(lesson_ref.provenance["topic"], "Hücre")
        self.assertEqual(pending_ref.id, "lesson.pending")
        self.assertEqual(pending_ref.provenance["question"], "Hücrenin temel birimi nedir?")
        profile.save.assert_not_called()

    def test_source_data_is_not_mutated(self):
        pending = {"question": "Hangi dosya?", "nested": {"items": [1, 2]}}
        lesson = {"topic": "Matematik", "active": 0, "done": False, "steps": [{"title": "A", "goal": "B"}]}
        session = SimpleNamespace(pending_request=pending)
        profile = self._profile(hoca=lesson)
        before_pending = json.loads(json.dumps(pending))
        before_lesson = json.loads(json.dumps(lesson))
        self._build(session_store=_SessionStore({"hamdi": session}), profile=profile)
        self.assertEqual(pending, before_pending)
        self.assertEqual(lesson, before_lesson)

    def test_snapshot_does_not_call_source_write_or_creating_accessors(self):
        session = SimpleNamespace(pending_request={"question": "x"})
        store = _SessionStore({"hamdi": session})
        profile = self._profile()
        self._build(session_store=store, profile=profile)
        store.get.assert_not_called()
        store.for_owner.assert_not_called()
        profile.save.assert_not_called()

    def test_builder_creates_no_second_durable_brain_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = list(root.iterdir())
            self._build(profile=self._profile())
            self.assertEqual(list(root.iterdir()), before)

    def test_same_input_state_produces_deterministic_snapshot(self):
        session = SimpleNamespace(
            pending_request={"question": "Hangi dosya?"},
            last_doc=("özet", "C:/docs/a.pdf", "ozet"),
            last_visual=None,
            last_command="son komut",
        )
        rows = [{"id": "h-1", "role": "user", "text": "merhaba", "ts": "2026-10-30 10:00:00", "source": "yazı"}]
        kwargs = {
            "session_store": _SessionStore({"hamdi": session}),
            "profile": self._profile(),
            "history_reader": lambda owner, limit: rows,
        }
        first = self._build(**kwargs).to_dict()
        second = self._build(**kwargs).to_dict()
        self.assertEqual(first, second)

    def test_unavailable_source_is_fail_safe_and_explained(self):
        def broken(*args, **kwargs):
            raise OSError("secret path must not leak")

        context = self._build(history_reader=broken, goal_reader=broken)
        status = [ref for ref in self._all_refs(context) if ref.kind == "source_status"]
        self.assertEqual({ref.source for ref in status}, {"history", "goal_state"})
        self.assertTrue(all(ref.provenance["reason_code"] == "SOURCE_UNAVAILABLE" for ref in status))
        self.assertNotIn("secret path", json.dumps(context.to_dict(), ensure_ascii=False))

    def test_callable_or_executable_objects_never_enter_snapshot(self):
        session = SimpleNamespace(pending_request={"question": "x", "callback": lambda: None})
        context = self._build(session_store=_SessionStore({"hamdi": session}))
        payload = context.to_dict()
        json.dumps(payload, ensure_ascii=False, allow_nan=False)
        text = repr(payload)
        self.assertNotIn("function", text)
        self.assertNotIn("callback", text)

    def test_text_and_live_use_the_same_active_context_serializer(self):
        context = self._build(profile=self._profile())
        self.assertIsInstance(context, ActiveContext)
        text_payload = context.to_dict()
        live_payload = context.to_dict()
        self.assertEqual(text_payload, live_payload)
        self.assertEqual(set(text_payload), {field.name for field in __import__("dataclasses").fields(ActiveContext)})


if __name__ == "__main__":
    unittest.main()
