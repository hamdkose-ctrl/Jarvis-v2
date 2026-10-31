"""PR7 Closeout-B3c-3: notes.read -> Core notes_read (read-only; all notes or one resolved note id)."""
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import test_brain_closeout_a  # noqa: F401  (shared test stubs)
import test_brain_production_entry as fx
from modules import brain_core_map, brain_entry, brain_precedence, brain_understanding, engine_runtime, requests_state
from modules.brain_contracts import ContextReference


def note_ref(ident, text="alışveriş listesi"):
    return ContextReference(id=str(ident), kind="note", source="profile.items", owner=fx.OWNER,
                            provenance={"collection": "items", "text": text})


class UnderstandingTests(unittest.TestCase):
    def understand(self, text, refs=()):
        return brain_understanding.understand(owner=fx.OWNER, request_id=fx.RID, text=text, active_context=fx.context(),
                                              candidates=tuple(refs), references=tuple(refs))

    def test_plural_show_proposes_all(self):
        for text in ("notlarımı göster", "notları göster"):
            result = self.understand(text)
            self.assertEqual(result.capability_hint, "notes.read", text)
            self.assertEqual(result.arguments["notes"], {"which": "all"}, text)

    def test_single_resolved_note_proposes_its_id(self):
        result = self.understand("notu göster", [note_ref("n7")])
        self.assertEqual(result.arguments.get("notes"), {"which": "one", "id": "n7"})

    def test_no_or_many_references_for_singular_propose_nothing(self):
        self.assertNotIn("notes", self.understand("notu göster").arguments)
        self.assertNotIn("notes", self.understand("notu göster", [note_ref("a"), note_ref("b")]).arguments)

    def test_other_verbs_or_second_action_stay_legacy(self):
        for text in ("notlarımı özetle", "notlarımı göster ve sil", "notlarımı listele"):
            self.assertNotIn("notes", self.understand(text).arguments, text)


class CoreValidationTests(unittest.TestCase):
    def test_core_revalidates(self):
        self.assertEqual(brain_core_map.core_plan("notes.read", {"notes": {"which": "all"}}),
                         ("notes_read", {"which": "all"}))
        self.assertEqual(brain_core_map.core_plan("notes.read", {"notes": {"which": "one", "id": " n7 "}}),
                         ("notes_read", {"which": "one", "id": "n7"}))
        for bad in ({}, {"notes": {"which": "one"}}, {"notes": {"which": "all", "id": "x"}},
                    {"notes": {"which": "delete"}}, {"notes": {"which": "one", "id": 7}},
                    {"notes": {"which": "all", "extra": 1}}, {"notes": "all"}):
            self.assertIsNone(brain_core_map.core_plan("notes.read", bad), bad)

    def test_hint_owner_is_core(self):
        self.assertEqual(brain_core_map.hint_owner("notes.read"), "core:notes_read")


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with patch.object(engine_runtime, "DATA_DIR", Path(self.temp.name)):
            self.ctx = engine_runtime.EngineContext()
        self.addCleanup(self.ctx._prefetch_pool.shutdown, wait=False, cancel_futures=True)
        self.owner = self.ctx.profile.slug
        self.ctx.system_control = Mock(windows_settings=Mock(return_value=None))
        guard = patch.object(brain_entry, "_install_core_guards", lambda runtime: None)
        guard.start()
        self.addCleanup(guard.stop)
        self.ctx.profile.data["items"] = []
        self.first = self.ctx.profile.add_note_item("süt al")
        self.second = self.ctx.profile.add_note_item("diş randevusu")

    def through_brain(self, text):
        rid = "b3c3-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı")
            handle = Mock(wraps=self.ctx.handle)
            out, feedback, _ = brain_entry.handoff(self.ctx, entry, handle, text)
        return entry, out, handle

    def test_all_notes_read_through_core_without_mutation(self):
        before = [dict(n) for n in self.ctx.profile.data["items"]]
        with patch.object(brain_precedence, "claim", return_value=None):
            entry, out, handle = self.through_brain("notlarımı göster")
        self.assertIn("süt al", out)
        self.assertIn("diş randevusu", out)
        self.assertFalse(handle.called)
        self.assertEqual(before, [dict(n) for n in self.ctx.profile.data["items"]])

    def test_unknown_note_id_is_reported_not_guessed(self):
        from modules import engine_intents
        out = engine_intents.dispatch(self.ctx, "notes_read", {"which": "one", "id": "yok"}, "x", "x")
        self.assertEqual(out, "Bu notu bulamadım.")

    def test_one_note_by_id_returns_that_note_only(self):
        from modules import engine_intents
        out = engine_intents.dispatch(self.ctx, "notes_read", {"which": "one", "id": self.second["id"]}, "x", "x")
        self.assertIn("diş randevusu", out)
        self.assertNotIn("süt al", out)


if __name__ == "__main__":
    unittest.main()
