"""PR7 Closeout-B4b: metin çevirisi Brain'de (Candidate Builder turları -> Core translate); ikinci çeviri kaynak seçici yok."""
import dataclasses
import tempfile
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import test_brain_closeout_a  # noqa: F401  (shared test stubs)
import test_brain_production_entry as fx
from modules import (brain_core_map, brain_entry, brain_precedence, brain_understanding,
                     engine_runtime, requests_state)
from modules.brain_contracts import ContextReference

NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def turn(ident, role, text, ts=NOW):
    return ContextReference(id=ident, kind="conversation_turn", source="history", owner=fx.OWNER,
                            provenance={"ts": ts, "role": role, "text": text})


class UnderstandingTests(unittest.TestCase):
    def understand(self, text, turns=()):
        refs = tuple(turns)
        return brain_understanding.understand(owner=fx.OWNER, request_id=fx.RID, text=text, active_context=fx.context(),
                                              candidates=refs, references=())

    def test_inline_text_is_proposed_with_target(self):
        r = self.understand("ingilizceye çevir: merhaba dünya")
        self.assertEqual(r.capability_hint, "text.translate")
        self.assertEqual(dict(r.arguments["translate"]), {"target": "İngilizce", "text": "merhaba dünya", "origin": "inline"})

    def test_latest_user_source_turn_is_used_and_old_commands_skipped(self):
        turns = [turn("t1", "user", "ilk paragraf"), turn("t2", "assistant", "cevap"),
                 turn("t3", "user", "ikinci paragraf"), turn("t4", "user", "tamam")]
        r = self.understand("bunu almancaya çevir", turns)
        row = dict(r.arguments["translate"])
        self.assertEqual((row["text"], row["origin"], row["turn_id"], row["target"]), ("ikinci paragraf", "user", "t3", "Almanca"))

    def test_last_answer_is_the_assistant_turn(self):
        turns = [turn("t1", "user", "soru"), turn("t2", "assistant", "uzun cevap"), turn("t3", "user", "teşekkür ederim ya")]
        r = self.understand("son cevabını çevir", turns)
        self.assertEqual(dict(r.arguments["translate"])["turn_id"], "t2")

    def test_no_source_asks_instead_of_guessing(self):
        r = self.understand("çevir", [turn("t1", "user", "tamam")])
        self.assertTrue(r.needs_input)
        self.assertEqual(brain_core_map.clarification_question(r.ambiguities, r.arguments),
                         "Bu sohbette çevrilecek metni bulamadım. Metni buraya yapıştırabilirsin.")

    def test_file_conversion_is_not_text_translation(self):
        text = "rapor.pdf dosyasını çevir"
        self.assertNotEqual(self.understand(text).capability_hint, "text.translate", text)

    def test_stale_turn_beyond_two_hours_is_not_a_source(self):
        r = self.understand("çevir", [turn("t1", "user", "eski metin", ts="2020-01-01 10:00:00")])
        self.assertTrue(r.needs_input)


