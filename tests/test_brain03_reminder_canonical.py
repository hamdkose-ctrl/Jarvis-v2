"""BRAIN-03 reminder parity through one canonical model -> Core -> State -> worker path.

Real profile JSON, temporal calculations and confirmation effects are used.
Only the model's semantic choice is deterministic in this suite. These tests
do NOT claim recognition accuracy for spoken Turkish; a live holdout is separate.
"""
from __future__ import annotations
from modules import core_brain_adapter

from dataclasses import replace
from datetime import datetime
import uuid
import unittest
from unittest.mock import Mock, patch

from test_mail_calendar_fixes import ProfileCase, _runtime, bounded_reminder_answer
from modules import brain_core_map, brain_entry, requests_state, main_planner
from modules.brain_contracts import ConversationRelation, RequestKind


class ReminderCanonicalTests(ProfileCase):
    now = datetime(2026, 10, 17, 10, 0)   # Saturday

    def rt(self):
        return _runtime(self, self.profile, self.now)

    def event(self, title=None):
        events = self.reload().data["events"]
        return next(ev for ev in events if ev["title"] == title) if title else events[0]

    def selected(self, rt, utterance, operation, *, title=None, duration=None, weekday=None):
        arguments = {"operation": operation}
        if title is not None:
            arguments["title"] = title
        if duration is not None:
            arguments["duration"] = duration
        if weekday is not None:
            arguments["weekday"] = weekday
        assert brain_core_map.core_plan("reminders.manage", arguments) is not None, arguments
        owner = rt.profile.slug
        rid = "reminder-edit-" + uuid.uuid4().hex[:12]
        assert requests_state.register(owner, rid)

        def model(current, text, *, active_context=None):
            assert text == utterance
            return replace(
                current, request_kind=RequestKind.CAPABILITY,
                conversation_relation=ConversationRelation.NEW_REQUEST,
                capability_hint="reminders.manage",
                arguments={"original_text": text, **arguments},
                ambiguities=(), needs_input=False, actions=(),
                reason_codes=current.reason_codes + ("MODEL_DECIDED",),
            )

        forbidden = Mock(side_effect=AssertionError("old raw NLP parsed a reminder"))
        with requests_state.activate(owner, rid), \
             patch.object(brain_entry, "apply_model_understanding", side_effect=model):
            entry = brain_entry.prepare(rt, owner=owner, request_id=rid,
                                        text=utterance, source="yazı",
                                        model_understanding=True)
            result, feedback, _ = core_brain_adapter.handoff(rt, entry, forbidden, utterance)
        forbidden.assert_not_called()
        self.assertEqual(entry.understanding.capability_hint, "reminders.manage")
        return str(result), feedback

    def approved(self, rt):
        return bounded_reminder_answer(rt, "evet")

    def denied(self, rt):
        return bounded_reminder_answer(rt, "hayır")

    def test_delete_requires_real_yes_and_preserves_other_events(self):
        self.profile.add_event("İlaç", "2026-10-18T09:00")
        self.profile.add_event("Dişçi", "2026-10-19T15:00")
        rt = self.rt()
        preview, feedback = self.selected(rt, "ilaç hatırlatmasını sil", "delete", title="İlaç")
        self.assertEqual(feedback.result_status, "needs_input")
        self.assertIn("onaylıyor musun", preview)
        self.assertEqual(len(self.reload().data["events"]), 2)
        approved = self.approved(rt)
        self.assertIn("Sildim: İlaç", approved)
        self.assertIn("Google Takvim'e dokunmadım", approved)
        self.assertEqual([row["title"] for row in self.reload().data["events"]], ["Dişçi"])

    def test_delete_synonyms_keep_one_typed_owner(self):
        for utterance in ("dişçi randevusunu kaldır", "dişçi hatırlatmasını iptal et",
                          "disci hatirlatmasini sil"):
            with self.subTest(utterance=utterance):
                self.profile.data["events"] = []
                self.profile.save()
                self.profile.add_event("Dişçi", "2026-10-19T15:00")
                rt = self.rt()
                preview, feedback = self.selected(rt, utterance, "delete", title="Dişçi")
                self.assertEqual(feedback.result_status, "needs_input")
                self.assertEqual(len(self.reload().data["events"]), 1)
                self.assertIn("Sildim: Dişçi", self.approved(rt))
                self.assertEqual(self.reload().data["events"], [])

    def test_no_answer_or_expired_snapshot_keeps_reminder(self):
        self.profile.add_event("İlaç", "2026-10-18T09:00")
        rt = self.rt()
        self.selected(rt, "ilaç hatırlatmasını sil", "delete", title="İlaç")
        self.denied(rt)
        self.assertEqual(len(self.reload().data["events"]), 1)
        self.selected(rt, "ilaç hatırlatmasını sil", "delete", title="İlaç")
        self.profile.reschedule_event(self.event()["id"], "2026-10-19T09:00")
        self.assertIn("kayıt değişti", self.approved(rt))
        self.assertEqual(self.event()["when"], "2026-10-19T09:00")

    def test_missing_or_duplicate_title_creates_no_approval(self):
        rt = self.rt()
        reply, feedback = self.selected(rt, "kitap hatırlatmasını sil", "delete", title="Kitap")
        self.assertIn("bulamadım", reply)
        self.assertIsNone(rt._session().pending_confirm)
        self.profile.add_event("Kitap", "2026-10-18T09:00")
        self.profile.add_event("Kitap", "2026-10-19T09:00")
        reply, feedback = self.selected(rt, "kitap hatırlatmasını sil", "delete", title="Kitap")
        self.assertIn("birden fazla", reply.casefold())
        self.assertIsNone(rt._session().pending_confirm)
        self.assertEqual(len(self.reload().data["events"]), 2)

    def test_repeating_delete_after_consent_removes_all_occurrences(self):
        self.profile.add_event("İlaç", "2026-10-18T09:00", repeat="daily")
        rt = self.rt()
        self.selected(rt, "ilaç hatırlatmasını sil", "delete", title="İlaç")
        self.assertIn("bütün tekrarları", self.approved(rt))
        self.assertEqual(self.reload().data["events"], [])

    def test_postpone_hours_days_and_colloquial_delay(self):
        self.profile.add_event("Sunum", "2026-10-17T14:00")
        expected = [
            ("sunum hatırlatmasını 10 dakika ertele", "10 dakika", "2026-10-17T14:10"),
            ("sunumu 2 saat ertele", "2 saat", "2026-10-17T16:10"),
            ("sunum randevusunu yarına ertele", "yarına", "2026-10-18T16:10"),
            ("sunum hatırlatmasını yarım saat ertele", "yarım saat", "2026-10-18T16:40"),
        ]
        for utterance, duration, new_when in expected:
            with self.subTest(utterance=utterance):
                rt = self.rt()
                preview, fb = self.selected(rt, utterance, "postpone",
                                            title="Sunum", duration=duration)
                self.assertEqual(fb.result_status, "needs_input")
                self.assertNotEqual(self.event()["when"], new_when)
                self.assertIn("erteledim", self.approved(rt))
                self.assertEqual(self.event()["when"], new_when)

    def test_postpone_all_day_rejects_minutes_and_allows_days(self):
        self.profile.add_event("Hediye", "2026-10-20")
        rt = self.rt()
        reply, _ = self.selected(rt, "hediye hatırlatmasını 10 dakika ertele",
                                 "postpone", title="Hediye", duration="10 dakika")
        self.assertIn("tüm gün", reply.casefold())
        self.assertIsNone(rt._session().pending_confirm)
        preview, _ = self.selected(rt, "hediye hatırlatmasını 2 gün ertele",
                                   "postpone", title="Hediye", duration="2 gün")
        self.assertIn("onaylıyor musun", preview)
        self.assertIn("erteledim", self.approved(rt))
        self.assertEqual(self.event()["when"], "2026-10-22")

    def test_fired_oneoff_snoozes_from_now_and_fires_again(self):
        self.profile.add_event("İlaç", "2026-10-17T09:30")
        self.assertEqual(len(self.profile.due_events(self.now)), 1)
        rt = self.rt()
        reply, fb = self.selected(rt, "ertele", "snooze")
        self.assertEqual(fb.result_status, "needs_input")
        self.assertEqual(self.event()["when"], "2026-10-17T09:30")
        self.assertIn("10 dakika", reply)
        self.assertIn("10 dakika sonra", self.approved(rt))
        self.assertEqual(self.event()["when"], "2026-10-17T10:10")
        self.assertEqual(len(self.reload().due_events(datetime(2026, 10, 17, 10, 9))), 0)
        self.assertEqual(len(self.reload().due_events(datetime(2026, 10, 17, 10, 11))), 1)

    def test_repeat_snooze_preserves_future_schedule(self):
        self.profile.add_event("İlaç", "2026-10-17T09:30", repeat="daily")
        self.profile.due_events(self.now)
        rt = self.rt()
        reply, fb = self.selected(rt, "ilaç hatırlatmasını yarım saat ertele",
                                  "snooze", title="İlaç", duration="yarım saat")
        self.assertEqual(fb.result_status, "needs_input")
        self.assertNotIn("snooze", self.event())
        self.assertIn("30 dakika sonra", self.approved(rt))
        ev = self.event()
        self.assertEqual(ev["snooze"], "2026-10-17T10:30")
        self.assertEqual(ev["when"], "2026-10-18T09:30")
        copy = self.reload()
        self.assertEqual(copy.due_events(datetime(2026, 10, 17, 10, 29)), [])
        self.assertEqual(len(copy.due_events(datetime(2026, 10, 17, 10, 31))), 1)
        self.assertEqual(copy.data["events"][0]["when"], "2026-10-18T09:30")

    def test_snooze_phrases_share_one_typed_worker(self):
        phrases = (
            ("10 dk sonra tekrar çal", "10 dk", "2026-10-17T10:10"),
            ("5 dakika sonra yine hatırlat", "5 dakika", "2026-10-17T10:05"),
            ("1 saat sonra tekrar çal", "1 saat", "2026-10-17T11:00"),
            ("beni 10 dakika sonra tekrar uyar", "10 dakika", "2026-10-17T10:10"),
            ("daha sonra hatırlat", None, "2026-10-17T10:10"),
        )
        for utterance, duration, target in phrases:
            with self.subTest(utterance=utterance):
                self.profile.data["events"] = []
                self.profile.save()
                self.profile.add_event("İlaç", "2026-10-17T09:30", repeat="daily")
                self.profile.due_events(self.now)
                rt = self.rt()
                self.selected(rt, utterance, "snooze", duration=duration)
                self.approved(rt)
                self.assertEqual(self.event()["snooze"], target)

    def test_snooze_requires_unique_recent_fired_event(self):
        self.profile.add_event("İlaç", "2026-10-18T09:30", repeat="daily")
        rt = self.rt()
        message, _ = self.selected(rt, "ertele", "snooze")
        self.assertIn("Yakın zamanda", message)
        self.assertIsNone(rt._session().pending_confirm)
        self.profile.data["events"] = []
        self.profile.save()
        for title in ("İlaç", "Spor"):
            self.profile.add_event(title, "2026-10-17T09:30", repeat="daily")
        self.profile.due_events(self.now)
        message, _ = self.selected(rt, "ertele", "snooze")
        self.assertIn("Birden fazla", message)
        self.assertIsNone(rt._session().pending_confirm)

    def test_snooze_stale_fired_snapshot_is_refused(self):
        self.profile.add_event("İlaç", "2026-10-17T09:30", repeat="daily")
        self.profile.due_events(self.now)
        rt = self.rt()
        self.selected(rt, "ertele", "snooze")
        self.profile.data["events"][0]["fired"] = "2026-10-17T09:59"
        self.profile.save()
        self.assertIn("çalma durumu değişmiş", self.approved(rt))
        self.assertNotIn("snooze", self.event())

    def test_move_to_weekday_one_off_is_not_a_scroll_action(self):
        self.profile.add_event("Sunum", "2026-10-19T14:00")
        rt = self.rt()
        preview, fb = self.selected(rt, "sunumu cumaya kaydır",
                                    "move", title="Sunum", weekday="cuma")
        self.assertEqual(fb.result_status, "needs_input")
        self.assertIn("kaydırmamı", preview)
        self.assertEqual(self.event()["when"], "2026-10-19T14:00")
        self.assertIn("kaydırdım", self.approved(rt))
        self.assertEqual(self.event()["when"], "2026-10-23T14:00")
        for text in ("sayfayı aşağı kaydır", "ekranı yukarı kaydır", "reklamı atla"):
            with self.subTest(text=text):
                self.assertIsNone(brain_core_map.core_plan(
                    "reminders.manage", {"operation": "move",
                                         "title": "Sunum", "weekday": text}))

    def test_move_repeat_keeps_weekly_rule_and_only_moves_next_occurrence(self):
        self.profile.add_event("Toplantı", "2026-10-19T10:00", repeat="weekly:0")
        rt = self.rt()
        self.selected(rt, "bu haftaki toplantıyı cumaya kaydır",
                      "move", title="Toplantı", weekday="cuma")
        self.assertIn("kaydırdım", self.approved(rt))
        self.assertEqual(self.event()["when"], "2026-10-23T10:00")
        self.assertEqual(self.event()["repeat"], "weekly:0")
        self.selected(rt, "toplantıyı pazartesiye kaydır",
                      "move", title="Toplantı", weekday="pazartesi")
        self.assertIn("kaydırdım", self.approved(rt))
        self.assertEqual(self.event()["when"], "2026-10-19T10:00")

    def test_skip_next_repeat_requires_yes_and_one_recurring_target(self):
        self.profile.add_event("İlaç", "2026-10-17T18:00", repeat="daily")
        rt = self.rt()
        preview, fb = self.selected(rt, "ilaç hatırlatmasını atla",
                                    "skip", title="İlaç")
        self.assertEqual(fb.result_status, "needs_input")
        self.assertEqual(self.event()["when"], "2026-10-17T18:00")
        self.assertIn("atlamamı", preview)
        self.assertIn("atladım", self.approved(rt))
        self.assertEqual(self.event()["when"], "2026-10-18T18:00")
        self.assertNotIn("base", self.event())

    def test_skip_one_off_is_refused_before_approval(self):
        self.profile.add_event("Dişçi", "2026-10-19T15:00")
        rt = self.rt()
        result, fb = self.selected(rt, "dişçi hatırlatmasını atla",
                                   "skip", title="Dişçi")
        self.assertIn("tek seferlik", result)
        self.assertIsNone(rt._session().pending_confirm)
        self.assertEqual(self.event()["when"], "2026-10-19T15:00")

    def test_core_denies_unbounded_targets_and_action_confusion(self):
        for args in (
            {"operation": "delete"}, {"operation": "delete", "title": ""},
            {"operation": "postpone", "title": "İlaç"},
            {"operation": "postpone", "title": "İlaç", "duration": "500 gün"},
            {"operation": "snooze", "duration": "3000 gün"},
            {"operation": "move", "title": "İlaç", "weekday": "tomorrow"},
            {"operation": "move", "title": "İlaç", "weekday": "cuma", "duration": "5 dakika"},
            {"operation": "snooze", "query": "C:/secret"},
            {"operation": "skip", "title": "İlaç", "event_id": 7},
            {"operation": "delete", "title": "İlaç", "all": True},
        ):
            with self.subTest(args=args):
                self.assertIsNone(brain_core_map.core_plan("reminders.manage", args))

    def test_raw_legacy_phrases_do_not_delete_without_model(self):
        self.profile.add_event("İlaç", "2026-10-18T09:00")
        rt = self.rt()
        for text in ("ilaç hatırlatmasını sil", "notu silme", "ilaç sil demedim"):
            with self.subTest(text=text):
                result = rt.handle(text)
                self.assertNotIn("Sildim:", str(result))
                self.assertEqual(len(self.reload().data["events"]), 1)

    def test_profile_snooze_save_failure_rolls_back(self):
        self.profile.add_event("İlaç", "2026-10-17T09:30", repeat="daily")
        ev = self.event()
        with patch.object(self.profile, "save", side_effect=OSError("disk dolu")):
            with self.assertRaises(OSError):
                self.profile.snooze_event(ev["id"], "2026-10-17T10:10")
        self.assertNotIn("snooze", self.event())
        self.assertTrue(self.profile.snooze_event(ev["id"], "2026-10-17T10:10"))
        self.assertEqual(self.event()["snooze"], "2026-10-17T10:10")


if __name__ == "__main__":
    unittest.main()
