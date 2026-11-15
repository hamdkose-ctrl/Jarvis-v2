"""PR7 Closeout-B3c-2: reminder creation as a Core intent running at the planner's precedence slot."""
from modules import core_brain_adapter
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
    ("her 2 saatte bir su içmeyi hatırlat", "Bu isteği güvenli biçimde doğrulayamadım", False),
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
            out, feedback, _ = core_brain_adapter.handoff(self.ctx, entry, handle, text)
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
                self.assertEqual(feedback.result_status, "failed" if "her 2 saatte" in text else "handled")

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

    def test_typed_creation_has_one_worker_and_no_legacy_edit_owner(self):
        self.assertFalse(hasattr(main_planner, "_edit_reminder"))
        self.assertFalse(hasattr(self.ctx, "_planner_command"))
        entry, out, feedback, handle = self.through_brain(
            "yarın saat 10'da toplantıyı hatırlat")
        self.assertEqual(out, "Takvime ekledim: toplantıyı, yarın 10:00.")
        self.assertEqual([e["title"] for e in self.ctx.profile.data["events"]],
                         ["toplantıyı"])
        self.assertFalse(handle.called)
        self.assertEqual(feedback.result_status, "handled")

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

    def test_mixed_calendar_sentence_never_replays_a_raw_reminder(self):
        # The accepted canonical route may ask for clarification or schedule
        # one event; the deleted raw planner may not interpret it again.
        for text in ("takvimi aç ve yarın 10'da toplantı hatırlat",
                     "yarın takvimimde ne var hatırlat",
                     "bu hafta planımı göster ve yarın 9'da ilaç hatırlat"):
            with self.subTest(text=text):
                self.ctx.profile.data["events"] = []
                self.ctx._session().pending_event_title = None
                _entry, _out, _feedback, _handle = self.through_brain(text)
                self.assertLessEqual(len(self.ctx.profile.data["events"]), 1)
                self.assertFalse(hasattr(self.ctx, "_planner_command"))

    def test_pending_date_answer_is_consumed_only_by_the_bound_state_owner(self):
        self.ctx._session().pending_event_title = "ilaç"
        with patch.object(brain_entry, "pending_answer_owned", return_value=False):
            self.assertIsNone(main_planner.continue_pending_event_title(
                self.ctx, "yarın 10'da", "yarın 10'da"))
        self.assertEqual(self.ctx._session().pending_event_title, "ilaç")
        self.assertEqual(self.ctx.profile.data["events"], [])

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

    def test_reminder_worker_requires_typed_arguments_not_raw_classification(self):
        self.assertFalse(hasattr(self.ctx, "_planner_command"))
        self.assertFalse(hasattr(main_planner, "core_reminder"))
        reply = main_planner.reminder_core(
            self.ctx, {"title": "ilaç", "when": "2026-11-01T09:00", "repeat": None},
            "bana yarın 9'da ilaç hatırlat", "bana yarın 9'da ilaç hatırlat")
        self.assertTrue(reply.startswith("Takvime ekledim: ilaç"))
        self.assertEqual(len(self.ctx.profile.data["events"]), 1)


if __name__ == "__main__":
    unittest.main()