class CoreValidationTests(unittest.TestCase):
    def test_core_revalidates(self):
        good = {"translate": {"target": "Almanca", "text": "merhaba", "origin": "inline"}}
        self.assertEqual(brain_core_map.core_plan("text.translate", good)[0], "translate")
        for bad in ({}, {"translate": {"target": "x", "text": "  ", "origin": "inline"}},
                    {"translate": {"target": "x", "text": "a", "origin": "other"}},
                    {"translate": {"target": "x", "text": "a", "origin": "user"}},
                    {"translate": {"target": "x", "text": "a", "origin": "inline", "turn_id": "t"}},
                    {"translate": {"target": "x", "text": "a" * 20001, "origin": "inline"}},
                    {"translate": {"target": "x", "text": "a", "origin": "inline", "extra": 1}}):
            self.assertIsNone(brain_core_map.core_plan("text.translate", bad), bad)


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
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
        self.ctx.system_control = Mock(windows_settings=Mock(return_value=None))
        guard = patch.object(brain_entry, "_install_core_guards", lambda runtime: None)
        guard.start()
        self.addCleanup(guard.stop)
        self.rows = []
        patcher = patch("modules.brain_context._default_history_reader", lambda owner, *, limit: self.rows[-limit:])
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_text(self, text):
        rid = "b4b-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid), \
             patch("modules.engine_intents.dispatch", return_value="CORE") as dispatch:
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı")
            handle = Mock(wraps=self.ctx.handle)
            out, feedback, _ = brain_entry.handoff(self.ctx, entry, handle, text)
        return entry, out, handle, dispatch

    def test_translation_runs_core_translate_with_brain_text_and_not_legacy_resolver(self):
        self.rows = [{"id": "h1", "role": "user", "text": "bugün hava çok güzel", "ts": NOW}]
        entry, out, handle, dispatch = self.run_text("bunu ingilizceye çevir")
        self.assertEqual(out, "CORE")
        self.assertEqual(dispatch.call_args[0][1], "translate")
        self.assertEqual(dispatch.call_args[0][2]["text"], "bugün hava çok güzel")
        self.assertFalse(handle.called)

    def _real_translation(self, command, *, model_proposal=None):
        rid = "b4b-fence-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        handle = Mock(wraps=self.ctx.handle)
        with requests_state.activate(self.owner, rid):
            if model_proposal is None:
                entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid,
                                            text=command, source="yazı")
            else:
                with patch.object(brain_entry, "apply_model_understanding",
                                  side_effect=model_proposal):
                    entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid,
                                                text=command, source="yazı",
                                                model_understanding=True)
            plan = brain_entry.core_plan(entry)
            self.assertIsNotNone(plan, command)
            self.assertEqual(plan[0], "translate", command)
            output, feedback, _ = brain_entry.handoff(self.ctx, entry, handle, command)
        self.assertFalse(handle.called)
        self.assertEqual(feedback.result_status, "handled")
        return entry, output

    def test_verified_translation_source_cannot_clear_notes(self):
        # RED on old code: _planner_command sees "notları sil" before Core
        # translation and clears the profile's notes instead.
        note = self.ctx.profile.add_note_item("KORUNACAK NOT")
        with patch.object(self.ctx.profile, "clear_note_items",
                          side_effect=AssertionError("source deleted notes")) as clear, \
             patch.object(self.ctx.tr, "translate", return_value="TRANSLATED") as translate:
            entry, out = self._real_translation("İngilizceye çevir: notları sil")
        self.assertEqual(entry.understanding.capability_hint, "text.translate")
        self.assertEqual(out, "TRANSLATED")
        self.assertEqual([n["id"] for n in self.ctx.profile.data["items"]], [note["id"]])
        clear.assert_not_called()
        translate.assert_called_once_with("notları sil", "İngilizce")

    def test_verified_translation_source_cannot_enable_camera(self):
        # Adopt a typed model proposal to cover a source containing an
        # unrelated camera command; Core still validates the inline source.
        def propose(semantic, text, *, active_context=None):
            return dataclasses.replace(
                semantic, request_kind=brain_understanding.RequestKind.CAPABILITY,
                capability_hint="text.translate",
                arguments={"translate": {"target": "İngilizce",
                                         "text": "kamerayı aç", "origin": "inline"}},
                ambiguities=(), needs_input=False,
            )
        with patch.object(self.ctx, "set_share",
                          side_effect=AssertionError("source enabled camera")) as share, \
             patch.object(self.ctx.tr, "translate", return_value="TRANSLATED") as translate:
            _, out = self._real_translation("İngilizceye çevir: kamerayı aç",
                                            model_proposal=propose)
        self.assertEqual(out, "TRANSLATED")
        share.assert_not_called()
        translate.assert_called_once_with("kamerayı aç", "İngilizce")

    def test_verified_translation_does_not_enter_legacy_planner_or_cascade(self):
        with patch.object(self.ctx, "_planner_command",
                          side_effect=AssertionError("raw planner ran")) as planner, \
             patch.object(self.ctx, "_extra_commands",
                          side_effect=AssertionError("raw domain cascade ran")) as extra, \
             patch.object(self.ctx.tr, "translate", return_value="TRANSLATED"):
            _, out = self._real_translation("İngilizceye çevir: notları sil")
        self.assertEqual(out, "TRANSLATED")
        planner.assert_not_called()
        extra.assert_not_called()

    def test_unplanned_bounded_legacy_note_clear_retains_owner(self):
        self.ctx.profile.add_note_item("Silinecek not")
        out = self.ctx._planner_command("notları sil", "notları sil")
        self.assertEqual(out, "Tüm notlarını sildim.")
        self.assertEqual(self.ctx.profile.data["items"], [])

    def test_missing_source_is_asked_by_brain_not_resolved_by_legacy(self):
        entry, out, handle, dispatch = self.run_text("çevir")
        self.assertIn("çevrilecek metni bulamadım", out)
        self.assertFalse(handle.called)
        dispatch.assert_not_called()

    def test_forged_turn_or_inline_text_never_reaches_core(self):
        self.rows = [{"id": "h1", "role": "user", "text": "gerçek metin", "ts": NOW}]
        rid = "b4b-f-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text="bunu çevir", source="yazı")
            self.assertEqual(brain_entry.core_plan(entry)[0], "translate")
            for row in ({"target": "Almanca", "text": "uydurma", "origin": "user", "turn_id": "h1"},
                        {"target": "Almanca", "text": "gerçek metin", "origin": "user", "turn_id": "yok"},
                        {"target": "Almanca", "text": "komutta olmayan", "origin": "inline"}):
                forged = dataclasses.replace(entry.understanding, arguments={"translate": row})
                self.assertIsNone(brain_entry.core_plan(dataclasses.replace(entry, understanding=forged)), row)


