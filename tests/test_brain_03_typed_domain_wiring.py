"""BRAIN-03: typed domain workers via real prepare -> handoff -> Core.

No cloud/model/OS/clipboard/image hardware touched; the external semantic
transport and each existing effect boundary are deterministic spies.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time
import unittest
from unittest.mock import Mock, patch

import test_brain_pr3_raw_text_authority as baseline
from modules import brain_context, brain_core_map, brain_entry, engine_context, engine_intents, workbench
from modules.brain_contracts import RequestKind


class TypedDomainWiringTests(baseline._CanonicalAuthorityHarness):
    @staticmethod
    def adopt(capability, arguments):
        def choose(current, utterance, *, active_context=None):
            return replace(
                current, request_kind=RequestKind.CAPABILITY,
                capability_hint=capability, arguments=arguments,
                ambiguities=(), needs_input=False,
                reason_codes=current.reason_codes + ("MODEL_DECIDED",),
            )
        return choose

    def typed(self, utterance, capability, arguments):
        self.assertFalse(hasattr(self.ctx, "_user_controls"))
        self.assertFalse(hasattr(self.ctx, "_planner_command"))
        self.assertFalse(hasattr(self.ctx, "_extra_commands"))
        with patch.object(brain_entry, "apply_model_understanding",
                          side_effect=self.adopt(capability, arguments)):
            entry, output, _handler, feedback = self.turn_real(
                utterance, model_understanding=True)
        return entry, output, feedback

    def test_calendar_week_plan_is_model_selected_core_read_only(self):
        # Real prepare/handoff/Core; the model transport is stubbed only at its
        # proposal boundary. No legacy week regex or raw planner gets authority.
        from modules import main_planner
        for period, utterance in (("this", "Bu haftam nasıl?"),
                                  ("next", "Haftaya ne var?"),
                                  ("seven", "Önümüzdeki yedi gün planı")):
            with (self.subTest(period=period),
                  patch.object(main_planner, "_week_plan", return_value="WEEK RESULT") as week):
                entry, output, feedback = self.typed(
                    utterance, "calendar.read", {"view": "week_plan", "period": period})
                self.assertEqual(brain_entry.core_plan(entry),
                                 ("agenda_read", {"view": "week_plan", "period": period}))
                self.assertEqual(output, "WEEK RESULT")
                self.assertEqual(feedback.result_status, "handled")
                week.assert_called_once_with(self.ctx, period)

    def test_screen_text_read_is_typed_and_read_only(self):
        with patch.object(self.ctx, "_screen_ocr", return_value="Satır bir\nSatır iki") as ocr, \
             patch.object(self.ctx, "_copy_text",
                          side_effect=AssertionError("read touched clipboard")) as copy, \
             patch.object(self.ctx.profile, "add_note_item",
                          side_effect=AssertionError("read wrote note")) as note:
            entry, output, feedback = self.typed(
                "Ekranda yazanı oku", "screen.text", {"operation": "read"})
        self.assertEqual(brain_entry.core_plan(entry), ("screen_text", {"operation": "read"}))
        self.assertEqual(output, "Satır bir\nSatır iki")
        self.assertEqual(feedback.result_status, "handled")
        ocr.assert_called_once()
        copy.assert_not_called()
        note.assert_not_called()

    def test_screen_text_copy_is_one_core_selected_clipboard_effect(self):
        with patch.object(self.ctx, "_screen_ocr", return_value="Metin") as ocr, \
             patch.object(self.ctx, "_copy_text", return_value=True) as copy:
            _, output, _ = self.typed(
                "Ekrandaki metni panoya kopyala", "screen.text", {"operation": "copy"})
        self.assertIn("panoya kopyaladım", output)
        ocr.assert_called_once()
        copy.assert_called_once_with("Metin")

    def test_error_note_is_single_owner_and_no_fabricated_error(self):
        with patch.object(self.ctx, "_screen_ocr", return_value="Hata görünmüyor") as ocr, \
             patch.object(self.ctx.profile, "add_note_item",
                          side_effect=AssertionError("invented note")) as note:
            _, output, _ = self.typed(
                "Ekran hatasını not al", "screen.text", {"operation": "error_note"})
        self.assertIn("hata görünmüyor", output)
        ocr.assert_called_once()
        note.assert_not_called()

    def test_screen_privacy_denial_precedes_capture_or_copy(self):
        with patch.object(self.ctx.privacy, "blocked",
                          return_value="İzin yok") as privacy, \
             patch.object(self.ctx, "_screen_ocr",
                          side_effect=AssertionError("OCR despite denial")) as ocr:
            _, output, _ = self.typed(
                "Ekrandaki metni oku", "screen.text", {"operation": "read"})
        self.assertEqual(output, "İzin yok")
        privacy.assert_any_call("screen")
        ocr.assert_not_called()

    def test_screen_text_single_executor_rejects_unsupported_operation_without_capture(self):
        with patch.object(self.ctx, "_screen_ocr",
                          side_effect=AssertionError("OCR without validated operation")) as ocr:
            reply = engine_intents.execute_screen_text(self.ctx, "delete_all")
        self.assertIn("doğrulanmadı", reply)
        ocr.assert_not_called()

    def test_share_starts_via_existing_vision_permission_owner(self):
        with patch.object(self.ctx, "set_share", return_value="KAMERA") as share:
            entry, output, feedback = self.typed(
                "Kamerayı aç", "device.share", {"action": "camera"})
        self.assertEqual(brain_entry.core_plan(entry), ("share_control", {"action": "camera"}))
        self.assertEqual(output, "KAMERA")
        self.assertEqual(feedback.result_status, "handled")
        share.assert_called_once_with("camera")

    def test_share_stop_does_not_invent_new_camera_session(self):
        with patch.object(self.ctx, "set_share", return_value="KAPALI") as share:
            _, output, _ = self.typed("Paylaşımı kapat", "device.share", {"action": "stop"})
        self.assertEqual(output, "KAPALI")
        share.assert_called_once_with(None)

    def test_voice_rate_uses_single_existing_preference_writer(self):
        self.ctx.profile.data["prefs"]["rate"] = -8
        with patch.object(engine_context, "set_profile_rate", return_value=True) as save, \
             patch("modules.voice_runtime.active", return_value=None):
            entry, output, _ = self.typed(
                "Biraz daha yavaş konuş", "voice.rate", {"direction": "slower"})
        self.assertEqual(brain_entry.core_plan(entry), ("voice_rate", {"direction": "slower"}))
        self.assertIn("yavaş", output)
        save.assert_called_once_with(self.ctx.profile, -18, lane=None)

    def test_brief_uses_existing_personal_briefing_executor(self):
        with patch.object(self.ctx, "_daily_briefing", return_value="ÖZET") as brief:
            entry, output, _ = self.typed("Bugün neler var?", "brief.read", {})
        self.assertEqual(brain_entry.core_plan(entry), ("daily_brief", {}))
        self.assertEqual(output, "ÖZET")
        brief.assert_called_once()

    def _record_recent_workbench(self):
        source = Path(self.temp.name) / "table.csv"
        source.write_text("item,value\nA,1\n", encoding="utf-8")
        with workbench._LOCK:
            workbench._LAST[self.owner] = {
                "paths": [str(source)], "instruction": "tablo yap",
                "at": time.monotonic(), "ext": ".xlsx",
            }
        self.addCleanup(workbench._LAST.pop, self.owner, None)
        return source

    def test_workbench_revision_uses_core_bound_owner_digest_and_path_permission(self):
        source = self._record_recent_workbench()
        with patch("modules.nxapi.allowed", return_value=source) as allowed, \
             patch.object(workbench, "handle", return_value="NEW TABLE") as worker:
            entry, output, feedback = self.typed(
                "Tabloyu Word olarak ver", "workbench.followup",
                {"operation": "revise", "format": "word"},
            )
        plan = brain_entry.core_plan(entry)
        self.assertEqual(plan[0], "workbench_followup")
        self.assertEqual(plan[1]["format"], ".docx")
        self.assertEqual(len(plan[1]["expected_digest"]), 64)
        self.assertEqual(output, "NEW TABLE")
        self.assertEqual(feedback.result_status, "handled")
        allowed.assert_called_once_with(str(source))
        worker.assert_called_once_with(
            self.owner, [str(source)],
            "tablo yap. Ek istek: Tabloyu Word olarak ver", ".docx",
        )

    def test_workbench_raw_followup_parser_is_physically_retired(self):
        # A model CHAT verdict cannot be turned into a revision by a removed
        # second semantic parser. Even a negative or quoted phrase has no effect.
        self.assertFalse(hasattr(workbench, "followup"))
        self._record_recent_workbench()
        def chat(current, text, *, active_context=None):
            return replace(
                current, request_kind=RequestKind.CHAT, capability_hint=None,
                arguments={"original_text": text}, ambiguities=(),
                needs_input=False, actions=(),
                reason_codes=current.reason_codes + ("MODEL_DECIDED", "MODEL_CHAT_DECIDED"),
            )
        with patch.object(brain_entry, "apply_model_understanding", side_effect=chat), \
             patch.object(workbench, "handle",
                          side_effect=AssertionError("CHAT must not revise a table")) as worker:
            for utterance in (
                "tabloyu güncelleme", "şu sütunu ekleme",
                "tabloyu Word olarak ver demedim",
                "bu cümlede tabloyu Word olarak ver yazıyor",
                "tabloyu PDF olarak ver, notları sil",
                "tabloyu güncellemek nasıl çalışıyor?",
            ):
                with self.subTest(utterance=utterance):
                    _entry, _output, _handler, feedback = self.turn_real(
                        utterance, model_understanding=True)
                    self.assertEqual(feedback.result_status, "handled")
        worker.assert_not_called()

    def test_workbench_typed_revision_permission_denial_has_no_file_effect(self):
        self._record_recent_workbench()
        digest = workbench.snapshot_digest(self.owner)
        self.assertIsNotNone(digest)
        with patch("modules.nxapi.allowed", return_value=None), \
             patch.object(workbench, "handle",
                          side_effect=AssertionError("unapproved workbench output")) as worker:
            response = workbench.followup_typed(
                self.owner, "Tabloyu Word olarak ver",
                expected_digest=digest, fmt=".docx")
        self.assertIn("güvenli biçimde", response)
        worker.assert_not_called()

    def test_workbench_missing_target_is_refused_before_raw_fallback(self):
        with patch.object(workbench, "handle",
                          side_effect=AssertionError("missing target executed")) as worker:
            entry, output, feedback = self.typed(
                "Tabloya yeni sütun ekle", "workbench.followup",
                {"operation": "revise"},
            )
        self.assertIsNone(brain_entry.core_plan(entry))
        self.assertIn("doğrulayamadım", output)
        self.assertEqual(feedback.result_status, "failed")
        worker.assert_not_called()

    def test_workbench_foreign_revision_and_expiry_are_not_effect_authority(self):
        source = self._record_recent_workbench()
        digest = workbench.snapshot_digest(self.owner)
        self.assertIsNotNone(digest)
        with patch.object(workbench, "handle",
                          side_effect=AssertionError("foreign or stale revision executed")) as worker:
            self.assertIn("değişti", workbench.followup_typed(
                self.owner, "Tabloyu Word yap", expected_digest="0" * 64))
            self.assertIn("değişti", workbench.followup_typed(
                "foreign-owner", "Tabloyu Word yap", expected_digest=digest))
            with workbench._LOCK:
                workbench._LAST[self.owner]["at"] -= workbench.FOLLOW_SECONDS + 1
            self.assertIn("süresi doldu", workbench.followup_typed(
                self.owner, "Tabloyu Word yap", expected_digest=digest))
        worker.assert_not_called()

    def test_study_plan_is_a_typed_read_without_raw_hoca_selection(self):
        schedule = {"days": [{"day": "Pazartesi", "blocks": [
            {"topic": "Matematik", "text": "ders", "minutes": 30},
        ]}], "days_left": None}
        with patch("modules.study._state", return_value={"docs": ["lesson"]}), \
             patch("modules.studyexam.plan", return_value=schedule) as worker:
            entry, output, feedback = self.typed(
                "Ders programımı söyle", "study.read", {"view": "plan"})
        self.assertEqual(brain_entry.core_plan(entry), ("study_read", {"view": "plan"}))
        self.assertIn("Matematik 30 dakika", output)
        self.assertEqual(feedback.result_status, "handled")
        worker.assert_called_once()

    def test_study_focus_is_typed_and_unconfigured_sources_are_reported(self):
        with patch("modules.study._state", return_value={"docs": []}), \
             patch("modules.studyexam.focus",
                   side_effect=AssertionError("no study material")) as worker:
            entry, output, _ = self.typed(
                "Hangi konuya çalışmalıyım?", "study.read", {"view": "focus"})
        self.assertEqual(brain_entry.core_plan(entry), ("study_read", {"view": "focus"}))
        self.assertIn("önce bir konu", output)
        worker.assert_not_called()

    def test_typed_study_preserves_request_cancellation(self):
        from modules import requests_state
        with patch("modules.study._state",
                   side_effect=requests_state.Cancelled("stop")):
            with self.assertRaises(requests_state.Cancelled):
                self.typed("Ders programımı oku", "study.read", {"view": "plan"})

    def test_raw_user_command_alias_is_physically_removed(self):
        self.assertFalse(hasattr(engine_context, "_user_command"))

    def test_new_note_is_created_by_core_and_uses_existing_note_owner(self):
        with patch.object(self.ctx, "_add_note", return_value={"id": 20}) as save:
            entry, output, feedback = self.typed(
                "Not al: Uçuş kodunu sakla", "notes.add",
                {"text": "Uçuş kodunu sakla"})
        self.assertEqual(brain_entry.core_plan(entry),
                         ("notes_add", {"text": "Uçuş kodunu sakla"}))
        self.assertEqual(output, "Not aldım: Uçuş kodunu sakla")
        self.assertEqual(feedback.result_status, "handled")
        save.assert_called_once_with("Uçuş kodunu sakla")
        self.assertFalse(hasattr(self.ctx, "_planner_command"))

    def test_calendar_today_agenda_reads_existing_owner_only(self):
        with patch.object(self.ctx, "_agenda_text", return_value="AJANDA") as agenda:
            entry, output, feedback = self.typed(
                "Bugün takvimimde ne var", "calendar.read",
                {"view": "agenda", "period": "today"})
        self.assertEqual(brain_entry.core_plan(entry),
                         ("agenda_read", {"view": "agenda", "period": "today"}))
        self.assertEqual(output, "AJANDA")
        self.assertEqual(feedback.result_status, "handled")
        agenda.assert_called_once()

    def test_calendar_week_uses_existing_week_worker(self):
        from modules import main_planner
        with patch.object(main_planner, "_week_plan", return_value="HAFTA") as week:
            entry, output, _ = self.typed(
                "Önümüzdeki hafta planım", "calendar.read",
                {"view": "week_plan", "period": "next"})
        self.assertEqual(brain_entry.core_plan(entry),
                         ("agenda_read", {"view": "week_plan", "period": "next"}))
        self.assertEqual(output, "HAFTA")
        week.assert_called_once_with(self.ctx, "next")

    def test_single_named_reminder_deletion_reuses_profile_owner(self):
        event = {"id": 17, "title": "Ekip Toplantısı",
                 "when": "2026-11-14T11:00"}
        self.ctx.profile.data["events"] = [event]
        with patch.object(self.ctx.profile, "delete_event", return_value=True) as delete:
            entry, output, feedback = self.typed(
                "Ekip Toplantısı hatırlatmasını sil", "reminders.manage",
                {"operation": "delete", "title": "Ekip Toplantısı"})
        self.assertEqual(brain_entry.core_plan(entry),
                         ("reminder_manage", {"operation": "delete", "title": "Ekip Toplantısı"}))
        self.assertEqual(feedback.result_status, "needs_input")
        self.assertIn("onaylıyor musun", output)
        pending = self.ctx._session().pending_confirm
        self.assertEqual(pending["event_id"], 17)
        self.assertEqual(pending["owner"], self.owner)
        delete.assert_not_called()
        from modules import main_planner
        with patch.object(self.ctx.profile, "delete_event", return_value=True) as confirmed:
            reply = main_planner.delete_reminder_confirmed(self.ctx, pending)
        self.assertIn("Sildim: Ekip Toplantısı", reply)
        confirmed.assert_called_once_with(17)

    def test_duplicate_title_cannot_silently_delete_other_events(self):
        self.ctx.profile.data["events"] = [
            {"id": 1, "title": "Ekip", "when": "2026-11-14T11:00"},
            {"id": 2, "title": "Ekip", "when": "2026-11-15T11:00"},
        ]
        with patch.object(self.ctx.profile, "delete_event",
                          side_effect=AssertionError("ambiguous delete")) as delete:
            _, output, _ = self.typed(
                "Ekip hatırlatmasını sil", "reminders.manage",
                {"operation": "delete", "title": "Ekip"})
        self.assertIn("birden fazla", output.casefold())
        delete.assert_not_called()

    def test_reminder_confirmation_refuses_foreign_or_changed_event(self):
        from modules import main_planner
        event = {"id": 9, "title": "Rapor", "when": "2026-11-15T09:00"}
        self.ctx.profile.data["events"] = [event]
        saved = {"action": "reminder_delete", "owner": self.owner,
                 "event_id": 9, "title": "Rapor",
                 "when": "2026-11-15T09:00", "repeat": None}
        with patch.object(self.ctx.profile, "delete_event",
                          side_effect=AssertionError("stale delete")) as worker:
            bad_owner = {**saved, "owner": "foreign"}
            self.assertIn("sahibi değişti",
                          main_planner.delete_reminder_confirmed(self.ctx, bad_owner))
            event["when"] = "2026-11-16T09:00"
            self.assertIn("kayıt değişti",
                          main_planner.delete_reminder_confirmed(self.ctx, saved))
        worker.assert_not_called()

    def test_exact_undo_uses_fast_gate_and_no_raw_cascade(self):
        with patch.object(self.ctx.files, "undo_organize", return_value=3) as undo, \
             patch.object(self.ctx, "handle", wraps=self.ctx.handle) as raw_handler:
            entry, output, _handler, feedback = self.turn_real(
                "düzenlemeyi geri al", model_understanding=False)
        self.assertEqual(entry.fast_gate.protocol, "fast.file.organize.undo")
        self.assertEqual(output, "3 dosyayı eski yerine taşıdım.")
        self.assertEqual(feedback.result_status, "handled")
        undo.assert_called_once_with(self.owner)
        raw_handler.assert_not_called()
        self.assertFalse(hasattr(self.ctx, "_extra_commands"))

    def test_nonexact_or_negated_undo_cannot_use_fast_undo_effect(self):
        from modules import brain_gates
        for utterance in ("düzenlemeyi geri alma", "düzenlemeyi geri al demedim"):
            with self.subTest(utterance=utterance):
                gate = brain_gates.deterministic_fast_gate(
                    owner=self.owner, request_id="undo-check",
                    text=utterance,
                    active_context=brain_context.ActiveContext(
                        owner=self.owner, request_id="undo-check"),
                )
                self.assertNotEqual(gate.protocol, "fast.file.organize.undo")

    def test_tasks_add_and_list_execute_existing_owner_without_raw_parser(self):
        from modules import tasks
        with patch.object(tasks, "add",
                          return_value={"id": 1, "text": "Ekip toplantısı"}) as add:
            entry, output, feedback = self.typed(
                "Ekip toplantısı görevini ekle", "tasks.manage",
                {"operation": "add", "text": "Ekip toplantısı"})
        self.assertEqual(brain_entry.core_plan(entry),
                         ("tasks_manage", {"operation": "add", "text": "Ekip toplantısı"}))
        self.assertEqual(output, "Görev ekledim: Ekip toplantısı.")
        self.assertEqual(feedback.result_status, "handled")
        add.assert_called_once_with(self.ctx.profile, "Ekip toplantısı")
        with patch.object(tasks, "list_text", return_value="LİSTE") as read:
            _, output, _ = self.typed(
                "Görevlerimi listele", "tasks.manage", {"operation": "list"})
        self.assertEqual(output, "LİSTE")
        read.assert_called_once_with(self.ctx.profile)

    def test_tasks_completion_requires_one_exact_open_title(self):
        from modules import tasks
        self.ctx.profile.data["tasks"] = [
            {"id": 14, "text": "Rapor hazırla", "done": False},
            {"id": 15, "text": "Rapor", "done": False},
        ]
        with patch.object(tasks, "complete_exact", return_value="Rapor") as complete:
            _, output, feedback = self.typed(
                "Rapor görevini bitir", "tasks.manage",
                {"operation": "complete", "text": "Rapor"})
        self.assertEqual(feedback.result_status, "handled")
        self.assertIn("tamamlandı", output)
        complete.assert_called_once_with(self.ctx.profile, "Rapor")
        self.ctx.profile.data["tasks"].append(
            {"id": 16, "text": "Rapor", "done": False})
        with patch.object(tasks, "complete_exact", return_value=None) as complete:
            _, output, _ = self.typed(
                "Rapor görevini bitir", "tasks.manage",
                {"operation": "complete", "text": "Rapor"})
        self.assertIn("tek bir", output)
        complete.assert_called_once_with(self.ctx.profile, "Rapor")

    def test_task_completion_domain_is_exact_atomic_and_idempotent(self):
        from modules import tasks
        self.ctx.profile.data["tasks"] = [
            {"id": 1, "text": "Rapor", "done": False},
            {"id": 2, "text": "Rapor hazırla", "done": False},
        ]
        with patch.object(self.ctx.profile, "save") as save:
            self.assertEqual(tasks.complete_exact(self.ctx.profile, "Rapor"), "Rapor")
            self.assertIsNone(tasks.complete_exact(self.ctx.profile, "Rapor"))
        self.assertTrue(self.ctx.profile.data["tasks"][0]["done"])
        self.assertFalse(self.ctx.profile.data["tasks"][1]["done"])
        save.assert_called_once()
        self.ctx.profile.data["tasks"].append({"id": 3, "text": "Rapor", "done": False})
        self.ctx.profile.data["tasks"][0]["done"] = False
        with patch.object(self.ctx.profile, "save",
                          side_effect=AssertionError("ambiguous write")) as save:
            self.assertIsNone(tasks.complete_exact(self.ctx.profile, "Rapor"))
        save.assert_not_called()

    def test_kb_question_uses_existing_read_only_worker(self):
        from modules import kb
        with patch.object(kb, "answer", return_value="DOKÜMAN BULGUSU") as answer:
            entry, output, feedback = self.typed(
                "Belgelerimde kira ne zaman bitiyor", "kb.query",
                {"question": "Belgelerimde kira ne zaman bitiyor"})
        self.assertEqual(brain_entry.core_plan(entry),
                         ("kb_query", {"question": "Belgelerimde kira ne zaman bitiyor"}))
        self.assertEqual(output, "DOKÜMAN BULGUSU")
        self.assertEqual(feedback.result_status, "handled")
        answer.assert_called_once_with(self.ctx.profile, "Belgelerimde kira ne zaman bitiyor")

    def test_worktrack_status_uses_existing_mail_privacy_worker(self):
        from modules import worktrack
        with patch.object(worktrack, "report", return_value="İŞ DURUMU") as report:
            entry, output, feedback = self.typed(
                "Bu hafta işte neler oldu", "worktrack.read",
                {"kind": "weekly"})
        self.assertEqual(brain_entry.core_plan(entry),
                         ("worktrack_read", {"kind": "weekly"}))
        self.assertEqual(output, "İŞ DURUMU")
        self.assertEqual(feedback.result_status, "handled")
        report.assert_called_once_with("weekly", None)

    def test_plain_hoca_lesson_starts_from_typed_core_worker(self):
        from modules import hoca
        with patch("config.load_settings", return_value={"hoca_enabled": True}), \
             patch.object(hoca, "start", return_value={
                 "topic": "Hücre", "steps": [{"title": "Giriş"}]}) as start, \
             patch.object(hoca, "_lesson_text", return_value="DERS İÇERİĞİ") as teach:
            entry, output, feedback = self.typed(
                "Hücre konusunu öğret", "hoca.lesson.start",
                {"topic": "Hücre"})
        self.assertEqual(brain_entry.core_plan(entry),
                         ("hoca_start", {"topic": "Hücre"}))
        self.assertIn("DERS İÇERİĞİ", output)
        self.assertEqual(feedback.result_status, "handled")
        start.assert_called_once_with(self.ctx.profile, "Hücre", level="", source=None)
        teach.assert_called_once_with(self.ctx.profile)

    def test_hoca_disabled_config_prevents_worker_call(self):
        from modules import hoca
        with patch("config.load_settings", return_value={"hoca_enabled": False}), \
             patch.object(hoca, "start",
                          side_effect=AssertionError("disabled Hoca started")) as start:
            entry, output, feedback = self.typed(
                "Hücre konusunu öğret", "hoca.lesson.start",
                {"topic": "Hücre"})
        self.assertEqual(brain_entry.core_plan(entry),
                         ("hoca_start", {"topic": "Hücre"}))
        self.assertIn("kapalı", output)
        start.assert_not_called()

    def test_browser_summary_reads_only_core_grounded_page(self):
        from modules import browser
        with patch.object(browser, "summarize", return_value="SAYFA ÖZETİ") as summarize:
            entry, output, feedback = self.typed(
                "https://example.org/blog sayfasını özetle",
                "browser.page.read", {"url": "https://example.org/blog"})
        self.assertEqual(brain_entry.core_plan(entry),
                         ("browser_page", {"url": "https://example.org/blog"}))
        self.assertEqual(output, "SAYFA ÖZETİ")
        self.assertEqual(feedback.result_status, "handled")
        summarize.assert_called_once_with("https://example.org/blog")

    def test_media_search_uses_exact_existing_worker_and_privacy(self):
        from modules import media
        with patch.object(media, "youtube", return_value="ARAMA") as youtube:
            entry, output, feedback = self.typed(
                "YouTube'da caz aç", "media.search",
                {"service": "youtube", "query": "caz"})
        self.assertEqual(brain_entry.core_plan(entry),
                         ("media_search", {"service": "youtube", "query": "caz"}))
        self.assertEqual(output, "ARAMA")
        self.assertEqual(feedback.result_status, "handled")
        youtube.assert_called_once_with("caz")
        with patch.object(self.ctx.privacy, "blocked", return_value="WEB KAPALI"), \
             patch.object(media, "youtube",
                          side_effect=AssertionError("privacy bypassed")) as youtube:
            _, output, _ = self.typed(
                "YouTube'da caz aç", "media.search",
                {"service": "youtube", "query": "caz"})
        self.assertEqual(output, "WEB KAPALI")
        youtube.assert_not_called()

    def test_model_grounding_rejects_invented_note_and_reminder_target(self):
        from modules import brain_model_understanding as model
        self.assertTrue(model._arguments_are_grounded(
            capability_id="notes.add", supplied={"text": "Raporu teslim et"},
            sources={"text": "Raporu teslim et"},
            text="Not al: Raporu teslim et"))
        self.assertFalse(model._arguments_are_grounded(
            capability_id="notes.add", supplied={"text": "Notları sil"},
            sources={"text": "Notları sil"},
            text="Not al: Raporu teslim et"))
        self.assertTrue(model._arguments_are_grounded(
            capability_id="reminders.manage",
            supplied={"operation": "delete", "title": "Rapor"},
            sources={"title": "Rapor"}, text="Rapor hatırlatmasını sil"))
        self.assertFalse(model._arguments_are_grounded(
            capability_id="reminders.manage",
            supplied={"operation": "delete", "title": "Ekip"},
            sources={}, text="Rapor hatırlatmasını sil"))

    def test_hoca_pending_answer_has_one_state_core_owner_and_stale_fence(self):
        from modules import hoca
        state = self.ctx.profile.data.setdefault("hoca", {})
        lesson = {"active": 0, "done": False, "topic": "Hücre",
                  "steps": [{"title": "Hücre", "goal": "Amaç"}],
                  "pending": {"step": 0, "question": "Hücre nedir?"}}
        # The actual profile schema lives in hoca.active; use a spy at that
        # seam but let Brain observe a genuine profile pending reference.
        self.ctx.profile.data["hoca"] = {"lesson": lesson}
        with patch.object(hoca, "active", return_value=lesson), \
             patch.object(hoca, "grade", return_value={
                 "correct": False, "feedback": "Yanlış", "expected": "Bir yapı"}) as grade, \
             patch("config.load_settings", return_value={"hoca_enabled": True}), \
             patch.object(self.ctx, "handle", wraps=self.ctx.handle) as raw_handler:
            entry, output, handler, feedback = self.turn_real(
                "cevap: test", model_understanding=False)
        self.assertTrue(entry.state_gate.matched)
        self.assertEqual(entry.state_gate.protocol, "hoca.lesson.control")
        self.assertEqual(entry.state_gate.selection, "answer:test")
        self.assertIn("Doğrusu", output)
        self.assertEqual(feedback.result_status, "handled")
        raw_handler.assert_not_called()
        grade.assert_called_once_with(self.ctx.profile, "test")
        with patch.object(hoca, "active", return_value={
                 **lesson, "pending": {"step": 1, "question": "Başka soru"}}), \
             patch.object(hoca, "grade",
                          side_effect=AssertionError("stale answer graded")) as grade:
            rejected = hoca.control_typed(self.ctx.profile, operation="answer",
                                           step=0, question="Hücre nedir?", answer="test")
        self.assertIn("değişti", rejected)
        grade.assert_not_called()

    def test_typed_taildrop_start_never_uses_raw_selector(self):
        from modules import filesend
        with patch.object(filesend, "transfer_typed", return_value="SENT") as transfer, \
             patch.object(filesend, "handle",
                          side_effect=AssertionError("raw Taildrop selector called")) as legacy:
            entry, output, feedback = self.typed(
                "Rapor PDF dosyasını telefonuma gönder", "filesend.transfer",
                {"operation": "search", "query": "Rapor PDF"})
        self.assertEqual(brain_entry.core_plan(entry),
                         ("filesend_transfer", {"operation": "search", "query": "Rapor PDF"}))
        self.assertEqual(output, "SENT")
        self.assertEqual(feedback.result_status, "handled")
        transfer.assert_called_once_with(self.owner, "search", "Rapor PDF")
        legacy.assert_not_called()

    def test_notify_typed_operation_is_profile_bound_and_web_privacy_checked(self):
        from modules import notify
        with patch.object(notify, "execute_typed", return_value="KAPANDI") as execute:
            _, output, feedback = self.typed(
                "Telefon bildirimini kapat", "notify.manage",
                {"operation": "disable"})
        self.assertEqual(output, "KAPANDI")
        self.assertEqual(feedback.result_status, "handled")
        execute.assert_called_once_with("disable", self.ctx.profile.data["prefs"], self.ctx.profile.save)
        with patch.object(self.ctx.privacy, "blocked", return_value="AĞ İZNİ YOK"), \
             patch.object(notify, "execute_typed",
                          side_effect=AssertionError("privacy bypass")) as execute:
            _, output, _ = self.typed(
                "Telefon bildirimi test gönder", "notify.manage", {"operation": "test"})
        self.assertEqual(output, "AĞ İZNİ YOK")
        execute.assert_not_called()

    def test_hoca_stale_same_question_but_new_lesson_identity_refuses_grading(self):
        from modules import hoca
        lesson = {"active": 0, "started": 55, "course_id": 3, "done": False,
                  "topic": "Hücre", "steps": [{"title": "Hücre"}],
                  "pending": {"step": 0, "question": "Hücre nedir?"}}
        self.ctx.profile.data["hoca"] = {"lesson": lesson}
        with patch.object(hoca, "grade",
                          side_effect=AssertionError("stale lesson graded")) as grade:
            reply = hoca.control_typed(
                self.ctx.profile, operation="answer", step=0,
                question="Hücre nedir?", answer="yanıt",
                started=54, course_id=3,
            )
        self.assertIn("değişti", reply)
        grade.assert_not_called()

    def test_hoca_control_without_pending_question_advances_without_raw_parser(self):
        from modules import hoca
        lesson = {"active": 0, "done": False, "topic": "Hücre",
                  "steps": [{"title": "Birinci", "goal": "Temel"},
                            {"title": "İkinci", "goal": "İleri"}],
                  "pending": None}
        self.ctx.profile.data["hoca"] = {"lesson": lesson}
        with patch.object(hoca, "advance", return_value=True) as advance, \
             patch.object(hoca, "_lesson_text", return_value="İKİNCİ") as teach, \
             patch("config.load_settings", return_value={"hoca_enabled": True}), \
             patch.object(self.ctx, "handle", wraps=self.ctx.handle) as raw_handler:
            entry, output, _handler, feedback = self.turn_real(
                "sonraki adım", model_understanding=False)
        self.assertEqual(entry.state_gate.protocol, "hoca.lesson.control")
        self.assertEqual(output, "İKİNCİ")
        self.assertEqual(feedback.result_status, "handled")
        raw_handler.assert_not_called()
        advance.assert_called_once_with(self.ctx.profile)
        teach.assert_called_once_with(self.ctx.profile)

    def test_turkish_casefold_reminder_title_uses_existing_tr_lower_contract(self):
        from modules import main_planner
        self.ctx.profile.data["events"] = [
            {"id": 49, "title": "İlaç", "when": "2026-11-15T09:00"},
        ]
        with patch.object(self.ctx.profile, "delete_event", return_value=True) as delete:
            entry, reply, feedback = self.typed(
                "ilaç hatırlatmasını sil", "reminders.manage",
                {"operation": "delete", "title": "ilaç"})
            pending = self.ctx._session().pending_confirm
            self.assertIsNotNone(pending)
            self.assertEqual(pending["event_id"], 49)
            self.assertIn("onaylıyor musun", reply)
            done = main_planner.delete_reminder_confirmed(self.ctx, pending)
        self.assertIn("Sildim: İlaç", done)
        delete.assert_called_once_with(49)

    def test_reminder_postpone_requires_exact_confirmation_and_valid_delay(self):
        from modules import main_planner
        # The former fixed Nov 15 time became past during Windows CI;
        # production correctly postponed from NOW. Use a future occurrence.
        from datetime import datetime, timedelta
        original = datetime.now().replace(second=0, microsecond=0) + timedelta(days=1)
        event = {"id": 12, "title": "Rapor", "when": original.strftime("%Y-%m-%dT%H:%M")}
        self.ctx.profile.data["events"] = [event]
        with patch.object(self.ctx.profile, "reschedule_event",
                          side_effect=AssertionError("mutated before approval")) as worker:
            entry, output, feedback = self.typed(
                "Rapor hatırlatmasını 10 dakika ertele", "reminders.manage",
                {"operation": "postpone", "title": "Rapor", "duration": "10 dakika"})
        self.assertEqual(brain_entry.core_plan(entry),
                         ("reminder_manage", {"operation": "postpone", "title": "Rapor", "minutes": 10}))
        self.assertIn("onaylıyor musun", output)
        self.assertEqual(feedback.result_status, "needs_input")
        worker.assert_not_called()
        pending = self.ctx._session().pending_confirm
        with patch.object(self.ctx.profile, "reschedule_event") as commit:
            response = main_planner.modify_reminder_confirmed(self.ctx, pending)
        self.assertIn("erteledim", response)
        commit.assert_called_once_with(12, (original + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M"))

    def test_reminder_postpone_rejects_stale_or_foreign_snapshot(self):
        from modules import main_planner
        event = {"id": 11, "title": "İlaç", "when": "2026-11-15T08:00"}
        self.ctx.profile.data["events"] = [event]
        proposal = {"action": "reminder_modify", "operation": "postpone", "minutes": 20,
                    "owner": self.owner, "event_id": 11, "title": "İlaç",
                    "when": "2026-11-15T08:00", "repeat": None, "base": None}
        with patch.object(self.ctx.profile, "reschedule_event",
                          side_effect=AssertionError("stale reminder mutated")) as worker:
            self.assertIn("başka kullanıcıya", main_planner.modify_reminder_confirmed(
                self.ctx, {**proposal, "owner": "other"}))
            event["when"] = "2026-11-16T08:00"
            self.assertIn("kayıt değişmiş", main_planner.modify_reminder_confirmed(
                self.ctx, proposal))
        worker.assert_not_called()

    def test_typed_taildrop_ambiguous_target_returns_needs_input_and_state_resume(self):
        from modules import filesend
        from pathlib import Path
        root = Path(self.temp.name) / "Downloads"
        root.mkdir(exist_ok=True)
        candidates = [root / "a.pdf", root / "b.pdf"]
        for name in candidates:
            name.write_text("data", encoding="utf-8")
        with patch.object(filesend, "_folders", return_value=[root]), \
             patch.object(filesend, "find", return_value=candidates), \
             patch.object(filesend, "_score_gap", return_value=False), \
             patch.object(filesend, "send", return_value="TRANSFER_OK") as send, \
             patch.object(self.ctx, "handle", wraps=self.ctx.handle) as raw_handler:
            entry, reply, feedback = self.typed(
                "Rapor dosyasını telefonuma gönder", "filesend.transfer",
                {"operation": "search", "query": "Rapor"})
            self.assertIn("hangisini", reply)
            self.assertEqual(feedback.result_status, "needs_input")
            resume, result, handler, resume_feedback = self.turn_real(
                "2", model_understanding=False)
        self.assertEqual(resume.state_gate.protocol, "filesend.pending.select")
        self.assertEqual(result, "TRANSFER_OK")
        self.assertEqual(resume_feedback.result_status, "handled")
        send.assert_called_once_with(candidates[1])
        raw_handler.assert_not_called()

    def test_notes_full_clear_typed_core_requires_existing_state_yes_protocol(self):
        from modules import main_planner
        old = self.ctx.profile.add_note_item("ÖNEMLİ NOT")
        with patch.object(self.ctx.profile, "clear_note_items",
                          side_effect=AssertionError("clear without consent")) as clear:
            entry, preview, feedback = self.typed(
                "tüm notları sil", "notes.manage", {"operation": "clear_all"})
        self.assertEqual(brain_entry.core_plan(entry),
                         ("notes_manage", {"operation": "clear_all"}))
        self.assertIn("onaylıyor musun", preview)
        self.assertEqual(feedback.result_status, "needs_input")
        self.assertEqual(self.ctx.profile.data["items"][0]["id"], old["id"])
        clear.assert_not_called()
        approved, result, handler, status = self.turn_real("evet", model_understanding=False)
        self.assertEqual(approved.state_gate.protocol, "session.pending_confirm.confirm")
        self.assertEqual(status.result_status, "handled")
        self.assertIn("Tüm notlarını sildim", result)
        self.assertEqual(self.ctx.profile.data["items"], [])

    def test_handoff_typed_add_and_list_only_call_existing_google_tasks_worker(self):
        from modules import handoff
        with patch.object(handoff, "execute_typed", return_value="DEVİR") as execute:
            entry, output, feedback = self.typed(
                "Yarın işte raporu kontrol edeceğim", "handoff.manage",
                {"operation": "add", "where": "is", "text": "raporu kontrol edeceğim", "when": "tomorrow"})
        self.assertEqual(brain_entry.core_plan(entry),
                         ("handoff_manage", {"operation": "add", "where": "is",
                                             "text": "raporu kontrol edeceğim", "when": "tomorrow"}))
        self.assertEqual(output, "DEVİR")
        self.assertEqual(feedback.result_status, "handled")
        execute.assert_called_once_with("add", where="is", text="raporu kontrol edeceğim", when="tomorrow")

    def test_handoff_exact_completion_cannot_choose_fuzzy_nearby_task(self):
        from modules import handoff
        candidates = [{"id": "a", "text": "Çizim", "where": "is"},
                      {"id": "b", "text": "Çizim kontrolü", "where": "is"}]
        with patch.object(handoff, "pending", return_value=candidates), \
             patch.object(handoff, "_svc") as service, \
             patch.object(handoff, "_lid", return_value="test-list"):
            service.return_value.tasks.return_value.patch.return_value.execute.return_value = {}
            self.assertIsNone(handoff.complete_exact("çiz"))
            self.assertEqual(handoff.complete_exact("Çizim"), "Çizim")
        service.return_value.tasks.return_value.patch.assert_called_once_with(
            tasklist="test-list", task="a", body={"status": "completed"})

    def test_notify_fallback_negation_does_not_enable_or_send(self):
        from modules import notify
        prefs = {}
        with patch.object(notify, "execute_typed",
                          side_effect=AssertionError("negated notification executed")) as run:
            self.assertIsNone(notify.handle("telefon bildirimini açma", prefs, lambda: None))
            self.assertIsNone(notify.handle("telefona mesaj gönderme", prefs, lambda: None))
        run.assert_not_called()

    def test_task_delete_waits_for_existing_owner_approval(self):
        from modules import tasks
        self.ctx.profile.data['tasks'] = []
        first = tasks.add(self.ctx.profile, 'Raporu hazırla')
        other = tasks.add(self.ctx.profile, 'Başka iş')
        _, output, _ = self.typed('Raporu hazırla görevini sil', 'tasks.manage',
                                     {'operation': 'delete', 'text': 'Raporu hazırla'})
        self.assertIn('Onaylıyor', output)
        self.assertTrue(any(task['id'] == first['id'] for task in self.ctx.profile.data['tasks']))
        pending = self.ctx._session().pending_action
        self.assertEqual(pending['owner'], self.owner)
        self.assertEqual(pending['params'], {'tid': first['id']})
        self.turn_real('evet')
        self.assertFalse(any(task['id'] == first['id'] for task in self.ctx.profile.data['tasks']))
        self.assertTrue(any(task['id'] == other['id'] for task in self.ctx.profile.data['tasks']))
        self.assertIsNone(self.ctx._session().pending_action)

    def test_core_rejects_untrusted_operation_enums_without_effects(self):
        for cap, payload in (
            ("screen.text", {"operation": "delete"}),
            ("screen.text", {"operation": "error_note", "path": "C:/x"}),
            ("device.share", {"action": "screen", "token": "secret"}),
            ("device.share", {"action": "invalid"}),
            ("voice.rate", {"direction": "suppress"}),
            ("voice.rate", {"direction": True}),
            ("brief.read", {"delete": True}),
            ("study.read", {"view": "execute"}),
            ("notes.add", {"text": ""}),
            ("notes.add", {"text": "x" * 5000}),
            ("notes.add", {"text": "ok", "permission": True}),
            ("notes.manage", {"operation": "clear_all", "id": "another-note"}),
            ("notes.manage", {"operation": "delete_last"}),
            ("calendar.read", {"view": "agenda", "period": "seven"}),
            ("calendar.read", {"view": "week_plan", "period": "tomorrow"}),
            ("calendar.read", {"view": "erase", "period": "today"}),
            ("reminders.manage", {"operation": "delete", "id": "fake", "title": "Team"}),
            ("reminders.manage", {"operation": "clear_all", "title": "Team"}),
            ("reminders.manage", {"operation": "postpone", "title": "Team", "duration": "999 gün"}),
            ("reminders.manage", {"operation": "postpone", "title": "Team", "duration": "az sonra"}),
            ("reminders.manage", {"operation": "postpone", "title": "Team"}),
            ("reminders.manage", {"operation": "skip", "title": "Team", "duration": "1 saat"}),
            ("tasks.manage", {"operation": "clear_all", "text": "A"}),
            ("tasks.manage", {"operation": "complete", "text": ""}),
            ("tasks.manage", {"operation": "list", "text": "secret"}),
            ("kb.query", {"question": ""}),
            ("worktrack.read", {"kind": "delete"}),
            ("worktrack.read", {"kind": "status", "project": True}),
            ("hoca.lesson.start", {"topic": ""}),
            ("hoca.lesson.start", {"topic": "İçerik", "source": "/secret.pdf"}),
            ("hoca.lesson.start", {"topic": "İçerik", "level": "unknown"}),
            ("browser.page.read", {"url": "file:///tmp/secret"}),
            ("browser.page.read", {"url": "http://127.0.0.1/admin"}),
            ("browser.page.read", {"url": "http://localhost/"}),
            ("browser.page.read", {"url": "https://user:pass@example.org/"}),
            ("browser.page.read", {"url": "https://example.org:5000/"}),
            ("media.search", {"service": "youtube", "query": ""}),
            ("media.search", {"service": "music_home", "query": "payload"}),
            ("media.search", {"service": "arbitrary", "query": "song"}),
            ("filesend.transfer", {"operation": "search", "query": ""}),
            ("filesend.transfer", {"operation": "screenshot", "query": "secret"}),
            ("filesend.transfer", {"operation": "path", "query": "A"}),
            ("notify.manage", {"operation": "send_all"}),
            ("notify.manage", {"operation": "enable", "topic": "attacker"}),
            ("handoff.manage", {"operation": "add", "where": "other", "text": "check"}),
            ("handoff.manage", {"operation": "complete", "text": ""}),
            ("handoff.manage", {"operation": "list", "text": "secret"}),
            ("workbench.followup", {"operation": "run_code"}),
            ("workbench.followup", {"operation": "revise", "path": "C:/private"}),
            ("workbench.followup", {"operation": "revise", "format": "exe"}),
        ):
            with self.subTest(capability=cap, payload=payload):
                self.assertIsNone(brain_core_map.core_plan(cap, payload))


if __name__ == "__main__":
    unittest.main()
