"""PR3B: kalan ham anlamsal cepheler (front-door/cascade) kanonical hatta devredilir.

Bu dosya RED olarak yazıldı: kanonical State/Fast/Understanding kararı verildikten sonra bile
`engine_commands.handle` ham kullanıcı cümlesini bağımsız yeniden sınıflandırıyor, bir *soru*
cffekt üretebiliyor, `_TypoRetry` aynı request'te ikinci bir pipeline geçişi çalıştırıyor ve
sıra semantiği ham yüzeyde doğuyor.

Üretim zinciri sınanır: `brain_entry.prepare → handoff → EngineContext.handle`. Canlı kullanıcı
state'i okunmaz (geçici dizin + izole goal/history store); effekte giden her modül sınırı Mock'tur
ve testler "etki hiç çağrılmadı" der. Model/ağ/worker çağrısı yoktur.
"""
from __future__ import annotations

import ast
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import test_brain_pr3_raw_text_authority as pr3a
from modules import brain_entry, engine_commands, finance, git_publish, learning, watcher
from modules.brain_contracts import RequestKind

ROOT = Path(__file__).resolve().parents[1]
ENGINE_COMMANDS_SOURCE = (ROOT / "modules" / "engine_commands.py").read_text(encoding="utf-8")

# Efekte dokuyan modül sınırları: hiçbiri gerçek iş yapmaz, hepsi kaydedilir.
EFFECT_SEAMS = (
    "updater.check", "updater.install_latest", "updater.verify_sync", "updater.status",
    "modules.diagnose.run", "modules.diagnose.summary",
    "modules.folder_analysis.handle", "modules.file_ops.handle",
    "modules.worktrack.handle", "modules.handoff.handle", "modules.notify.handle",
    "modules.finance_alert_commands.matches", "modules.selfctl.handle",
    "modules.media.handle", "modules.filesend.handle",
    "modules.pc_guide.handle", "modules.developer.handle", "modules.task_agents.handle",
)
_EFFECT_DEFAULTS = {"verify_sync": {"sync_state": "clean"}, "status": {"error": "", "sha": "", "msg": ""},
                    "run": {}, "summary": "ARIZA", "matches": False}


class _RawDoorHarness(pr3a._CanonicalAuthorityHarness):
    """Kanonical tur + gerçek legacy kapı; effekte giden her sınır kaydedilmiş Mock."""

    def setUp(self):
        super().setUp()
        self.seams: dict[str, Mock] = {}
        for spec in EFFECT_SEAMS:
            target, attr = spec.rsplit(".", 1)
            module = __import__(target, fromlist=[attr])
            mock = Mock(return_value=_EFFECT_DEFAULTS.get(attr))
            self.seams[f"{target}.{attr}"] = mock
            starter = patch.object(module, attr, mock)
            starter.start()
            self.addCleanup(starter.stop)
        for module, attr, value in ((git_publish, "publish_worktree", "YAYINLANDI"),
                                    (watcher, "handle", None), (learning, "handle", None),
                                    (finance, "answer", None)):
            mock = Mock(return_value=value)
            self.seams[f"{module.__name__}.{attr}"] = mock
            starter = patch.object(module, attr, mock)
            starter.start()
            self.addCleanup(starter.stop)
        for name in ("messaging", "plugins", "browser", "tasks", "kb", "files", "output"):
            stub = Mock(name=name)
            for attr in ("is_whatsapp_message", "quick_parse", "extract", "send_whatsapp",
                         "handle", "wants_organize", "plan_organize", "apply_organize",
                         "save_text_result", "find_contact", "normalize_phone"):
                setattr(stub, attr, Mock(return_value=None))
            stub.extract.return_value = (None, None)
            setattr(self.ctx, name, stub)
        self.ctx._extra_commands = Mock(return_value=None)
        # Core planının meşru effect'i kendi modül sınırında durur: hiçbir test model/ağ çağrısı yapmaz.
        self.ctx.tr = Mock(translate=Mock(return_value="ÇEVİRİ"))
        self.ctx._mail_handle = Mock(return_value=None)
        self.ctx._screen_ocr = Mock(return_value="EKRAN METNİ")
        self.ctx._copy_text = Mock(return_value=True)
        self.ctx._web_search = Mock(return_value="ARAMA")
        self.ctx._file_command = Mock(return_value=None)
        self.ctx._contact_command = Mock(return_value=None)
        self.ctx._study_intent = Mock(return_value=None)
        self.ctx._planner_command = Mock(return_value=None)
        self.ctx._user_command = Mock(return_value=None)
        self.ctx._macro_teach = Mock(return_value=None)
        self.ctx._macro_manage = Mock(return_value=None)
        self.ctx._macro_run = Mock(return_value=None)

        # Legacy kapının kendisi: gerçek, ama her girişi kaydedilir (typo ikinci geçişi görünür).
        real_door = engine_commands.handle
        self.door = Mock(side_effect=real_door, name="engine_commands.handle")
        starter = patch.object(engine_commands, "handle", self.door)
        starter.start()
        self.addCleanup(starter.stop)

    def silent(self, *prefixes: str) -> list[str]:
        """Adı geçen sınır(ler)den hiçbiri çağrılmadı; çağrılanların adlarını döner."""
        return sorted(name for name, mock in self.seams.items()
                      if any(name.startswith(p) for p in prefixes) and mock.called)

    def turn(self, text, handler=None, source="yazı"):
        from modules import requests_state
        rid = "pr3b-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        self.rid = rid
        with requests_state.activate(self.owner, rid):
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source=source)
            handle = handler if handler is not None else self.ctx.handle
            out, feedback, _ = brain_entry.handoff(self.ctx, entry, handle, text)
        self.turn_texts = [call.args[1] for call in self.door.call_args_list]
        return entry, out, handle, feedback


