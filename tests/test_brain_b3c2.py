"""PR7 Closeout-B3c-2: reminder creation as a Core intent running at the planner's precedence slot."""
import tempfile
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import test_brain_closeout_a  # noqa: F401  (shared test stubs)
from modules import brain_core_map, brain_entry, brain_precedence, engine_runtime, main_planner, reminder_parse, requests_state
from modules.brain_contracts import ConversationRelation, RequestKind

# (sentence, expected reply prefix, pending_event_title is set?)
TABLE = [
    ("yarın saat 10'da toplantıyı hatırlat", "Takvime ekledim: toplantıyı, yarın 10:00.", False),
    ("bana yarın 9'da ilaç hatırlat", "Takvime ekledim: ilaç, yarın 09:00.", False),
    ("her gün 9'da su içmeyi hatırlat", "Tamam, her gün 09:00 hatırlatacağım: su içmeyi.", False),
    ("hatırlat", "Neyi eklememi istersin?", False),
    ("bana hatırlat", "Neyi eklememi istersin?", False),
    ("her 2 saatte bir su içmeyi hatırlat", "Bu tekrarı anlayamadım", False),
    ("hafta içi her gün 8'de spor hatırlat", "Tamam, hafta içi her gün 08:00 hatırlatacağım: spor.", False),
    ("yarin 9da ilac hatirlat", "Takvime ekledim: ilac, yarın 09:00.", False),
]


class ParserTests(unittest.TestCase):
    def test_creation_detection_matches_the_old_inline_rule(self):
        for text in ("hatırlat", "bana hatırlat", "yarın 9'da ilaç hatırlat", "takvime ekle yarın 10'da dişçi",
                     "yarin 9da ilac hatirlat"):
            self.assertTrue(reminder_parse.is_creation_request(text), text)
        for text in ("toplantıyı hatırlat", "hava nasıl"):
            self.assertFalse(reminder_parse.is_creation_request(text), text)

    def test_single_time_parser_is_modules_when(self):
        parsed = reminder_parse.parse("yarın saat 10'da toplantıyı hatırlat", datetime(2026, 10, 31, 12, 0))
        self.assertEqual((parsed["title"], parsed["when"], parsed["repeat"]), ("toplantıyı", "2026-11-01T10:00", None))

    def test_core_shape_validation(self):
        good = {"reminder": {"title": "ilaç", "when": "2026-11-01T09:00", "repeat": None}}
        self.assertIsNotNone(brain_core_map.core_plan("reminder.propose", good))
        for bad in ({}, {"reminder": {"title": "x", "when": "yarın", "repeat": None}},
                    {"reminder": {"title": "x", "when": None, "repeat": "every:1"}},
                    {"reminder": {"title": "x" * 300, "when": None, "repeat": None}},
                    {"reminder": {"title": "x", "when": None, "repeat": None, "execute": True}},
                    {"reminder": "yarın"}):
            self.assertIsNone(brain_core_map.core_plan("reminder.propose", bad), bad)


class Pipeline(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        with patch.object(engine_runtime, "DATA_DIR", Path(temp.name)):
            self.ctx = engine_runtime.EngineContext()
        self.addCleanup(self.ctx._prefetch_pool.shutdown, wait=False, cancel_futures=True)
        self.ctx.profile.data["events"] = []
        self.owner = self.ctx.profile.slug
        self.ctx.system_control = Mock(windows_settings=Mock(return_value=None))
        guard = patch.object(brain_entry, "_install_core_guards", lambda runtime: None)
        guard.start()
        self.addCleanup(guard.stop)

    def through_brain(self, text):
        rid = "b3c2-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı")
            handle = Mock(wraps=self.ctx.handle)
            out, feedback, _ = brain_entry.handoff(self.ctx, entry, handle, text)
        return entry, out, feedback, handle


