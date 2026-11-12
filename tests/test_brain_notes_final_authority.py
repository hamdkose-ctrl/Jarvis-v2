"""PR7 final notes authority: canonical Brain owns note read synonyms and named target selection."""
import dataclasses
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import test_brain_closeout_a  # noqa: F401
from modules import brain_entry, engine_runtime, requests_state
from modules.brain_contracts import RequestKind


class NotesFinalAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with patch.object(engine_runtime, "DATA_DIR", Path(self.temp.name)):
            self.ctx = engine_runtime.EngineContext()
        self.addCleanup(self.ctx._prefetch_pool.shutdown, wait=False, cancel_futures=True)
        self.owner = self.ctx.profile.slug
        self.ctx.system_control = Mock(windows_settings=Mock(return_value=None))
        guard = patch.object(brain_entry, "_install_core_guards", lambda runtime: None)
        guard.start(); self.addCleanup(guard.stop)
        self.ctx.profile.data["items"] = []

    def add(self, text):
        return self.ctx.profile.add_note_item(text)

    def through_brain(self, text, *, forbid_legacy_lookup=False):
        rid = "notes-final-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        handler = Mock(wraps=self.ctx.handle)
        real_lookup = __import__("modules.main_planner", fromlist=["_note_lookup"])._note_lookup
        cm = (patch("modules.main_planner._note_lookup", side_effect=AssertionError("canonical not hedefi legacy resolver'a dönmemeli"))
              if forbid_legacy_lookup else patch("modules.main_planner._note_lookup", wraps=real_lookup))
        with requests_state.activate(self.owner, rid), cm:
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı")
            out, feedback, _ = brain_entry.handoff(self.ctx, entry, handler, text)
        return entry, out, feedback, handler

    def test_read_synonyms_reach_core_without_legacy_planner(self):
        self.add("süt al")
        for text in ("notlarımı oku", "notlarımı say", "notları listele"):
            entry, out, feedback, handler = self.through_brain(text, forbid_legacy_lookup=True)
            self.assertEqual(entry.understanding.capability_hint, "notes.read", text)
            self.assertEqual(entry.understanding.arguments.get("notes"), {"which": "all"}, text)
            self.assertIn("süt al", out, text)
            self.assertFalse(handler.called, text)
            self.assertEqual(feedback.result_status, "handled", text)

    def test_note_read_verbs_do_not_expand_global_file_read_scope(self):
        rid = "notes-scope-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid,
                                        text="rapor.pdf'i oku", source="yazı")
        self.assertNotEqual(entry.understanding.capability_hint, "notes.read")
        self.assertNotEqual(entry.understanding.capability_hint, "files.read")

    def test_named_delete_uses_brain_resolved_stable_id(self):
        market = self.add("market listesi süt ekmek")
        other = self.add("kitap listesi sefiller")
        entry, out, feedback, handler = self.through_brain("market notunu sil", forbid_legacy_lookup=True)
        self.assertEqual(entry.understanding.capability_hint, "notes.write")
        self.assertEqual(entry.understanding.arguments.get("notes"), {"operation": "delete", "id": str(market["id"])})
        self.assertEqual([str(r.id) for r in entry.references if r.kind == "note"], [str(market["id"])])
        self.assertFalse(handler.called)
        self.assertIn("Notu sildim", out)
        self.assertEqual([n["id"] for n in self.ctx.profile.data["items"]], [other["id"]])
        self.assertEqual(feedback.result_status, "handled")

    def test_named_edit_uses_brain_resolved_stable_id_and_exact_new_text(self):
        market = self.add("market listesi süt")
        other = self.add("kitap listesi sefiller")
        entry, out, _feedback, handler = self.through_brain("market notunu düzelt: süt ve ekmek", forbid_legacy_lookup=True)
        self.assertEqual(entry.understanding.capability_hint, "notes.write")
        self.assertEqual(entry.understanding.arguments.get("notes"), {
            "operation": "update", "id": str(market["id"]), "text": "süt ve ekmek",
        })
        self.assertFalse(handler.called)
        rows = {n["id"]: n["text"] for n in self.ctx.profile.data["items"]}
        self.assertEqual(rows[market["id"]], "süt ve ekmek")
        self.assertEqual(rows[other["id"]], "kitap listesi sefiller")
        self.assertIn("Düzelttim", out)


    def _assert_core_note_update_does_not_execute_quoted_control(self, quoted_text):
        market = self.add("market listesi süt")
        self.assertIsNone(self.ctx._session().pending_voice)
        # The old raw user-controls gate would capture sharing/camera and even
        # voice selection before Core dispatch. Guard the effect boundary.
        with patch.object(self.ctx, "set_share",
                          side_effect=AssertionError("quoted note content started capture")) as share:
            entry, out, feedback, handler = self.through_brain(
                "market notunu düzelt: " + quoted_text,
                forbid_legacy_lookup=True,
            )
        self.assertEqual(entry.understanding.capability_hint, "notes.write")
        self.assertEqual(entry.understanding.arguments.get("notes"), {
            "operation": "update", "id": str(market["id"]), "text": quoted_text,
        })
        self.assertFalse(handler.called)
        self.assertEqual(feedback.result_status, "handled")
        self.assertIn("Düzelttim", out)
        self.assertEqual(market["text"], quoted_text)
        self.assertIsNone(self.ctx._session().pending_voice)
        share.assert_not_called()

    def test_core_note_update_screen_phrase_is_only_new_note_text(self):
        self._assert_core_note_update_does_not_execute_quoted_control("ekranı paylaş")

    def test_core_note_update_camera_phrase_is_only_new_note_text(self):
        self._assert_core_note_update_does_not_execute_quoted_control("kamerayı aç")

    def test_core_note_update_voice_phrase_cannot_open_voice_selection(self):
        self._assert_core_note_update_does_not_execute_quoted_control("sesimi değiştir")

    def test_core_notes_read_with_quoted_share_phrase_has_single_core_owner(self):
        # A model-proposed notes read is injected at the same production
        # Understanding seam; Core revalidates the typed payload independently.
        self.add("ekranı paylaş")
        command = "notlarımı oku: 'ekranı paylaş'"
        def propose_read(semantic, text, *, active_context=None):
            return dataclasses.replace(
                semantic, request_kind=RequestKind.CAPABILITY,
                capability_hint="notes.read", arguments={"notes": {"which": "all"}},
                ambiguities=(), needs_input=False,
            )
        rid = "notes-quote-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        handler = Mock(wraps=self.ctx.handle)
        with requests_state.activate(self.owner, rid), \
             patch.object(brain_entry, "apply_model_understanding", side_effect=propose_read), \
             patch.object(self.ctx, "set_share",
                          side_effect=AssertionError("note read started capture")) as share:
            entry = brain_entry.prepare(
                self.ctx, owner=self.owner, request_id=rid, text=command,
                source="yazı", model_understanding=True,
            )
            self.assertEqual(brain_entry.core_plan(entry), ("notes_read", {"which": "all"}))
            out, feedback, _ = brain_entry.handoff(self.ctx, entry, handler, command)
        self.assertIn("ekranı paylaş", out)
        self.assertEqual(feedback.result_status, "handled")
        self.assertFalse(handler.called)
        share.assert_not_called()

    def test_unplanned_screen_share_retains_existing_raw_control_owner(self):
        with patch.object(self.ctx, "set_share", return_value="PAYLASIM") as share:
            reply = self.ctx._user_controls("ekranı paylaş", "ekranı paylaş")
        self.assertEqual(reply, "PAYLASIM")
        share.assert_called_once_with("screen")

    def test_ambiguous_named_delete_never_mutates_or_falls_to_legacy_resolver(self):
        one = self.add("market listesi süt")
        two = self.add("market listesi ekmek")
        entry, out, feedback, handler = self.through_brain("market notunu sil", forbid_legacy_lookup=True)
        self.assertTrue(entry.understanding.needs_input)
        self.assertEqual(feedback.result_status, "needs_input")
        self.assertFalse(handler.called)
        self.assertEqual({n["id"] for n in self.ctx.profile.data["items"]}, {one["id"], two["id"]})
        self.assertIn("netleştir", out.casefold())

    def test_bounded_numbered_and_clear_all_mutations_are_not_reclassified_as_notes_write(self):
        self.add("bir")
        self.add("iki")
        for text in ("2. notu sil", "tüm notları sil"):
            rid = "notes-bounded-" + uuid.uuid4().hex[:8]
            requests_state.register(self.owner, rid)
            with requests_state.activate(self.owner, rid):
                entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı")
            self.assertNotEqual(entry.understanding.capability_hint, "notes.write", text)

    def test_forged_notes_write_id_is_not_a_core_plan(self):
        market = self.add("market listesi süt")
        rid = "notes-forged-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid,
                                        text="market notunu sil", source="yazı")
        self.assertEqual([str(r.id) for r in entry.references if r.kind == "note"], [str(market["id"])])
        forged_semantic = dataclasses.replace(
            entry.understanding,
            arguments={**entry.understanding.arguments,
                       "notes": {"operation": "delete", "id": "forged-note-id"}},
        )
        self.assertIsNone(brain_entry.core_plan(dataclasses.replace(entry, understanding=forged_semantic)))


if __name__ == "__main__":
    unittest.main()