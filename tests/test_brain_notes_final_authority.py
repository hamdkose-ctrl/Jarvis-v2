"""PR7 final notes authority: canonical Brain owns note read synonyms and named target selection."""
from modules import core_brain_adapter
import dataclasses
import tempfile
import unittest
import uuid
from pathlib import Path
from contextlib import nullcontext
from unittest.mock import Mock, patch

import test_brain_closeout_a  # noqa: F401
from modules import brain_core_map, brain_entry, engine_intents, engine_runtime, requests_state
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
        from modules import main_planner
        if forbid_legacy_lookup:
            self.assertFalse(hasattr(main_planner, "_note_lookup"))
        with requests_state.activate(self.owner, rid), nullcontext():
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı")
            out, feedback, _ = core_brain_adapter.handoff(self.ctx, entry, handler, text)
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
            out, feedback, _ = core_brain_adapter.handoff(self.ctx, entry, handler, command)
        self.assertIn("ekranı paylaş", out)
        self.assertEqual(feedback.result_status, "handled")
        self.assertFalse(handler.called)
        share.assert_not_called()

    def test_typed_screen_share_uses_existing_single_worker(self):
        plan = brain_core_map.core_plan("device.share", {"action": "screen"})
        self.assertEqual(plan, ("share_control", {"action": "screen"}))
        self.assertFalse(hasattr(self.ctx, "_user_controls"))
        with patch.object(self.ctx, "set_share", return_value="PAYLASIM") as share, \
             patch("modules.requests_state.check"):
            reply = engine_intents.dispatch(self.ctx, *plan, "ekranı paylaş", "ekranı paylaş")
        self.assertEqual(reply, "PAYLASIM")
        share.assert_called_once_with("screen")

    def test_typed_note_update_does_not_trigger_previous_table_followup(self):
        note = self.add("market listesi süt")
        with patch.object(self.ctx, "_file_command",
                          side_effect=AssertionError("untyped table followup ran")) as raw:
            entry, out, feedback, handler = self.through_brain(
                "market notunu düzelt: tabloyu Word'de ver",
                forbid_legacy_lookup=True,
            )
        self.assertEqual(entry.understanding.capability_hint, "notes.write")
        self.assertEqual(entry.understanding.arguments.get("notes"), {
            "operation": "update", "id": str(note["id"]), "text": "tabloyu Word'de ver",
        })
        self.assertEqual(note["text"], "tabloyu Word'de ver")
        self.assertEqual(feedback.result_status, "handled")
        self.assertFalse(handler.called)
        raw.assert_not_called()

    def test_unplanned_table_followup_does_not_reenter_raw_file_owner(self):
        from modules import brain_precedence
        with patch.object(self.ctx, "_file_command",
                          side_effect=AssertionError("raw table followup executed")) as raw:
            claimed = brain_precedence.claim(self.ctx, "tabloyu Word'de ver")
        self.assertIsNone(claimed)
        raw.assert_not_called()

    def test_explicit_quoted_path_ui_file_command_stays_authoritative(self):
        from modules import brain_precedence
        ui = '"C:\\Temp\\report.docx" özetle'
        self.assertIsNotNone(self.ctx._FILE_CMD.match(ui))
        with patch.object(self.ctx, "_file_command", return_value="UI FILE") as raw:
            claimed = brain_precedence.claim(self.ctx, ui, ("notes_read", {"which": "all"}))
        self.assertEqual(claimed, ("file_command", "UI FILE"))
        raw.assert_called_once_with(ui)

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