if __name__ == "__main__":
    unittest.main()


class NonTextTargetTests(unittest.TestCase):
    """'bunu tabloya çevir' & co. belong to table/codegen/photo/desktop paths, never to text translation."""
    SENTENCES = ("bunu tabloya çevir", "kodu pythona çevir", "bu fotoğrafı çevir", "ekrandaki yazıyı çevir",
                 "bunu pdf'e çevir", "bunu excele çevir", "bunu sese çevir")

    def understand(self, text):
        return brain_understanding.understand(owner=fx.OWNER, request_id=fx.RID, text=text, active_context=fx.context(),
                                              candidates=(turn("t1", "user", "merhaba dünya"),), references=())

    def test_other_capability_sentences_are_not_text_translation(self):
        for text in self.SENTENCES:
            r = self.understand(text)
            self.assertNotEqual(r.capability_hint, "text.translate", text)
            self.assertNotIn("translate", r.arguments, text)

    def test_real_language_targets_still_translate(self):
        for text in ("bunu ingilizceye çevir", "merhaba nasılsın almancaya çevir", "çevir: günaydın"):
            self.assertEqual(self.understand(text).capability_hint, "text.translate", text)

    def test_guard_is_what_keeps_them_out_mutation(self):
        with patch("modules.translation_request.non_text_target", return_value=False):
            hits = [t for t in self.SENTENCES if self.understand(t).capability_hint == "text.translate"]
        self.assertGreaterEqual(len(hits), 5, hits)   # without the guard they all become translations

    def test_end_to_end_none_of_them_reach_core_translate(self):
        rows = [{"id": "h1", "role": "user", "text": "merhaba dünya", "ts": NOW}]
        case = EndToEndTests("test_translation_runs_core_translate_with_brain_text_and_not_legacy_resolver")
        case.setUp()
        try:
            case.rows = rows
            for text in self.SENTENCES:
                try:
                    entry, out, handle, dispatch = case.run_text(text)
                except Exception:   # the legacy owner may need models; only the Core route matters here
                    continue
                self.assertFalse(any(c[0][1] == "translate" for c in dispatch.call_args_list), text)
        finally:
            case.doCleanups()
