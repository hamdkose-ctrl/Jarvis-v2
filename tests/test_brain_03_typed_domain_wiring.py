"""BRAIN-03: typed domain workers via real prepare -> handoff -> Core.

No cloud/model/OS/clipboard/image hardware touched; the external semantic
transport and each existing effect boundary are deterministic spies.
"""
from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import Mock, patch

import test_brain_pr3_raw_text_authority as baseline
from modules import brain_core_map, brain_entry, engine_context, engine_intents
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

    def test_core_rejects_untrusted_operation_enums_without_effects(self):
        for cap, payload in (
            ("screen.text", {"operation": "delete"}),
            ("screen.text", {"operation": "error_note", "path": "C:/x"}),
            ("device.share", {"action": "screen", "token": "secret"}),
            ("device.share", {"action": "invalid"}),
            ("voice.rate", {"direction": "suppress"}),
            ("voice.rate", {"direction": True}),
            ("brief.read", {"delete": True}),
        ):
            with self.subTest(capability=cap, payload=payload):
                self.assertIsNone(brain_core_map.core_plan(cap, payload))


if __name__ == "__main__":
    unittest.main()