class MetaLanguageEffectFenceTests(_RawDoorHarness):
    """Bir soru/meta cümlesi kanonical olarak icra isteği değildir; hiçbir raw kapı onu effekte taşıyamaz.

    Kök: `brain_entry._use_existing_handler` CHAT/CAPABILITY turunu legacy handler'a düşürüyor ve
    `engine_commands.handle` cümleyi baştan sınıflandırıp effekte gidiyor (ölçüldü: "git yükle ne
    demek?" gerçek yayın denedi, "notları temizle ne demek?" notları sildi)."""

    def test_a_question_about_publishing_publishes_nothing(self):
        entry, _out, _handle, _ = self.turn("git yükle ne demek?")
        self.assertIs(entry.understanding.request_kind, RequestKind.CAPABILITY)
        self.assertIsNone(entry.understanding.capability_hint)
        self.assertEqual(self.silent("updater", "modules.git_publish"), [])

    def test_a_question_about_self_update_installs_nothing(self):
        self.turn("kendini güncelleme nasıl çalışır?")
        self.assertEqual(self.silent("updater"), [])

    def test_a_question_about_diagnostics_runs_no_probes(self):
        self.turn("sistemi kontrol etmek ne demek?")
        self.assertEqual(self.silent("modules.diagnose"), [])

    def test_a_question_about_folder_watch_touches_no_watch_rule(self):
        self.turn("klasör izleme nedir?")
        self.assertEqual(self.silent("modules.watcher"), [])

    def test_a_question_about_learning_writes_no_rule(self):
        self.turn("öğrenme kuralları nasıl çalışır?")
        self.assertEqual(self.silent("modules.learning"), [])

    def test_a_question_about_notes_clearing_clears_no_notes(self):
        entry, out, _handle, _ = self.turn("notları temizle ne demek?")
        self.assertNotIn("sildim", str(out))
        self.ctx._planner_command.assert_not_called()

    def test_a_question_about_whatsapp_does_not_probe_message_ownership(self):
        self.turn("whatsapp nasıl çalışır?")
        self.ctx.messaging.is_whatsapp_message.assert_not_called()
        self.ctx.messaging.extract.assert_not_called()
        self.assertIsNone(self.ctx._session().pending_msg)

    def test_a_question_about_the_screen_error_takes_no_screenshot(self):
        self.turn("ekrandaki hatayı nota eklemeden önce ne yapmalıyım?")
        self.ctx._screen_ocr.assert_not_called()

    def test_a_plain_greeting_consults_no_domain_door(self):
        entry, out, _handle, _ = self.turn("selam")
        self.assertIs(entry.understanding.request_kind, RequestKind.CHAT)
        self.assertEqual(out, "CHAT")
        self.ctx._extra_commands.assert_not_called()
        self.assertEqual(self.silent("modules.selfctl", "modules.media", "modules.notify",
                                     "modules.worktrack", "modules.finance_alert_commands"), [])

    def test_an_unmapped_execution_command_keeps_its_current_owner(self):
        # PR3B blind fence değildir: icra isteği olan ve kanonical sahibi henüz olmayan cümle
        # kapısına ulaşmaya devam eder (parity PR3C envanterinde).
        self.turn("İndirilenler'i izle")
        self.assertEqual([name for name, m in self.seams.items()
                          if name.endswith("watcher.handle") and m.called], ["modules.watcher.handle"])


