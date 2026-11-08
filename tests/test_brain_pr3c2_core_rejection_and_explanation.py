"""PR3C-2: Core reddi ham kapıya düşmez; açıklama sorusu etki yetkisi taşımaz.

Ölçülen taban (`d03b944`, yalıtılmış kanonical zincir):

- Kanonical öneri Core'da doğrulanmadığında (`core_plan` None) `handoff` kontrolü
  `handler(command)`'a bırakıyordu. Tam tipli çeviri önerisi (`text.translate`) reddedilince
  ham `_extra_commands` cevabı kullanıcıya dönüyordu (`HAM KAPI CEVABI`), feedback ise `handled`
  diyordu: reddin üzerine etki ve sahte başarı.
- `dosya taşımak güvenli mi?` ve `mail göndermenin riskleri neler?` EXPLANATION_REQUEST
  taşımıyordu; tur ham kapıların tamamını dolaşıyordu.
- `dolar kaç tl ne demek?` hem EXPLANATION_REQUEST hem `research.search` ipucu taşıyordu:
  tanım sorusu `task` planına dönüşüp Goal yürütmesi başlatıyordu.

Bu dosya istenen sözleşmeyi kilitler. `core_plan=None` tek başına ret değildir: yalnız tipli
payload'ı olan (cümle metni dışında alan taşıyan) tam öneri reddedilmiş sayılır; yalnız
`original_text` taşıyan eksik öneri meşru eski sahibinde kalır (`beni uyar`, `dosyayı aç`,
`raporda ara`). Üretim zinciri sınanır; geçici profil/günlük kullanılır, hiçbir etki sınırı
gerçek iş yapmaz.
"""
from __future__ import annotations

import uuid
import unittest
from unittest.mock import Mock, patch

import test_brain_pr3b_legacy_front_door_authority as b3b
from modules import brain_core_map, brain_entry, requests_state
from modules.brain_contracts import RequestKind
from modules.brain_understanding import EXPLANATION_REQUEST_CODE, EXECUTION_REQUEST_CODE

REJECTED_MESSAGE = "güvenli biçimde doğrulayamadım"


class _Pr3c2Harness(b3b._RawDoorHarness):
    """PR3B yalıtılmış hattı + tur başına sıfırlanan kapı/etki defteri."""

    def reset(self) -> None:
        for name in b3b.RAW_DOORS:
            getattr(self.ctx, name).reset_mock()
        for mock in self.seams.values():
            mock.reset_mock()
        self.door.reset_mock()
        self.run_goal.reset_mock()
        self.ctx._mail_handle.reset_mock()
        self.ctx._web_search.reset_mock()
        self.ctx._screen_ocr.reset_mock()
        self.ctx._copy_text.reset_mock()
        self.ctx.tr.reset_mock()

    def owner_silent(self) -> list[str]:
        return self.silent("modules.folder_analysis", "modules.file_ops", "modules.pc_guide",
                           "modules.developer", "modules.task_agents", "modules.watcher",
                           "modules.learning", "modules.finance", "modules.selfctl",
                           "modules.notify", "modules.worktrack", "modules.handoff")

    def codes(self, entry) -> tuple[str, ...]:
        return tuple(entry.understanding.reason_codes)

    def _entry(self, text: str):
        rid = "pr3c2-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            return brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı")

    def superseded(self, text: str) -> bool | None:
        with brain_entry.bind(self._entry(text)):
            return brain_entry.goal_question_superseded(self.ctx)


class CoreRejectionFenceTests(_Pr3c2Harness):
    """Kanonical reddedilmiş tam tipli öneri ham kapıdan ikinci kez yürütülemez (§2)."""

    def _reject(self, text: str):
        self.reset()
        self.ctx._extra_commands = Mock(return_value="HAM KAPI CEVABI")
        with patch.object(brain_entry, "core_plan", lambda entry: None):
            return self.turn(text)

    def test_a_rejected_typed_proposal_never_reaches_the_raw_gate(self):
        entry, out, _handle, _ = self._reject("şu notu ingilizceye çevir")
        self.assertIs(entry.understanding.request_kind, RequestKind.CAPABILITY)
        self.assertIn("translate", entry.understanding.arguments)
        self.assertNotIn("HAM KAPI CEVABI", str(out))
        self.assertIn(REJECTED_MESSAGE, str(out))
        self.ctx._extra_commands.assert_not_called()
        self.assertEqual(self.turn_texts, [])
        self.assertEqual(self.silent("modules.file_ops", "modules.folder_analysis"), [])

    def test_the_rejection_is_a_structured_failure_not_a_false_success(self):
        _entry, _out, _handle, feedback = self._reject("şu notu ingilizceye çevir")
        self.assertEqual(feedback.result_status, "failed")
        self.assertEqual(feedback.reason_code, "CORE_PROPOSAL_REJECTED")

    def test_a_rejected_typed_proposal_runs_no_capability_effect(self):
        self._reject("şu notu ingilizceye çevir")
        self.ctx.tr.translate.assert_not_called()
        self.run_goal.assert_not_called()

    def test_the_fence_is_not_a_general_none_rejection(self):
        # Tipli payload yoksa öneri "eksik"tir, ret değildir: meşru eski sahibi çalışmaya devam eder.
        # Ölçülen taban davranışı korunur: `beni uyar` planner sorusu açar (needs_input),
        # `dosyayı aç`/`raporda ara` mevcut clarify cevabını döner; hiçbiri ret sayılmaz.
        for text in ("beni uyar", "dosyayı aç", "raporda ara"):
            with self.subTest(text=text):
                self.reset()
                entry, out, _handle, feedback = self.turn(text)
                self.assertIs(entry.understanding.request_kind, RequestKind.CAPABILITY)
                self.assertEqual(set(entry.understanding.arguments), {"original_text"})
                self.assertNotEqual(feedback.reason_code, "CORE_PROPOSAL_REJECTED")
                self.assertNotEqual(feedback.result_status, "failed")
                self.assertNotIn(REJECTED_MESSAGE, str(out))
                self.assertEqual(self.door.call_count, 1)
                self.ctx._extra_commands.assert_called_once()
                self.run_goal.assert_not_called()

    def test_a_validated_typed_proposal_still_executes_exactly_once(self):
        self.reset()
        _entry, out, _handle, _ = self.turn("şu notu ingilizceye çevir")
        self.assertEqual(out, "ÇEVİRİ")
        self.ctx.tr.translate.assert_called_once()
        self.ctx._extra_commands.assert_called_once()   # claim sırasındaki mevcut cascade sözleşmesi


