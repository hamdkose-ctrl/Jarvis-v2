"""PR7 Closeout-B3c-3: notes.read -> Core notes_read (read-only; all notes or one resolved note id)."""
from modules import core_brain_adapter
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
        for text in ("notlarımı göster", "notları göster", "notlarımı oku", "notlarımı say", "notları listele"):
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
        for text in ("notlarımı göster ve sil", "notlarımı göster ve hava durumu nasıl"):
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
        self.ctx.profile.data["items"] = []
        self.first = self.ctx.profile.add_note_item("süt al")
        self.second = self.ctx.profile.add_note_item("diş randevusu")

    def through_brain(self, text):
        rid = "b3c3-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı")
            handle = Mock(wraps=self.ctx.handle)
            out, feedback, _ = core_brain_adapter.handoff(self.ctx, entry, handle, text)
        return entry, out, handle

    def real_claim_run(self, text):
        """prepare -> handoff with the REAL brain_precedence.claim (front gates included)."""
        with patch("modules.engine_intents.dispatch", return_value="CORE") as dispatch:
            entry, out, handle = self.through_brain(text)
        core = dispatch.call_args[0][1:3] if dispatch.called else None
        return entry, out, handle, core

    def test_plural_show_reaches_core_instead_of_selfctl_navigation(self):
        for text in ("notlarımı göster", "notları göster", "notlarımı bana göster"):
            entry, out, handle, core = self.real_claim_run(text)
            self.assertEqual(entry.understanding.arguments["notes"], {"which": "all"}, text)
            self.assertEqual(core, ("notes_read", {"which": "all"}), text)
            self.assertEqual(out, "CORE", text)
            self.assertFalse(handle.called, text)

    def test_single_note_reaches_core_with_its_id_through_real_claim(self):
        self.ctx.profile.data["items"] = [self.second]
        entry, out, handle, core = self.real_claim_run("son notu göster")
        self.assertEqual(core, ("notes_read", {"which": "one", "id": str(self.second["id"])}))
        self.assertEqual(out, "CORE")
        self.assertFalse(handle.called)

    def test_last_note_uses_current_profile_list_position(self):
        entry, out, handle, core = self.real_claim_run("son notu göster")
        self.assertEqual(core, ("notes_read", {"which": "one", "id": str(self.second["id"])}))
        self.assertFalse(entry.understanding.needs_input)

    def test_multi_intent_sentences_get_no_notes_proposal_and_keep_legacy_path(self):
        for text in ("notları göster ve hava durumu nasıl", "notlarımı göster ve not al: süt",
                     "notlarımı göster saat kaç", "notlarımı göster, haberleri oku",
                     "notlarımı göster 5 çarpı 7 kaç", "notlarımı göster sonra hava nasıl"):
            entry, out, handle, core = self.real_claim_run(text)
            self.assertNotIn("notes", entry.understanding.arguments, text)
            self.assertNotEqual((core or ("",))[0], "notes_read", text)

    def test_handoff_rejects_id_not_in_brain_references(self):
        import dataclasses
        self.ctx.profile.data["items"] = [self.second]
        rid = "b3c3-ref-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text="son notu göster", source="yazı")
            self.assertIsNotNone(brain_entry.core_plan(entry))
            forged = dataclasses.replace(entry.understanding, arguments={"notes": {"which": "one", "id": "forged-id"}})
            self.assertIsNone(brain_entry.core_plan(dataclasses.replace(entry, understanding=forged)))

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