class TypoSinglePassTests(_RawDoorHarness):
    """Yazım düzeltme aynı request içinde ikinci bir pipeline geçişi çalıştırmaz (BRAIN-MIG-042)."""

    def test_module_has_no_second_pipeline_retry(self):
        tree = ast.parse(ENGINE_COMMANDS_SOURCE)
        names = {node.name for node in ast.walk(tree) if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
        self.assertNotIn("_TypoRetry", names)
        entry_point = next(node for node in tree.body
                           if isinstance(node, ast.FunctionDef) and node.name == "handle_request")
        recursive = {node.func.id for node in ast.walk(entry_point)
                     if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertNotIn("handle", recursive)

    def test_the_door_runs_once_with_the_users_own_sentence(self):
        for text in ("kotrol et", "whatsapp nasıl çalışır?", "notlarımı göstr"):
            with self.subTest(text=text):
                self.door.reset_mock()
                self.turn(text)
                self.assertEqual(self.turn_texts, [text],
                                 "aynı request'te düzeltilmiş metin ikinci kez kapıya giremez")

    def test_model_fallback_keeps_the_users_own_words(self):
        self.turn("yarış merhaba")
        self.assertTrue(self.ctx.chat.called)
        self.assertEqual(self.ctx.chat.call_args.args[0], "yarış merhaba")


class MultiStepAuthorityTests(_RawDoorHarness):
    """Sıra semantiği kanonical katmanda doğar; ham yüzey adım seçmez (BRAIN-MIG-017)."""

    def test_engine_surface_does_not_split_the_user_sentence(self):
        tree = ast.parse(ENGINE_COMMANDS_SOURCE)
        calls = {node.func.attr for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        names = {node.func.id for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertTrue({"_split_steps", "_run_steps"}.isdisjoint(calls | names))

    def test_two_steps_run_their_own_typed_effect_once_each(self):
        entry, out, _handle, _ = self.turn("önce sesi kıs sonra sonraki müzik")
        self.assertEqual(self.rid, entry.request_id)
        self.ctx._volume_step.assert_called_once_with(-10, "kıstım")
        self.ctx.system_control.media_control.assert_called_once_with("next")
        self.assertIn("1.", out)
        self.assertIn("2.", out)


class DispatchArmFenceTests(_RawDoorHarness):
    """`command_manager.dispatch` geniş kolları bir soruyu rehberlik/görev/geliştirme turu yapmaz."""

    def test_an_informational_question_starts_no_guided_or_development_task(self):
        entry, _out, _handle, _ = self.turn("fotosentez nedir")
        self.assertIs(entry.understanding.request_kind, RequestKind.CHAT)
        self.assertEqual(self.silent("modules.pc_guide", "modules.developer", "modules.task_agents"), [])

    def test_a_question_about_a_visual_type_opens_no_image_draft(self):
        # Ölçüldü (taban): ilk kol görsel taslağı başlattı ve "sohbetten mi, dosyadan mı?" sordu;
        # sonraki "sohbet" cevabı ücretli görsel üretir. Bir soru görsel akışının sahibi olamaz.
        _entry, out, _handle, _ = self.turn("infografik nedir?")
        self.assertIsNone(self.ctx._session().pending_visual)
        self.assertNotIn("nereden gelsin", str(out))

    def test_a_question_about_the_workflow_grammar_is_not_a_usage_error(self):
        # Ölçüldü (taban): sabit önek kolu "görev akışı nedir?"i bozuk kullanım sayıp ValueError attı.
        _entry, out, _handle, _ = self.turn("görev akışı nedir?")
        self.assertNotIn("Kullanım:", str(out))

    def test_advisory_guidance_keeps_its_canonical_owner(self):
        # PR3B soru-fencesi rehberlik kolunu kapatmaz: "adım adım" kanonical advisory isteğidir.
        self.turn("adım adım wifi nasıl açılır")
        self.assertTrue(self.seams["modules.pc_guide.handle"].called)

    def test_an_explicit_task_still_reaches_its_current_owner(self):
        _entry, out, _handle, _ = self.turn("görev: raporu özetle")
        self.assertTrue(self.door.called)
        self.assertNotEqual(out, "CHAT")


class CoreRejectionFenceTests(_RawDoorHarness):
    """Kanonical reddedilmiş typed öneri legacy ham kapıya düşüp effekte dönüşmez (bölüm 24)."""

    def test_rejected_capability_does_not_reopen_the_raw_door(self):
        entry, out, _handle, _ = self.turn("şu notu ingilizceye çevir")
        self.assertIs(entry.understanding.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(self.silent("modules.file_ops", "modules.folder_analysis"), [])
        self.assertNotIn("HANDLER", str(out))

    def test_files_refusal_still_fails_closed(self):
        entry, out, _handle, _ = self.turn("gizli.txt dosyasını özetle")
        self.assertIs(entry.understanding.request_kind, RequestKind.CLARIFY)
        self.door.assert_not_called()


if __name__ == "__main__":
    unittest.main()