class ExplanationRequestAuthorityTests(_Pr3c2Harness):
    """Açıklama/risk soruları etki başlatmaz; gerçek istekler kendi sahibinde kalır (§3)."""

    def _explained(self, text: str):
        self.reset()
        entry, out, _handle, _ = self.turn(text)
        self.assertIn(EXPLANATION_REQUEST_CODE, self.codes(entry), text)
        self.assertIs(entry.understanding.request_kind, RequestKind.CHAT, text)
        self.assertIsNone(entry.understanding.capability_hint, text)
        self.assertEqual(out, "CHAT", text)
        self.assertEqual(self.door.call_count, 1, text)
        for name in b3b.RAW_DOORS:
            getattr(self.ctx, name).assert_not_called()
        self.assertEqual(self.owner_silent(), [])
        self.run_goal.assert_not_called()
        self.ctx._web_search.assert_not_called()
        return entry

    def test_a_safety_question_is_an_explanation_turn(self):
        self._explained("dosya taşımak güvenli mi?")

    def test_a_risk_question_is_an_explanation_turn(self):
        self._explained("mail göndermenin riskleri neler?")

    def test_a_definition_question_that_mentions_a_market_phrase_starts_no_research(self):
        entry = self._explained("dolar kaç tl ne demek?")
        self.assertEqual(set(entry.understanding.arguments), {"original_text"})

    def test_the_already_closed_explanation_examples_stay_closed(self):
        for text in ("döviz kuru nedir?",
                     "rapor dosyasını belgelerime taşımak ne demek?",
                     "ekrandaki metni okumak nasıl yapılır?",
                     "panoya kopyalamak nedir?"):
            with self.subTest(text=text):
                self._explained(text)

    def test_a_real_research_request_still_reaches_its_owner(self):
        self.reset()
        entry, out, _handle, _ = self.turn("dolar kaç tl araştır")
        self.assertEqual(entry.understanding.capability_hint, "research.search")
        self.assertNotIn(EXPLANATION_REQUEST_CODE, self.codes(entry))
        self.assertEqual(brain_core_map.core_plan(entry.understanding.capability_hint,
                                                  entry.understanding.arguments)[0], "task")
        self.assertEqual(out, "GOAL_RUN")
        self.run_goal.assert_called_once()

    def test_a_real_file_move_request_is_unchanged(self):
        self.reset()
        entry, out, _handle, _ = self.turn("bu dosyayı taşı")
        self.assertIn(EXECUTION_REQUEST_CODE, self.codes(entry))
        self.assertNotIn(EXPLANATION_REQUEST_CODE, self.codes(entry))
        self.assertEqual(out, "GOAL_RUN")
        self.run_goal.assert_called_once()

    def test_a_real_draft_request_is_unchanged(self):
        self.reset()
        entry, out, _handle, _ = self.turn("mail taslağı hazırla")
        self.assertIn(EXECUTION_REQUEST_CODE, self.codes(entry))
        self.assertNotIn(EXPLANATION_REQUEST_CODE, self.codes(entry))
        self.assertEqual(out, "GOAL_RUN")
        self.run_goal.assert_called_once()

    def test_a_real_reminder_request_still_reaches_the_reminder_plan(self):
        self.reset()
        entry, _out, _handle, _ = self.turn("yarın bana hatırlat")
        self.assertEqual(entry.understanding.capability_hint, "reminder.propose")
        self.assertNotIn(EXPLANATION_REQUEST_CODE, self.codes(entry))
        self.assertEqual(brain_core_map.core_plan(entry.understanding.capability_hint,
                                                  entry.understanding.arguments)[0], "reminder")

    def test_an_explicit_freshness_request_is_not_demoted_to_explanation(self):
        # Pure Understanding keeps the freshness route; the model-owned finance override is
        # exercised through the production proposal path in test_brain_b3_finance_authority.
        for text in ("güncel dolar kuru nedir?", "bugünkü dolar kuru nedir?"):
            with self.subTest(text=text):
                self.reset()
                entry, out, _handle, _ = self.turn(text)
                self.assertNotIn(EXPLANATION_REQUEST_CODE, self.codes(entry))
                self.assertEqual(entry.understanding.capability_hint, "research.search")
                self.assertEqual(out, "GOAL_RUN")
                self.run_goal.assert_called_once()

    def test_a_fresh_news_tell_request_is_not_an_explanation(self):
        # "haberleri anlat" bir açıklama fiiliyle biter ama taze dış veri isteğidir; tek
        # kanonical tazelik kuralı kazanır, araştırma planı korunur.
        self.reset()
        entry, out, _handle, _ = self.turn("yapay zeka haberlerini anlat")
        self.assertNotIn(EXPLANATION_REQUEST_CODE, self.codes(entry))
        self.assertEqual(entry.understanding.capability_hint, "research.search")
        self.assertEqual(out, "GOAL_RUN")

    def test_a_troubleshooting_question_keeps_its_diagnose_owner(self):
        # Soru işareti tek başına açıklama yetkisi değildir: teşhis sahibi çalışmaya devam eder.
        self.reset()
        _entry, out, _handle, _ = self.turn("neden çalışmıyor?")
        self.assertEqual(out, "ARIZA")
        self.seams["modules.diagnose.run"].assert_called_once()