class EndToEndTests(Pipeline):
    def test_before_after_table_replies_match_and_core_runs_without_legacy_handler(self):
        for text, prefix, _ in TABLE:
            with self.subTest(text=text):
                self.ctx.profile.data["events"] = []
                self.ctx._session().pending_event_title = None
                entry, out, feedback, handle = self.through_brain(text)
                self.assertEqual(entry.understanding.capability_hint, "reminder.propose")
                self.assertTrue(str(out).startswith(prefix), out)
                self.assertFalse(handle.called)          # Core intent, not raw-text re-interpretation
                self.assertEqual(feedback.result_status, "handled")

    def test_timeless_reminder_with_title_keeps_ne_zaman_flow(self):
        # "hatırlat" opener, title but no time -> same "ne zaman?" question + pending title as before.
        entry, out, feedback, handle = self.through_brain("bana ilaç hatırlat")
        self.assertIn("için ne zaman?", out)
        self.assertEqual(self.ctx._session().pending_event_title, "ilaç")
        self.assertEqual(feedback.result_status, "needs_input")

    def test_conflict_confirmation_flow_is_unchanged(self):
        self.through_brain("yarın saat 10'da toplantıyı hatırlat")
        entry, out, feedback, handle = self.through_brain("yarın saat 10'da toplantıyı hatırlat")
        self.assertIn("kaydını yine de ekleyeyim mi?", out)
        self.assertIsInstance(self.ctx._session().pending_event_title, dict)
        self.assertEqual(len(self.ctx.profile.data["events"]), 1)   # nothing added before approval

    def test_typed_creation_does_not_run_legacy_edit_and_unplanned_edit_survives(self):
        # Former assertion made legacy edit precede a Core-validated CREATE.
        # That is the dangerous second effect owner fixed by BRAIN-03 #599.
        with patch.object(main_planner, "_edit_reminder",
                          side_effect=AssertionError("legacy edit before Core creation")) as edit:
            entry, out, feedback, handle = self.through_brain("yarın saat 10'da toplantıyı hatırlat")
        self.assertEqual(out, "Takvime ekledim: toplantıyı, yarın 10:00.")
        self.assertEqual([e["title"] for e in self.ctx.profile.data["events"]], ["toplantıyı"])
        self.assertFalse(handle.called)
        edit.assert_not_called()

        # Without a Core plan, legacy edit/snooze is still the existing domain owner.
        with patch.object(main_planner, "_edit_reminder", return_value="ERTELENDİ") as edit:
            raw = self.ctx._planner_command("toplantıyı ertele", "toplantıyı ertele")
        self.assertEqual(raw, "ERTELENDİ")
        edit.assert_called_once()

    def test_unquoted_core_reminder_skips_legacy_file_gate(self):
        # An unquoted reminder is already Core-owned. The earlier file gate
        # must not interpret its title as an unrelated Workbench followup.
        # Explicit quoted-path UI commands keep their separate priority.
        with patch.object(self.ctx, "_file_command",
                          side_effect=AssertionError("raw file gate ran")) as raw:
            entry, out, feedback, handle = self.through_brain("yarın saat 10'da toplantıyı hatırlat")
        self.assertEqual(entry.understanding.capability_hint, "reminder.propose")
        self.assertEqual(out, "Takvime ekledim: toplantıyı, yarın 10:00.")
        self.assertEqual([e["title"] for e in self.ctx.profile.data["events"]], ["toplantıyı"])
        self.assertEqual(feedback.result_status, "handled")
        raw.assert_not_called()
        self.assertFalse(handle.called)

    def test_planner_consumes_the_core_validated_arguments_not_its_own_parse(self):
        plan = ("reminder", {"title": "GERÇEK", "when": "2026-11-01T09:00", "repeat": None})
        with patch.object(brain_core_map, "core_plan", return_value=plan):
            entry, out, feedback, handle = self.through_brain("bana yarın 10'da toplantıyı hatırlat")
        self.assertEqual([(e["title"], e["when"]) for e in self.ctx.profile.data["events"]], [("GERÇEK", "2026-11-01T09:00")])

    def run_both(self, text):
        """(brain reply+events, legacy planner reply+events) from identical fresh state."""
        self.ctx.profile.data["events"] = []
        self.ctx._session().pending_event_title = None
        entry, brain_out, _, handle = self.through_brain(text)
        brain = (str(brain_out), [(e["title"], e["when"]) for e in self.ctx.profile.data["events"]], entry.understanding.capability_hint)
        self.ctx.profile.data["events"] = []
        self.ctx._session().pending_event_title = None
        legacy_out = self.ctx._planner_command(text, self.ctx._tr_lower(text))
        legacy = (str(legacy_out), [(e["title"], e["when"]) for e in self.ctx.profile.data["events"]])
        return brain, legacy

    def test_calendar_sentences_behave_exactly_like_the_legacy_planner(self):
        for text in ("takvimi aç ve yarın 10'da toplantı hatırlat", "yarın takvimimde ne var hatırlat",
                     "bu hafta planımı göster ve yarın 9'da ilaç hatırlat"):
            with self.subTest(text=text):
                brain, legacy = self.run_both(text)
                self.assertEqual(brain[2], "reminder.propose", text)
                self.assertEqual(brain[:2], legacy, text)   # nothing dropped, nothing reordered

    def test_note_and_pending_answer_branches_keep_priority_over_reminder_creation(self):
        entry, out, feedback, handle = self.through_brain("not al: yarın 9'da ilaç hatırlat")
        self.assertEqual(entry.understanding.capability_hint, "reminder.propose")
        self.assertTrue(str(out).startswith("Not aldım"), out)
        self.assertEqual(self.ctx.profile.data["events"], [])
        # an unanswered "ne zaman?" question owns the next sentence
        self.ctx._session().pending_event_title = "ilaç"
        args = {"title": "toplantıyı", "when": "2026-11-01T10:00", "repeat": None}
        text = "bana yarın 10'da toplantıyı hatırlat"
        with main_planner.core_reminder(args):
            self.ctx._planner_command(text, self.ctx._tr_lower(text))
        self.assertEqual([e["title"] for e in self.ctx.profile.data["events"]], ["ilaç"])

    def test_open_event_title_does_not_block_a_new_validated_reminder(self):
        self.ctx._session().pending_event_title = "ilaç"
        text = "bana yarın 10'da toplantıyı hatırlat"
        rid = "b3c2-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı")
        # Slot varlığı plan veto sebebi değildir: yeni istek kendi doğrulanmış planıyla çalışır.
        self.assertTrue(brain_entry._has_open_pending(entry))
        self.assertEqual(entry.understanding.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(entry.understanding.conversation_relation, ConversationRelation.NEW_REQUEST)
        self.assertEqual((brain_entry.core_plan(entry) or (None,))[0], "reminder")

        entry, out, feedback, handle = self.through_brain(text)
        self.assertTrue(str(out).startswith("Takvime ekledim: toplantıyı"), out)
        self.assertEqual([e["title"] for e in self.ctx.profile.data["events"]], ["toplantıyı"])
        self.assertEqual(self.ctx._session().pending_event_title, "ilaç")   # eski soru korunur

    def test_no_second_reminder_when_core_args_are_consumed(self):
        self.through_brain("bana yarın 9'da ilaç hatırlat")
        self.assertEqual(len(self.ctx.profile.data["events"]), 1)

    def test_legacy_planner_path_still_creates_when_core_does_not_own_it(self):
        reply = self.ctx._planner_command("bana yarın 9'da ilaç hatırlat", "bana yarın 9'da ilaç hatırlat")
        self.assertTrue(reply.startswith("Takvime ekledim: ilaç"))


if __name__ == "__main__":
    unittest.main()
