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
from modules import brain_core_map, brain_entry, engine_context, engine_intents, workbench
from modules.brain_contracts import RequestKind


class TypedDomainWiringTests(baseline._CanonicalAuthorityHarness):
    @staticmethod
    def adopt(capability, arguments):
        def choose(current, utterance, *, active_context=None):
            return replace(
                current, request_kind=RequestKind.CAPABILITY,
                capability_hint=capability, arguments=arguments,
                ambiguities=(), needs_input=False,
            )
        return choose

    def typed(self, utterance, capability, arguments):
        with patch.object(brain_entry, "apply_model_understanding",
                          side_effect=self.adopt(capability, arguments)), \
             patch.object(self.ctx, "_user_controls",
                          side_effect=AssertionError("legacy controls invoked")) as controls, \
             patch.object(self.ctx, "_planner_command",
                          side_effect=AssertionError("raw planner invoked")) as planner, \
             patch.object(self.ctx, "_extra_commands",
                          side_effect=AssertionError("raw cascade invoked")) as cascade:
            entry, output, _handler, feedback = self.turn_real(
                utterance, model_understanding=True)
        controls.assert_not_called()
        planner.assert_not_called()
        cascade.assert_not_called()
        return entry, output, feedback

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
        source.write_text("item,value\\nA,1\\n", encoding="utf-8")
        with workbench._LOCK:
            workbench._LAST[self.owner] = {
                "paths": [str(source)], "instruction": "tablo yap",
                "at": time.monotonic(), "ext": ".xlsx",
            }
        self.addCleanup(workbench._LAST.pop, self.owner, None)
        return source

    def test_workbench_revision_uses_core_bound_owner_digest_and_path_permission(self):
        source = self._record_recent_workbench()
        with patch("modules.nxapi.allowed", return_value=source) as allowed, \\
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
        with patch("modules.study._state", return_value={"docs": ["lesson"]}), \\
             patch("modules.studyexam.plan", return_value=schedule) as worker:
            entry, output, feedback = self.typed(
                "Ders programımı söyle", "study.read", {"view": "plan"})
        self.assertEqual(brain_entry.core_plan(entry), ("study_read", {"view": "plan"}))
        self.assertIn("Matematik 30 dakika", output)
        self.assertEqual(feedback.result_status, "handled")
        worker.assert_called_once()

    def test_study_focus_is_typed_and_unconfigured_sources_are_reported(self):
        with patch("modules.study._state", return_value={"docs": []}), \\
             patch("modules.studyexam.focus",
                   side_effect=AssertionError("no study material")) as worker:
            entry, output, _ = self.typed(
                "Hangi konuya çalışmalıyım?", "study.read", {"view": "focus"})
        self.assertEqual(brain_entry.core_plan(entry), ("study_read", {"view": "focus"}))
        self.assertIn("önce bir konu", output)
        worker.assert_not_called()

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
            ("workbench.followup", {"operation": "run_code"}),
            ("workbench.followup", {"operation": "revise", "path": "C:/private"}),
            ("workbench.followup", {"operation": "revise", "format": "exe"}),
        ):
            with self.subTest(capability=cap, payload=payload):
                self.assertIsNone(brain_core_map.core_plan(cap, payload))


if __name__ == "__main__":
    unittest.main()