class DomainOwnerRegressionTests(_Pr3c2Harness):
    """Açıklama hükmü komşu sahipleri (alarm, kural, planner, pending, Goal) yutmaz."""

    def test_guided_advice_keeps_its_pc_guide_owner(self):
        self.reset()
        entry, _out, _handle, _ = self.turn("adım adım wifi nasıl açılır")
        self.assertNotIn(EXPLANATION_REQUEST_CODE, self.codes(entry))
        self.assertTrue(self.seams["modules.pc_guide.handle"].called)

    def test_rule_teaching_still_reaches_learning(self):
        self.reset()
        self.seams["modules.learning.handle"].return_value = "KURAL"
        entry, out, _handle, _ = self.turn("kural ekle: her sabah su iç")
        self.assertNotIn(EXPLANATION_REQUEST_CODE, self.codes(entry))
        self.seams["modules.learning.handle"].assert_called_once()
        self.assertEqual(out, "KURAL")

    def test_an_alarm_sentence_keeps_the_raw_domain_owner(self):
        self.reset()
        entry, _out, _handle, _ = self.turn("dolar 45 tl üstüne çıkarsa haber ver")
        self.assertNotIn(EXPLANATION_REQUEST_CODE, self.codes(entry))
        self.assertIs(entry.understanding.request_kind, RequestKind.CHAT)
        self.ctx._extra_commands.assert_called_once()

    def test_a_pending_confirmation_is_still_consumed(self):
        self.reset()
        self.turn("bilgisayarı kapat")
        self.ctx.system_control.shutdown_pc.assert_not_called()
        self.reset()
        _entry, out, _handle, _ = self.turn("evet")
        self.ctx.system_control.shutdown_pc.assert_called_once_with()
        self.assertIn("60 saniye", str(out))

    def test_a_pending_weather_location_answer_is_still_an_answer(self):
        self.reset()
        self.ctx._session().pending_weather_location = True
        entry, out, _handle, _ = self.turn("İzmir")
        self.assertNotIn(EXPLANATION_REQUEST_CODE, self.codes(entry))
        self.assertEqual(out, "HAVA")
        self.ctx._weather.assert_called_once()
        self.assertFalse(self.ctx._session().pending_weather_location)

    def test_an_explanation_question_supersedes_an_open_goal_question(self):
        # Açıklama sorusu açık Goal sorusunun cevabı değildir; Goal onu tüketemez.
        self.assertTrue(self.superseded("dolar kaç tl ne demek?"))
        self.assertTrue(self.superseded("dosya taşımak güvenli mi?"))

    def test_a_real_answer_does_not_supersede_an_open_goal_question(self):
        self.assertFalse(self.superseded("izmir"))

    def test_a_pending_photo_continuation_keeps_its_typed_photo_proposal(self):
        # Açıklama hükmü açık foto bağlamının tipli önerisini silmez: `bunu açıkla`
        # hâlâ photo.action sahibine gider (taban d03b944 ile aynı sahip).
        from test_brain_photo_followup_relation import decide as photo_decide
        semantic = photo_decide("bunu açıkla")
        self.assertIn(EXPLANATION_REQUEST_CODE, tuple(semantic.reason_codes))
        self.assertEqual(semantic.capability_hint, "photo.action")
        self.assertIs(semantic.request_kind, RequestKind.CAPABILITY)


if __name__ == "__main__":
    unittest.main()
