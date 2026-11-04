"""PR3B: kalan ham anlamsal cepheler (front-door/cascade) kanonical hatta devredilir.

Bu dosya RED olarak yazıldı: kanonical State/Fast/Understanding kararı verildikten sonra bile
`engine_commands.handle` ham kullanıcı cümlesini bağımsız yeniden sınıflandırıyor, bir *soru*
cffekt üretebiliyor, `_TypoRetry` aynı request'te ikinci bir pipeline geçişi çalıştırıyor ve
sıra semantiği ham yüzeyde doğuyor. Kapanan maddeler bu dosyada kilit olarak durur (aşağıdaki
sınıf docstring'leri hangi hükmün artık üretimde olduğunu yazar); kapanmayanlar RED kalır.

Üretim zinciri sınanır: `brain_entry.prepare → handoff → EngineContext.handle`. Canlı kullanıcı
state'i okunmaz (geçici dizin + izole goal/history store); effekte giden her modül sınırı Mock'tur
ve testler "etki hiç çağrılmadı" der. Model/ağ/worker çağrısı yoktur.
"""
from __future__ import annotations

import ast
import inspect
import re
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_brain_pr3_raw_text_authority as pr3a
from modules import brain_entry, engine_commands, finance, git_publish, learning, typo, watcher
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

# Ham cümleyi kapılarına soran yüzey kapıları: soru turunda hiçbiri çağrılmamalı (§28).
RAW_DOORS = ("_file_command", "_planner_command", "_user_command", "_contact_command",
             "_extra_commands")


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
        # PR3C-2: tanım sorusu artık CHAT hükmüdür (yayın yeteneği taşımaz).
        self.assertIs(entry.understanding.request_kind, RequestKind.CHAT)
        self.assertIn("EXPLANATION_REQUEST", tuple(entry.understanding.reason_codes))
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
        calls = [node.func.id for node in ast.walk(entry_point)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
        self.assertEqual(calls, ["handle"], "giriş tek bir geçiş çalıştırır, başka hiçbir şey yapmaz")
        self.assertFalse(any(isinstance(node, (ast.For, ast.While)) for node in ast.walk(entry_point)))

    def test_the_door_runs_once_with_the_users_own_sentence(self):
        corpus = ("kotrol et", "whatsapp nasıl çalışır?", "notlarımı göstr",
                  "notlari temizle", "yarinki randevularimi soyle", "seviyeyi 40 yap")
        for text in corpus:
            with self.subTest(text=text):
                self.door.reset_mock()
                self.turn(text)
                self.assertEqual(self.turn_texts, [text],
                                 "aynı request'te düzeltilmiş metin ikinci kez kapıya giremez")

    def test_model_fallback_keeps_the_users_own_words(self):
        self.turn("yarış merhaba")
        self.assertTrue(self.ctx.chat.called)
        self.assertEqual(self.ctx.chat.call_args.args[0], "yarış merhaba")

    def test_the_corrected_view_reaches_only_the_closed_exact_admin_set(self):
        # §25 A / Karar B: düzeltilmiş görünümün tek yetkisi tam-cümle exact admin tanıyıcılarıdır.
        # Yeni bir kol listeye ancak bilinçli olarak eklenebilir; domain akışları giremez.
        tree = ast.parse((ROOT / "modules" / "command_manager.py").read_text(encoding="utf-8"))
        arm = next(node for node in tree.body
                   if isinstance(node, ast.FunctionDef) and node.name == "exact_admin_view")
        self.assertEqual({ast.unparse(node.func) for node in ast.walk(arm) if isinstance(node, ast.Call)},
                         {"usage_meter.handle", "smart_router.handle", "system_doctor.handle",
                          "diagnose.requested", "diagnose.run", "diagnose.summary",
                          "brain_gates.conversation_summary_request", "brain_gates.table_request",
                          "context.conversation_summary", "context.table_chat"})

    def test_the_surface_consults_the_closed_set_exactly_once(self):
        tree = ast.parse(ENGINE_COMMANDS_SOURCE)
        calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
        self.assertEqual(calls.count("exact_admin_view"), 1)
        self.assertEqual(calls.count("runtime.typo.fix"), 1)
        self.assertEqual(_source_calls("typo.fix"), ["modules/engine_commands.py"])

    def test_a_diacritic_only_misspelling_still_reaches_its_exact_admin_owner(self):
        # Tek ölçülen kazanç sınıfı: cümlenin tek eksiği Türkçe karakter, tek farkı exact admin grameri.
        self.ctx._conversation_summary = Mock(return_value="ÖZET")
        self.door.reset_mock()
        _entry, out, _handle, _ = self.turn("konusmayi ozetle")
        self.assertEqual(self.turn_texts, ["konusmayi ozetle"])
        self.ctx._conversation_summary.assert_called_once_with()
        self.assertEqual(out, "ÖZET")

    def test_a_corrected_view_reaches_no_effect_gate(self):
        # Ölçülen taban: ikinci geçiş effekte giden kapıları düzeltilmiş metinle *tekrar* çalıştırıyordu
        # ("yarinki randevularimi soyle" -> "yarınki randevularimi sö", "raporuwhatsapp ile ahmeta
        # gönder" -> "… ahmet"). Ölçülen kazanç: ham cümle bu kapılara zaten kendi yazımıyla ulaşıyor
        # ("notlari temizle" planner kapısına girdi), yani düzeltmenin domain effekte yetkisi yoktu.
        gates = (self.ctx._planner_command, self.ctx._file_command, self.ctx._user_command)
        for text in ("notlari temizle", "yarinki randevularimi soyle", "indirilenleri duzenle"):
            with self.subTest(text=text):
                self.door.reset_mock()
                for gate in gates:
                    gate.reset_mock()
                self.turn(text)
                self.assertEqual(self.turn_texts, [text])
                seen = [call.args[0] for gate in gates for call in gate.call_args_list if call.args]
                self.assertNotIn(typo.fix(text.casefold()), seen,
                                 "düzeltilmiş görünüm effekte giden bir kapıya ulaşamaz")


class TypoReadRecoveryTests(_RawDoorHarness):
    """Taban kazancı: ilk değerlendirme hiçbir kol almadan düştüğünde düzeltilmiş görünüm aynı
    request içinde yalnız tam-cümle SALT-OKUMA gramerlerine gösterilir.

    Ölçülen taban (`ea2f0b3`, 496 satır gerçek üretim zinciri, effekte giden her sınır Mock):
    `_TypoRetry` 47 satırda ikinci geçişi çalıştırdı, 5 satırda kullanıcıya görünen sonuç değişti ve
    ikinci geçişte mutasyonlu effect çağıran satır YOK (0). Ölçülen üç gerçek salt-okuma kazancı
    burada kilitlenir — not listesi, günün programı, görev listesi. Yazma/organize/tarayıcı açma
    kollara kazanç listesinde bulunmadığı için yine yetki yoktur.
    """

    def _instrument(self) -> dict[str, int]:
        """State/Fast/Understanding ve kurtarma kapısı sarılır: ikinci bir geçiş sayılırsa görünür."""
        from modules import command_manager
        counts = {"understand": 0, "state": 0, "fast": 0, "recovery": 0}

        def wrap(target, attr, key):
            real = getattr(target, attr)

            def spy(*args, **kwargs):
                counts[key] += 1
                return real(*args, **kwargs)

            starter = patch.object(target, attr, spy)
            starter.start()
            self.addCleanup(starter.stop)

        wrap(brain_entry, "understand", "understand")
        wrap(brain_entry, "exact_state_gate", "state")
        wrap(brain_entry, "deterministic_fast_gate", "fast")
        wrap(command_manager, "typo_read_recovery", "recovery")
        return counts

    def _spy_dispatch(self) -> list[tuple]:
        from modules import engine_intents
        real = engine_intents.dispatch
        calls: list[tuple] = []

        def spy(runtime, intent, a, command, cmd_lower):
            calls.append((intent, dict(a), command, cmd_lower))
            return real(runtime, intent, a, command, cmd_lower)

        starter = patch.object(engine_intents, "dispatch", spy)
        starter.start()
        self.addCleanup(starter.stop)
        return calls

    def test_a_misspelled_notes_read_still_reads_the_notes_once(self):
        self.ctx.profile.data["items"] = [{"id": 1, "text": "irsaliye tarihi perşembe"}]
        counts, intents = self._instrument(), self._spy_dispatch()
        entry, out, _handle, _ = self.turn("notlarımı göstr")
        self.assertIs(entry.understanding.request_kind, RequestKind.CHAT,
                      "ham cümle kanonical olarak reddedildi; kurtarma ikinci pipeline değildir")
        self.assertEqual(out, "Notların: 1) irsaliye tarihi perşembe", "tabanın kullanıcıya görünen sonucu")
        self.assertEqual(intents, [("notes_read", {"which": "all"}, "notlarımı göstr", "notlarımı göstr")],
                         "etki kanonical intent sahibi ve kullanıcının own cümlesiyle yürür")
        self.assertEqual(self.turn_texts, ["notlarımı göstr"])
        self.assertEqual(counts, {"understand": 1, "state": 1, "fast": 1, "recovery": 1})
        self.assertEqual(self.silent("modules.folder_analysis", "modules.file_ops",
                                     "modules.media", "modules.notify", "modules.worktrack"), [])
        seen = [arg for call in self.seams["modules.selfctl.handle"].call_args_list for arg in call.args]
        self.assertNotIn(typo.fix("notlarımı göstr"), seen,
                         "salt-okuma kurtarması düzeltilmiş metni hiçbir efekt kapısına taşımaz")
        seen = [call.args[0] for call in self.ctx._planner_command.call_args_list if call.args]
        self.assertNotIn(typo.fix("notlarımı göstr"), seen,
                         "kurtarma ham kapıyı düzeltilmiş metinle yeniden yürütmez")

    def test_a_misspelled_agenda_read_still_answers_the_day_plan(self):
        counts = self._instrument()
        self.ctx._agenda_text = Mock(return_value="Bugün: 09:00 ders")
        opener = Mock()
        starter = patch("webbrowser.open", opener)
        starter.start()
        self.addCleanup(starter.stop)
        entry, out, _handle, _ = self.turn("takvimimi kotrol et")
        self.assertIs(entry.understanding.request_kind, RequestKind.CHAT)
        self.assertEqual(out, "Bugün: 09:00 ders", "tabanın gün programı cevabı")
        self.assertEqual(self.ctx._agenda_text.call_count, 1)
        self.assertEqual(self.ctx._agenda_text.call_args.args[1], "Bugün")
        opener.assert_not_called()  # tarayıcı açmak etkidi: düzeltilmiş görünüme kapalı
        self.assertEqual(self.turn_texts, ["takvimimi kotrol et"])
        self.assertEqual(counts, {"understand": 1, "state": 1, "fast": 1, "recovery": 1})

    def test_a_misspelled_task_list_read_still_answers_the_list(self):
        from modules import tasks as tasks_module
        counts = self._instrument()
        self.ctx.tasks = tasks_module  # gerçek salt-okuma grameri, izole profil üzerinde
        for attr in ("add", "toggle", "delete", "clear_done"):
            starter = patch.object(tasks_module, attr, Mock(side_effect=AssertionError("görev yazma yetkisi yok")))
            starter.start()
            self.addCleanup(starter.stop)
        entry, out, _handle, _ = self.turn("gorevlerimi listelee")
        self.assertIs(entry.understanding.request_kind, RequestKind.CHAT)
        self.assertEqual(out, "Açık görevin yok.", "tabanın görev listesi cevabı")
        self.assertEqual(self.turn_texts, ["gorevlerimi listelee"])
        self.assertEqual(counts, {"understand": 1, "state": 1, "fast": 1, "recovery": 1})

    def test_the_recovery_is_consulted_only_when_the_spelling_actually_changed(self):
        counts = self._instrument()
        for text in ("notlarımı göster", "saat kaç", "takvimimi kontrol et",
                     "görevlerimi listele", "selam"):
            with self.subTest(text=text):
                self.door.reset_mock()
                self.turn(text)
        self.assertEqual(counts["recovery"], 0,
                         "yazımı zaten doğru olan turlar kurtarmaya inmez: koşul düzeltmenin gerçekten fark üretmesi")

    def test_the_corrected_view_still_earns_no_write_open_or_organize_authority(self):
        counts = self._instrument()
        corpus = ("rapor hazırla", "aynı isimli dosyayı bul", "silah nasıl çalışır", "olarak başla",
                  "masaüstünü duzenle", "indirilenleri duzenle", "notlari temizle",
                  "yarinki randevularimi soyle", "bana hetırlat")
        gates = (self.ctx._planner_command, self.ctx._file_command, self.ctx._user_command)
        for text in corpus:
            with self.subTest(text=text):
                self.door.reset_mock()
                for gate in gates:
                    gate.reset_mock()
                _entry, out, _handle, _ = self.turn(text)
                corrected = typo.fix(text.casefold())
                seen = [call.args[0] for gate in gates for call in gate.call_args_list if call.args]
                self.assertNotIn(corrected, seen, "düzeltilmiş görünüm effekte giden ham kapıya ulaşamaz")
                self.assertEqual(self.turn_texts, [text])
                # Aynı cümle düzeltme hiç uygulanmasa da aynı sonucu verir: kurtarma yalnız okur.
                self.door.reset_mock()
                identity = patch.object(self.ctx, "typo", SimpleNamespace(fix=lambda value: value))
                identity.start()
                self.addCleanup(identity.stop)
                _entry2, out_identity, _handle2, _ = self.turn(text)
                identity.stop()
                self.assertEqual(out, out_identity)
                self.assertLessEqual(counts["recovery"], len(corpus))

    def test_a_write_intent_proposed_for_the_corrected_view_is_refused(self):
        from modules import brain_core_map, brain_understanding
        counts = self._instrument()
        intents = self._spy_dispatch()
        starter = patch.object(brain_understanding, "notes_read_view", Mock(return_value=("notes.write", {})))
        starter.start()
        self.addCleanup(starter.stop)
        starter = patch.object(brain_core_map, "core_plan", Mock(return_value=("notes_write", {"operation": "delete"})))
        starter.start()
        self.addCleanup(starter.stop)
        self.ctx.profile.data["items"] = [{"id": 1, "text": "silinecek not"}]
        _entry, out, _handle, _ = self.turn("notlarımı göstr")
        self.assertEqual(out, "CHAT", "yazma niyeti düzeltilmiş görünüm için asla yürümez")
        self.assertEqual([row[0] for row in intents], ["chat"], "kapalı set dışındaki intent dispatch edilmez")
        self.assertEqual(counts["recovery"], 1)
        self.assertEqual(self.ctx.profile.data["items"], [{"id": 1, "text": "silinecek not"}],
                         "reddedilen yazma niyeti not defterine dokunmaz")


def _typo_recovery_source() -> str:
    import ast as _ast
    tree = _ast.parse((ROOT / "modules" / "command_manager.py").read_text(encoding="utf-8"))
    return "\n\n".join(_ast.unparse(node) for node in tree.body
                       if isinstance(node, _ast.FunctionDef)
                       and node.name in {"typo_read_recovery", "typo_read_plan"})


class TypoReadRecoveryGuardTests(unittest.TestCase):
    """Kurtarma yüzeyi kapalı ve tek çağrılıdır: yeni bir mini-router doğarsa bu test düşer."""

    def test_the_surface_is_called_once_from_the_command_seam_only(self):
        self.assertEqual(_source_calls("typo_read_recovery"), ["modules/engine_commands.py"])
        self.assertEqual(_source_calls("typo_read_plan"), ["modules/engine_commands.py"])
        calls = [ast.unparse(node.func) for node in ast.walk(ast.parse(ENGINE_COMMANDS_SOURCE))
                 if isinstance(node, ast.Call)]
        self.assertEqual(calls.count("typo_read_recovery"), 1)
        self.assertEqual(calls.count("typo_read_plan"), 1)
        self.assertEqual(calls.count("exact_admin_view"), 1)
        self.assertEqual(calls.count("runtime.typo.fix"), 1)

    def test_the_recovery_consults_only_named_read_grammars(self):
        source = _typo_recovery_source()
        self.assertTrue(source, "typo_read_recovery/typo_read_plan tanımlı değil")
        called = {ast.unparse(node.func) for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)}
        self.assertEqual(called, {"brain_understanding.notes_read_view", "brain_core_map.core_plan",
                                  "main_planner.agenda_read_request", "runtime.datetime.now",
                                  "runtime._agenda_text", "tasks.list_request", "tasks.list_text"},
                         f"kurtarma yüzeyi kapalı okuma seti dışına çıktı: {sorted(called)}")

    def test_the_recovery_itself_selects_no_effect(self):
        # Intent yürütme yetkisi seam'de kalır: kurtarma yüzeyi dispatch çağıran yeni bir üretici değildir.
        from test_brain_orphan_dispatch_guard import _production_sources, dispatch_call_sites
        self.assertEqual(set(dispatch_call_sites(_production_sources())),
                         {"modules/brain_entry.py", "modules/engine_commands.py"})

    def test_only_read_intents_can_be_dispatched_from_the_corrected_view(self):
        from modules import command_manager
        self.assertEqual(command_manager._TYPO_READ_INTENTS, frozenset({"notes_read"}))
        self.assertNotIn("notes_write", command_manager._TYPO_READ_INTENTS)
        self.assertTrue(command_manager._TYPO_READ_INTENTS.isdisjoint(
            {"reminder", "notes_write", "file_action", "app_open", "app_close", "task", "audio_action",
             "media_action", "screen_capture", "shutdown_request", "photo_action"}))


class ExplanationFenceOwnershipTests(_RawDoorHarness):
    """Çit, sahipliği olan turu domain kapısından çalamaz (§28 ile §25'in kesiştiği yer).

    `brain_entry.explanation_turn()` kanonical EXPLANATION hükmünü legacy ham cephelerin önüne
    çit olarak koyar. Çidin kendisi bir kazanç; ama bir domain kapısı bu cümleye *gerçekten*
    yanıt veriyorsa çit onu yutamaz. Ölçüm (16 satır, taban = çit yok / tepe = çit açık, aynı
    üretim zinciri): kullanıcıya görünen çıktının değiştiği tek satır yok. Bu sınıf o ölçümü
    çifte kilitler — (a) Hoca/rehber/geliştirme kapısının aldığım her cümle kapıda kalır ve
    yanıtı kazanır, (b) çidin ateşlediği her cümlede tabanın çıktısıyla tepe aynıdır."""

    LESSON = {"topic": "Türev", "active": 1, "done": False,
              "steps": [{"title": "Giriş", "goal": "kavram"},
                        {"title": "Uygulama", "goal": "soru çözümü"}],
              "pending": {"step": 1, "question": "Türevin tanımını söylesene."}}

    def seed(self):
        self.ctx.profile.data["hoca"] = {"lesson": dict(self.LESSON)}
        self.ctx.profile.data["study"] = {"mode": "teacher",
                                          "docs": [{"kind": "book", "title": "Fizik"}],
                                          "progress": []}

    def fence_of(self, text) -> bool:
        from modules import requests_state
        rid = "fence-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text=text, source="yazı")
            with brain_entry.bind(entry):
                return brain_entry.explanation_turn()

    def without_fence(self, text):
        """Tabanın kendisi: çit yokken aynı tur (db44bd0 öncesi sıra)."""
        self.seed()
        starter = patch.object(brain_entry, "explanation_turn", lambda: False)
        starter.start()
        try:
            self.door.reset_mock()
            return self.turn(text)[1]
        finally:
            starter.stop()

    def with_fence(self, text, quiet: bool = False):
        self.seed()
        self.door.reset_mock()
        if quiet:
            # Taban turunun bıraktığı izler silinir: çit kapalıyken kapılar hiç çağrılmamalı.
            for mock in self.seams.values():
                mock.reset_mock()
            self.ctx._study_intent.reset_mock()
            for gate in RAW_DOORS:
                getattr(self.ctx, gate).reset_mock()
        return self.turn(text)[1]

    def test_hoca_owning_sentences_stay_with_the_hoca_door(self):
        # Ölçülen: bu cümlelerde çit ateşlenmiyor (state/fast/pend/hint ya da EXPLANATION değil)
        # ve Hoca kapısının yanıtı kullanıcıya görünen sonuç.
        self.ctx._study_intent = Mock(return_value="HOCA YANITI")
        for text in ("hoca modu: hücre", "hücre konusunu öğret", "zayıf konularım", "cevap: eğim",
                     "bilmiyorum", "bugün ne çalışayım", "hangi konuya çalışmalıyım", "çalışmaya başla"):
            with self.subTest(text=text):
                self.assertFalse(self.fence_of(text), "Hoca kapısının cümlesi açıklama turu sayılamaz")
                self.ctx._study_intent.reset_mock()
                out = self.with_fence(text)
                self.assertEqual(out, "HOCA YANITI")
                self.assertEqual(self.ctx._study_intent.call_args_list, [((text,), {})],
                                 "kapı kendi ham cümlesiyle çağrılır")

    def test_hoca_control_phrases_are_owned_by_the_canonical_state_gate(self):
        for text in ("sonraki adıma geç", "dersi bitir"):
            with self.subTest(text=text):
                self.assertFalse(self.fence_of(text), "bounded state protokolü turu zaten aldı")

    def test_the_domain_doors_still_receive_their_questions(self):
        for seam, text in (("modules.pc_guide.handle", "ekrandaki klasör ne işe yarar?"),
                           ("modules.developer.handle", "bu hata neden oluyor?")):
            with self.subTest(text=text):
                self.assertFalse(self.fence_of(text))
                self.seams[seam].return_value = "KAPIT YANITI"
                self.addCleanup(setattr, self.seams[seam], "return_value", None)
                self.assertEqual(self.with_fence(text), "KAPIT YANITI")

    def test_an_active_lesson_question_loses_nothing_to_the_fence(self):
        # Ölçülen kapının hükmü: aktif derste serbest açıklama sorusuna Hoca yanıt üretmiyor
        # (`hoca.handle` yalnız kontrol/cevap/zayıf konu sözcüklerinde yanıt verir). O yüzden
        # çit bir kazanç taşımaz: taban ve tepe aynı kullanıcıya görünen sonuç.
        for text in ("bu adımı biraz daha açıklar mısın?", "burada ne yapmam gerekiyor?",
                     "fotosentez nedir"):
            with self.subTest(text=text):
                self.assertTrue(self.fence_of(text))
                base = self.without_fence(text)
                self.assertEqual(base, self.with_fence(text, quiet=True))
                self.assertEqual(self.silent("modules.pc_guide", "modules.developer", "modules.diagnose"), [])
                self.assertEqual(self.ctx._study_intent.call_args_list, [])

    def test_the_fence_never_consumes_an_open_bounded_pending(self):
        self.seed()
        pending = {"kind": "app_open", "target": "Paint", "owner": self.ctx.profile.slug,
                   "expires": time.time() + 60, "resume": {}}
        self.ctx._session().pending_action = dict(pending)
        self.addCleanup(setattr, self.ctx._session(), "pending_action", None)
        _entry, out, _handle, _ = self.turn("notları temizle ne demek?")
        self.assertEqual(out, self.without_fence("notları temizle ne demek?"))
        self.assertEqual(self.ctx._session().pending_action, pending,
                         "ilgisiz soru bekleyen onayı tüketmez")

    def test_the_answer_to_an_open_pending_is_not_an_explanation_turn(self):
        self.seed()
        self.ctx._session().pending_action = {"kind": "app_open", "target": "Paint",
                                              "owner": self.ctx.profile.slug,
                                              "expires": time.time() + 60, "resume": {}}
        self.addCleanup(setattr, self.ctx._session(), "pending_action", None)
        self.assertFalse(self.fence_of("evet"), "onay yanıtı açıklama turu değildir")
        from modules import requests_state
        rid = "fence-" + uuid.uuid4().hex[:8]
        requests_state.register(self.owner, rid)
        with requests_state.activate(self.owner, rid):
            entry = brain_entry.prepare(self.ctx, owner=self.owner, request_id=rid, text="evet", source="yazı")
            with brain_entry.bind(entry):
                self.assertTrue(brain_entry.pending_answer_owned("pending_action"))

    def test_a_plain_explanation_reaches_no_raw_door(self):
        self.seed()
        for gate in RAW_DOORS:
            getattr(self.ctx, gate).reset_mock()
        self.door.reset_mock()
        self.turn("fotosentez nedir")
        self.assertEqual([call.args[0] for gate in RAW_DOORS
                          for call in getattr(self.ctx, gate).call_args_list if call.args], [],
                         "çit açıkken ham kapılar soruya hiç bakmaz")
        self.assertEqual(self.ctx._study_intent.call_args_list, [])


class MultiStepAuthorityTests(_RawDoorHarness):
    """Sıra semantiği kanonical katmanda doğar; ham yüzey adım seçmez (BRAIN-MIG-017)."""

    def test_engine_surface_carries_no_sequence_grammar(self):
        tree = ast.parse(ENGINE_COMMANDS_SOURCE)
        calls = {node.func.attr for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        names = {node.func.id for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        # Bölme grameri yüzeyde hiç duramaz: ne fonksiyon çağrısı ne de runtime regex'i.
        self.assertTrue({"_split_steps"}.isdisjoint(calls | names))
        self.assertNotIn("_STEP_SPLIT", attrs)
        self.assertIn("step_plan", calls)

    def test_the_segmentation_owner_is_the_canonical_understanding_layer(self):
        # Tek sahip: gramer brain_understanding'de doğar, entry yalnız bağlı tur için okur.
        from modules import brain_understanding
        self.assertEqual(brain_understanding.sequence_steps("önce sesi kıs sonra parlaklığı 40 yap"),
                         ("sesi kıs", "parlaklığı 40 yap"))
        self.assertEqual(brain_understanding.sequence_steps("sesi kıs"), ())
        self.assertEqual(brain_understanding.sequence_steps("önce sesi kıs"), ())
        self.assertTrue(brain_understanding.is_sequenced("önce sesi kıs"))
        self.assertFalse(brain_understanding.is_sequenced("sesi kıs"))

    def test_the_legacy_raw_splitter_has_no_owner_left(self):
        # Retire = silinir; "legacy" diye bırakılan ikinci bir gramer sahibi kabul edilmez.
        tree = ast.parse((ROOT / "modules" / "engine_sequence.py").read_text(encoding="utf-8"))
        defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        self.assertNotIn("_split_steps", defined)
        self.assertIn("_run_steps", defined)  # typed adım çalıştırma adaptörü meşru sahibinde kalır.
        surface = sorted(str(path.relative_to(ROOT)).replace("\\", "/") for path in (ROOT / "modules").glob("*.py")
                         if "_split_steps" in path.read_text(encoding="utf-8"))
        self.assertEqual(surface, [])

    def test_the_plan_is_bound_to_this_turns_own_sentence(self):
        # Kanonical karar bağlı request'in kendi cümlesine aittir: tur dışı bir metin için
        # (ör. düzeltilmiş ikinci geçiş görüşü) adım planı doğmaz.
        seen = {}

        def probe(command):
            seen["other"] = brain_entry.step_plan("önce maili oku sonra raporu yaz")
            seen["own"] = brain_entry.step_plan(command)
            return "PROBE"

        # "selam" legacy handler'a düşen bir sohbet turudur; plan kendi cümlesinden doğar.
        self.turn("selam", handler=probe)
        self.assertEqual(seen["other"], ())
        self.assertEqual(seen["own"], ())
        self.turn("önce sesi kıs sonra parlaklığı 40 yap", handler=probe)
        self.assertEqual(seen["other"], ())
        self.assertEqual(seen["own"], ("sesi kıs", "parlaklığı 40 yap"))

    def test_two_steps_run_their_own_typed_effect_once_each(self):
        entry, out, _handle, _ = self.turn("önce sesi kıs sonra sonraki müzik")
        self.assertEqual(self.rid, entry.request_id)
        self.ctx._volume_step.assert_called_once_with(-10, "kıstım")
        self.ctx.system_control.media_control.assert_called_once_with("next")
        self.assertIn("1.", out)
        self.assertIn("2.", out)

    def test_an_open_pending_still_blocks_a_new_sequence(self):
        # Bounded state invariant'ı yüzeyde kalır: adım planı açıksa bile kısmi yürütme yok.
        self.ctx._session().pending_confirm = ("silinsin mi?", "not")
        _entry, out, _handle, _ = self.turn("önce sesi kıs sonra sonraki müzik")
        self.assertIn("Açık bir mesaj/onay/düzenleme akışı varken", str(out))
        self.ctx._volume_step.assert_not_called()
        self.ctx.system_control.media_control.assert_not_called()


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


class DispatchArmPrecedenceTests(_RawDoorHarness):
    """Açık admin önek kolları, geniş anahtar taramasından önce sahibine gider (bölüm 3 denetimi).

    Ölçüldü (taban): `dispatch`'in ilk kolu `visual_chat`, görsel türünü cümlenin *içinde* arayan
    sabit-olmayan bir taramadır (`visual_commands.detect_type_by_keyword` → `re.search`). Bu yüzden
    `pc görevi: infografik çiz` masaüstü görevi görsel taslağa, `görev akışı rapor: infografik
    tasarla` görev akışı da aynı şekilde düşüyordu; kullanıcıya "içerik nereden gelsin?" sorusu
    dönüyordu. exact protokol, geniş NL taramasından önce gelir (§29: "Brain daha önce olsun"
    kör kuralı değil, sahiplik sırası). Görsel kolun kendisi kanonical sahibi gelene kadar
    domain-owned kalır (BRAIN-MIG-063 → PR3C envanteri)."""

    def setUp(self):
        super().setUp()
        from modules import desktop_agent, task_agents, visual_chat
        self.seen: list[str] = []

        def desktop(owner, command, *args, **kwargs):
            self.seen.append("desktop")
            return "PC GÖREVİ" if re.match(r"^pc\s+görev", command, re.I) else None

        def flow(owner, command, emit=None, *, summary=False):
            self.seen.append("workflow")
            return "GÖREV AKIŞI" if str(command).lower().startswith("görev akışı") else None

        def visual(context, command, normalized):
            self.seen.append("visual")
            return real_visual(context, command, normalized)

        real_visual = visual_chat.handle
        for module, attr, value in ((desktop_agent, "handle", desktop),
                                    (desktop_agent, "awaiting", lambda owner: False),
                                    (desktop_agent, "spoken", lambda owner: ""),
                                    (task_agents, "handle", flow),
                                    (visual_chat, "handle", visual)):
            starter = patch.object(module, attr, value)
            starter.start()
            self.addCleanup(starter.stop)

    def test_an_explicit_pc_task_is_not_stolen_by_the_broad_keyword_sweep(self):
        _entry, out, _handle, _ = self.turn("pc görevi: infografik çiz")
        self.assertEqual(self.seen, ["desktop"])
        self.assertIsNone(self.ctx._session().pending_visual)
        self.assertIn("PC GÖREVİ", str(out))
        self.assertNotIn("nereden gelsin", str(out))

    def test_an_explicit_workflow_is_not_stolen_by_the_broad_keyword_sweep(self):
        _entry, out, _handle, _ = self.turn("görev akışı rapor: infografik tasarla")
        self.assertEqual(self.seen, ["workflow"])
        self.assertIsNone(self.ctx._session().pending_visual)
        self.assertIn("GÖREV AKIŞI", str(out))

    def test_a_visual_request_without_an_admin_prefix_keeps_its_current_owner(self):
        # Fence kör değil: açık admin öneki olmayan görsel isteği aynı kolunda kalır.
        _entry, out, _handle, _ = self.turn("zihin haritası çıkar")
        self.assertIn("visual", self.seen)
        self.assertIsNotNone(self.ctx._session().pending_visual)
        self.assertIn("nereden gelsin", str(out))


class ExactAdminArmScopeTests(unittest.TestCase):
    """§3 kanıtı: exact admin kolları cümlenin *tamamı* üzerinde karar verir, içinde değil.

    Yalnız negatif biçimler gerçek tanıyıcılara gider (efektsiz küme üyeliği); pozitif biçimler
    kendi owner testlerinde ölçülmüştür ve burada kota/dosya/worker efekti başlatmaz."""

    def test_the_quota_arm_rejects_a_longer_sentence(self):
        from modules import usage_meter
        for text in ("kota durumu değil", "pc kota durumu nedir", "kullanım"):
            self.assertIsNone(usage_meter.handle("alice", text), text)

    def test_router_and_doctor_arms_are_membership_lists(self):
        from modules import smart_router, system_doctor
        for text in ("smart router açılır mı", "akıllı router nasıl çalışır", "model yetenekleri listesi"):
            self.assertIsNone(smart_router.handle("alice", text), text)
        for text in ("pc ses kontrolü değil", "sistem tanılama nedir", "arka planda sistem kontrolü yap"):
            self.assertIsNone(system_doctor.handle("alice", text), text)

    def test_the_desktop_owner_gate_is_the_same_admin_family_as_the_early_arm(self):
        # Erken kolun öneki ile owner'ın kendi kapısı aynı aileyi tanımalı; aksi hâlde yüzey,
        # owner'ın sahiplenmediği bir cümleyi masaüstüne itiyor olur (ölçülen sapma riski).
        import re as _re
        from modules import desktop_agent
        surface = _re.compile(r"^pc\s+(?:görev(?:i)?(?=[:\s])|onayla\s|iz(?:in|ni|inleri|inler)\b)", _re.I)
        for text in ("pc görevi: hesap makinesi 12 ile 7 topla", "pc görevi durum", "pc onayla evet",
                     "pc izinleri", "PC İZİN VER"):
            self.assertTrue(surface.match(text), text)
        for text in ("hesap makinesini aç", "pc rehberliği: wifi", "izin ver"):
            self.assertFalse(surface.match(text), text)
        self.assertTrue(callable(desktop_agent.handle))


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


def _source_calls(marker: str) -> list[str]:
    """Bu adı *çağıran* üretim modülleri (ast.Attribute veya ast.Name çağrısı); tanımlar hariç.

    Noktalı işaretçi ("typo.fix") zincirin son iki halkasıyla karşılaştırılır, çıplak ad tek
    halkayla."""
    found = []
    files = sorted(list(ROOT.glob("*.py")) + list((ROOT / "modules").rglob("*.py"))
                   + list((ROOT / "scripts").glob("*.py")))
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else (func.id if isinstance(func, ast.Name) else None)
            dotted = ast.unparse(func) if "." in marker else None
            if name == marker or (dotted and dotted.split(".")[-2:] == marker.split(".")):
                found.append(path.relative_to(ROOT).as_posix())
                break
    return found


class CascadeOrderContractTests(unittest.TestCase):
    """§11/§25 B: cascade'in kökü tek sıra sözleşmesidir; yüzey kendi mini-router'ını taşımaz.

    Ölçülen taban (base `ea2f0b3` üzerinden bu committen önce): `engine_commands.handle` dört
    ham handler'ı (`_macro_teach/_macro_manage/_macro_run/_extra_commands`) bir tuple döngüsünde
    sırayla yokluyordu. Aynı sıra `brain_precedence.FRONT_GATES`'te ikinci kez tanımlıydı, yani
    sıranın iki sahibi vardı ve yüzeyde plan-fencesi yoktu. Kök çözüm: kuyruk aralığı tek
    sahibinden çağrılır; yüzey gate adlarını hiç anmaz. (Sahiplik envanteri BRAIN-MIG-052 → PR3C;
    buradaki kilitten sonra bile cascade'in üretim çağıranı yalnız sıralık sözleşmedir.)"""

    def test_the_tail_is_the_end_of_the_single_order_contract(self):
        from modules import brain_precedence
        self.assertEqual(brain_precedence.TAIL_GATES,
                         brain_precedence.FRONT_GATES[-len(brain_precedence.TAIL_GATES):])
        self.assertEqual(brain_precedence.TAIL_GATES,
                         ("macro_teach", "macro_manage", "macro_run", "extra_commands"))

    def _runtime(self, answers=None):
        from types import SimpleNamespace
        answers = answers or {}
        calls: list[tuple[str, tuple]] = []

        def gate(name):
            def run(*args):
                calls.append((name, args))
                return answers.get(name)
            return run

        return SimpleNamespace(
            calls=calls, _tr_lower=lambda text: text.casefold(),
            _macro_teach=gate("macro_teach"), _macro_manage=gate("macro_manage"),
            _macro_run=gate("macro_run"), _extra_commands=gate("extra_commands"),
            _file_command=gate("file_command"), _user_command=gate("user_command"),
            _planner_command=gate("planner_command"),
            system_control=SimpleNamespace(windows_settings=gate("windows_settings")),
            emit=gate("emit"))

    def test_each_tail_gate_is_consulted_once_in_contract_order(self):
        from modules import brain_precedence
        runtime = self._runtime()
        self.assertIsNone(brain_precedence.claim_tail(runtime, "Raporumu telefona gönder"))
        self.assertEqual([name for name, _ in runtime.calls],
                         ["macro_teach", "macro_manage", "macro_run", "extra_commands"])
        self.assertEqual([args for _, args in runtime.calls],
                         [("Raporumu telefona gönder", "raporumu telefona gönder"),
                          ("raporumu telefona gönder",), ("raporumu telefona gönder",),
                          ("Raporumu telefona gönder", "raporumu telefona gönder")])

    def test_the_first_answering_gate_stops_the_tail(self):
        from modules import brain_precedence
        runtime = self._runtime({"macro_run": "KISAYOL"})
        self.assertEqual(brain_precedence.claim_tail(runtime, "deneme komutu"), ("macro_run", "KISAYOL"))
        self.assertEqual([name for name, _ in runtime.calls], ["macro_teach", "macro_manage", "macro_run"])

    def test_the_tail_never_replays_an_earlier_effect_gate(self):
        # Devir çift sahiplik değildir: kuyruk aralığı, yüzeyin daha önce yürüttüğü efekt gate'lerini
        # ikinci kez çalıştıramaz (ikinci taşıma/silme/yayın riski).
        from modules import brain_precedence
        runtime = self._runtime()
        brain_precedence.claim_tail(runtime, "bugün neler var")
        replayed = {name for name, _ in runtime.calls}
        self.assertTrue(replayed.isdisjoint({"file_command", "windows_settings", "user_command",
                                             "planner_command", "emit"}))

    def test_the_full_contract_still_runs_every_gate_from_the_front(self):
        from modules import brain_precedence, selfctl
        runtime = self._runtime()
        # selfctl bir modül sınırıdır (runtime._x değil), bu yüzden çağrı defterinde adı geçmez;
        # efektsiz olması için burada patch'lenir.
        with patch.object(selfctl, "handle", lambda lowered, emit: None):
            self.assertIsNone(brain_precedence.claim(runtime, "hava nasıl"))
        self.assertEqual([name for name, _ in runtime.calls],
                         [name for name in brain_precedence.FRONT_GATES if name != "selfctl"])


class CascadeRootTests(_RawDoorHarness):
    """§25 B ve D: ham anlamsal aday döngüsü yüzeyden kalkar, cascade'in tek üretim çağıranı kalır."""

    def _handle_body(self):
        tree = ast.parse(ENGINE_COMMANDS_SOURCE)
        return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "handle")

    def test_the_surface_carries_no_raw_semantic_candidate_loop(self):
        handle = self._handle_body()
        loops = [node for node in ast.walk(handle)
                 if isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(node.iter, (ast.Tuple, ast.List))]
        self.assertEqual(loops, [], "engine_commands.handle çoklu ham anlamsal aday döngüsü taşıyamaz (§25 B)")

    def test_the_surface_names_no_cascade_gate(self):
        handle = self._handle_body()
        attrs = {node.attr for node in ast.walk(handle) if isinstance(node, ast.Attribute)}
        self.assertTrue(attrs.isdisjoint({"_macro_teach", "_macro_manage", "_macro_run", "_extra_commands"}),
                        "sıranın tek sahibi brain_precedence; yüzey gate adlarını tekrar listeleyemez")
        self.assertIn("claim_tail", attrs)

    def test_the_cascade_has_one_production_call_owner(self):
        # §25 D'nin PR3B'de ölçülebilir hâli: normal kullanıcı üretim yolunda cascade'i çağıran
        # tek yer sıra sözleşmesidir. BRAIN-MIG-052'de kollar kanonical parity kazanınca bu son
        # çağıran da silinir; o gün bu satır [] bekler — başka modüle izin yoktur.
        self.assertEqual(_source_calls("_extra_commands"), ["modules/brain_precedence.py"])

    def test_the_mail_owner_is_reached_only_from_the_cascade(self):
        # BRAIN-MIG-051: "bu cümle mail mi?" hükmü yalnız tek cascade kolundadır, yüzeylerde değil.
        self.assertEqual(_source_calls("_mail_handle"), ["modules/engine_tools.py"])


class CascadeReachabilityTests(_RawDoorHarness):
    """Fence kör değildir: kuyruk devri sonrası eşleşmemiş kometler aynı sahibine ulaşıyor."""

    def setUp(self):
        super().setUp()
        from functools import partial

        from modules import engine_tools
        self.ctx._extra_commands = partial(engine_tools._extra_commands, self.ctx)

    def test_an_unmapped_folder_request_still_reaches_its_cascade_owner(self):
        self.seams["modules.folder_analysis.handle"].return_value = "ANALİZ"
        _entry, out, _handle, _ = self.turn("İndirilenler klasörünü incele")
        self.assertIn("ANALİZ", str(out))
        self.seams["modules.folder_analysis.handle"].assert_called_once()

    def test_a_shortcut_answer_stops_the_cascade_behind_it(self):
        self.ctx._macro_run = Mock(return_value="KISAYOL ÇALIŞTI")
        self.seams["modules.folder_analysis.handle"].return_value = "ANALİZ"
        _entry, out, _handle, _ = self.turn("deneme kısayolunu çalıştır")
        self.assertIn("KISAYOL ÇALIŞTI", str(out))
        self.seams["modules.folder_analysis.handle"].assert_not_called()

    def test_an_explicit_mail_request_still_reaches_the_mail_owner(self):
        # Provider/account kararları domain'de kalır (§12): kanonical mail capability yokken
        # cümle aynı sahibine gider; PR3B bunu sökmez, yalnız tek kapıya indirir.
        self.ctx._mail_handle = Mock(return_value="MAİL")
        _entry, out, _handle, _ = self.turn("maillerimi kontrol et")
        self.assertIn("MAİL", str(out))


class FinanceAlertEntryScopeTests(unittest.TestCase):
    """§13 ölçümü (taban): giriş küresel anlamsal seçim değil, sabit tam kalıptır.

    Spec `if finance_alert_commands.matches(command)` satırını "bu global semantic selection"
    olarak sınıflıyordu. Kod gerçeği ölçüldü: tanıyıcı `fullmatch`/tam küme üyeliğidir, yani
    cümlenin *içinde* alan aramaz; exact admin/FAST ailesindendir (B). Kalan iş, alarmın
    kanonical öneri/Core eşlemesi (BRAIN-MIG-053 → PR3C), bu kalıbın genişletilmesi değil."""

    POSITIVE = ("dolar 45 tl üstüne çıkarsa haber ver", "altın 2500 tl'nin altına inerse haber ver",
                "alarmi sil 3", "alarmlarim")
    NEGATIVE = ("döviz kuru nedir?", "alarm kurmak nasıl çalışır", "bugün hava nasıl, alarmlar da var mı",
                "iş mailimi kontrol et", "gram altın kaç tl", "")

    def test_the_exact_alarm_grammar_is_recognised(self):
        from modules import finance_alert_commands
        for text in self.POSITIVE:
            with self.subTest(text=text):
                self.assertTrue(finance_alert_commands.matches(text), text)

    def test_a_sentence_that_only_mentions_the_words_does_not_match(self):
        from modules import finance_alert_commands
        for text in self.NEGATIVE:
            with self.subTest(text=text):
                self.assertFalse(finance_alert_commands.matches(text), text)


class RepoWideAuthorityGuardTests(unittest.TestCase):
    """§25 C/D yapısal guard'ları repo geneli: ham anlamsal cephe adı yeni sahibi olamaz.

    Bu sınıftaki her küme kodundan ölçüldü (`_source_calls` AST taraması; tanımlar değil
    *çağıranlar* sayılır). Kilitlerin amacı PR3B'de söküm değildir — kalan kapıların sahipliği
    BRAIN-MIG-051/052/053/054 envanterindedir (PR3C) — fakat sıralık yüzeye yarın bir modülden
    ikinci `watcher.handle(command)` çağrısı gelirse bu testler onu RED yapar. Guard brittle
    tam-dosya snapshot değildir: yalnız ad + çağıran dosya kümesi."""

    # Ölçülen üretim çağıranları (base `ea2f0b3` → PR3B head): ham cümleyi alan anlamsal yoklamalar.
    RAW_PROBE_OWNERS = {
        "watcher.handle": {"modules/engine_commands.py"},
        "learning.handle": {"modules/engine_commands.py"},
        "finance.answer": {"modules/engine_commands.py", "scripts/finans_kaynak_testi.py"},
        "is_whatsapp_message": {"modules/engine_commands.py"},
        "_contact_command": {"modules/engine_commands.py"},
        "quick_parse": {"modules/engine_commands.py"},
        "selfctl.handle": {"modules/engine_commands.py"},
        "_file_command": {"modules/brain_precedence.py", "modules/engine_commands.py",
                          "modules/engine_tools.py", "modules/main_documents.py"},
        "windows_settings": {"modules/brain_precedence.py", "modules/engine_commands.py"},
    }

    def test_a_raw_semantic_probe_has_only_its_pinned_production_owner(self):
        for marker, owners in self.RAW_PROBE_OWNERS.items():
            with self.subTest(marker=marker):
                self.assertEqual(set(_source_calls(marker)), owners)

    def test_the_cascade_helper_is_called_only_from_the_order_contract(self):
        # §25 D: `_extra_commands` bir compat yardımcısı olarak yüzeye geri bağlanamaz; tek
        # çağıran `brain_precedence` sırası sözleşmesidir. Söküm BRAIN-MIG-052 (PR3C) satırıdır.
        self.assertEqual(_source_calls("_extra_commands"), ["modules/brain_precedence.py"])

    def test_the_typo_rewriter_is_consulted_from_exactly_one_production_site(self):
        # §25 A'nın repo geneli yarısı: düzeltilmiş görünümü başka bir modül de okuyamaz.
        self.assertEqual(_source_calls("typo.fix"), ["modules/engine_commands.py"])

    def test_every_capability_hint_understanding_can_emit_is_core_mapped(self):
        """Yeni hint yalnız Core eşlemesiyle doğar: §24 fence'inin ön koşulu burada kilitlidir."""
        import re as _re

        from modules import brain_core_map
        source = (ROOT / "modules" / "brain_understanding.py").read_text(encoding="utf-8")
        constants = dict(_re.findall(r'^([A-Z_]+(?:_CAPABILITY|_HINT))\s*=\s*"([^"]+)"', source, _re.M))
        emitted = set(constants.values()) | set(_re.findall(r'(?:return|:)\s*"([a-z_]+\.[a-z_.]+)"', source))
        self.assertTrue(emitted)
        self.assertEqual(sorted(emitted - set(brain_core_map.CORE_INTENTS)), [])


class CoreRejectionFallthroughInventoryTests(_RawDoorHarness):
    """§24 kapanışı: Core'un reddettiği TAM tipli öneri ham cepheden ikinci kez yürütülemez.

    PR3B ölçümü: `core_plan` None olduğunda `handoff` kontrolü `handler(command)`'a düşüyor,
    bir kapı cevaplanırsa efekt kanonical reddi eziyordu (ölçülen satır: `text.translate`).
    PR3C-2 bu aileyi kapattı: mapped hint + `original_text` dışında tipli payload taşıyan öneri
    Core'da doğrulanmadıysa `handoff` fail-closed reddeder (`CORE_PROPOSAL_REJECTED`). Eksik
    öneri (yalnız cümle metni) ret sayılmaz; meşru eski sahibinde kalır (`beni uyar`,
    `dosyayı aç`, `raporda ara`) — bu ayrım `test_brain_pr3c2_core_rejection_and_explanation.py`
    içinde kilitlidir."""

    def test_a_rejected_typed_proposal_never_reaches_the_raw_surface(self):
        """PR3C-2 kapanışı: eski `assertIn("HAM KAPI CEVABI")` sözleşmesi tersine döndü."""
        self.ctx._extra_commands = Mock(return_value="HAM KAPI CEVABI")
        with patch.object(brain_entry, "core_plan", lambda entry: None):
            entry, out, _handle, feedback = self.turn("şu notu ingilizceye çevir")
        self.assertIs(entry.understanding.request_kind, RequestKind.CAPABILITY)
        self.assertNotIn("HAM KAPI CEVABI", str(out))
        self.assertEqual(feedback.result_status, "failed")
        self.assertEqual(feedback.reason_code, "CORE_PROPOSAL_REJECTED")
        self.ctx._extra_commands.assert_not_called()

    def test_the_parity_families_that_already_close_a_rejected_proposal_are_named(self):
        # Red durumunda ham yüzeyi tamamen kapatan aileler: photo (handoff'ta plan'sız ret),
        # files (`_file_access_refusal`) ve PR3C-2'nin tipli-payload çiti. Üçü de kendi
        # test sınıflarında kilitlidir (test_brain_photo_core_cutover, CoreRejectionFenceTests,
        # test_brain_pr3c2_core_rejection_and_explanation); burada envanter sahibi olarak adlandırılır.
        from modules import brain_entry as entry_module
        source = inspect.getsource(entry_module.handoff)
        self.assertIn("capability_hint == PHOTO_CAPABILITY", source)
        self.assertIn("refusal = _file_access_refusal(entry)", source)
        self.assertIn("_core_rejected_proposal(entry)", source)


class MetaLanguageRawDoorSilenceTests(_RawDoorHarness):
    """§28: kanonical olarak tanınmış bir soru hiçbir ham domain kapısına gitmez.

    Taban `ea2f0b3` ölçümü (aynı yalıtılmış zincir, kapılar Mock): bu dört cümlenin HERİ
    `_file_command`, `_planner_command`, `_user_command`, `_contact_command`,
    `_extra_commands` ve `selfctl/pc_guide/developer/task_agents/watcher/learning/finance`
    sınırlarının tamamına soruluyordu. Bu head'te hiçbirine sorulmuyor: `explanation_turn`
    yüzeyi kapalı exact-admin setine yönlendiriyor. Efekt sıfır, sorgu sıfır."""

    def _doors_silent(self):
        for name in RAW_DOORS:
            getattr(self.ctx, name).assert_not_called()

    def test_a_rate_question_consults_no_raw_domain_door(self):
        entry, out, _handle, _ = self.turn("döviz kuru nedir?")
        self.assertIs(entry.understanding.request_kind, RequestKind.CHAT)
        self._doors_silent()
        self.assertEqual(self.silent("modules.watcher", "modules.learning", "modules.finance",
                                     "modules.selfctl"), [])
        self.assertEqual(out, "CHAT")

    def test_a_file_operation_question_touches_no_file_door(self):
        entry, _out, _handle, _ = self.turn("rapor dosyasını belgelerime taşımak ne demek?")
        self._doors_silent()
        self.assertEqual(self.silent("modules.file_ops", "modules.watcher", "modules.learning"), [])
        self.ctx._file_command.assert_not_called()

    def test_a_screen_text_question_reads_no_screen_and_asks_no_door(self):
        entry, _out, _handle, _ = self.turn("ekrandaki metni okumak nasıl yapılır?")
        self._doors_silent()
        self.ctx._screen_ocr.assert_not_called()
        self.ctx._copy_text.assert_not_called()

    def test_a_clipboard_question_copies_nothing(self):
        entry, _out, _handle, _ = self.turn("panoya kopyalamak nedir?")
        self._doors_silent()
        self.ctx._copy_text.assert_not_called()
        self.assertEqual(self.silent("modules.selfctl", "modules.notify"), [])


class EpistemicQuestionInventoryTests(_RawDoorHarness):
    """§28 kapanışı: güvenlik/risk ve tanım soruları kanonical olarak açıklama hükmüdür.

    Taban `ea2f0b3` ölçümü: "dosya taşımak güvenli mi?" ve "mail göndermenin riskleri neler?"
    hiçbir `_STATIC_MARKERS` işaretçisi taşımadığı için EXPLANATION_REQUEST üretmiyor, tur ham
    cephenin tamamını dolaşıyordu. PR3C-2 işaretçileri genişletti: ikisi de EXPLANATION + CHAT
    olur, ham kapıya sorulmaz. Tanım sorusu bir anahtar sözcük yüzünden yetenek önerisi de
    taşıyamaz (`dolar kaç tl ne demek?` → research ipucu düşer); açık tazelik isteği
    (`güncel dolar kuru nedir?`) kendi planında kalır."""

    def test_a_safety_or_risk_question_walks_no_raw_door(self):
        for text in ("dosya taşımak güvenli mi?", "mail göndermenin riskleri neler?"):
            with self.subTest(text=text):
                self.door.reset_mock()
                for door in RAW_DOORS:
                    getattr(self.ctx, door).reset_mock()
                entry, _out, _handle, _ = self.turn(text)
                self.assertIn("EXPLANATION_REQUEST", tuple(entry.understanding.reason_codes))
                self.assertIs(entry.understanding.request_kind, RequestKind.CHAT)
                self.assertIsNone(entry.understanding.capability_hint)
                self.assertEqual(self.door.call_count, 1)   # tek canonical geçiş
                for name in RAW_DOORS:
                    getattr(self.ctx, name).assert_not_called()

    def test_a_marker_question_with_a_market_phrase_starts_no_research(self):
        # "ne demek?" tanım sorusudur; cümledeki "kaç tl" bir arama isteği doğurmaz.
        entry, _out, _handle, _ = self.turn("dolar kaç tl ne demek?")
        self.assertIsNone(entry.understanding.capability_hint)
        self.assertEqual(set(entry.understanding.arguments), {"original_text"})
        self.assertIn("EXPLANATION_REQUEST", tuple(entry.understanding.reason_codes))
        self.assertEqual(self.door.call_count, 1)
        for name in RAW_DOORS:
            getattr(self.ctx, name).assert_not_called()


class DiagnoseTypoViewTests(_RawDoorHarness):
    """Regresyon 1 (`sistemi kotrol et`): teşhis yüzeyi düzeltilmiş görünümde de sahibine yürür.

    Ölçülen taban (`ea2f0b3` probe koşusu, satır p486): base ikinci bir `handle()` geçişinde ham
    regex arıza kapısını düzeltilmiş cümleyle çalıştırdı — owner `none`, `passes=2`, `effect_total=34`
    (`diagnose.run` gerçekten koştu; mock olduğu için outcome kaydı boş). Head: owner `chat`,
    `passes=1`, `effect_total=16`, outcome `CHAT`. Kayıp, kullanıcının gördüğü teşhis çıktısıdır.
    Düzeltme ikinci geçiş veya ham regex yetkisi değildir: düzeltilmiş görünümün kapalı tam-cümle
    admin setine, sahibi `modules.diagnose` olan bir tanıyıcı daha girer (§25 A).
    """

    def test_correctly_spelled_diagnosis_runs_the_diagnose_owner(self):
        self.door.reset_mock()
        _entry, out, _handle, _ = self.turn("sistemi kontrol et")
        self.assertEqual(out, "ARIZA")
        self.seams["modules.diagnose.run"].assert_called_once()
        self.assertEqual(self.turn_texts, ["sistemi kontrol et"])
        self.run_goal.assert_not_called()

    def test_misspelled_diagnosis_reaches_the_same_owner_exactly_once(self):
        self.door.reset_mock()
        _entry, out, _handle, _ = self.turn("sistemi kotrol et")
        self.assertEqual(out, "ARIZA")
        self.seams["modules.diagnose.run"].assert_called_once()
        self.seams["modules.diagnose.summary"].assert_called_once()
        self.assertEqual(self.turn_texts, ["sistemi kotrol et"],
                         "düzeltilmiş metin legacy kapıya ikinci kez giremez")

    def test_misspelled_diagnosis_never_becomes_a_goal_run(self):
        self.turn("sistemi kotrol et")
        self.run_goal.assert_not_called()

    def test_the_closed_recognizer_owns_the_whole_sentence_only(self):
        # Tanıyıcı tam-cümledir: cümlenin bir kesitinde geçen teşhis sözcüğü etki yetkisi almaz.
        from modules import diagnose
        for text in ("sistem taraması nedir", "arıza tespiti nasıl çalışır",
                     "sistem çökmeleri neden olur", "bunu kontrol et", "sistem durumu",
                     "sistem tanılama", "pc ses kontrolü"):
            with self.subTest(text=text):
                self.assertFalse(diagnose.requested(text), text)
        for text in ("sistemi kontrol et", "sistem kontrol", "bağlantıyı kontrol et",
                     "kendini test et", "her şey yolunda mı", "sorun var mı", "neden çalışmıyor",
                     "ne bozuk", "sistem taraması", "arıza tespiti yap", "jarvis sistemi kontrol et"):
            with self.subTest(text=text):
                self.assertTrue(diagnose.requested(text), text)

    def test_an_explanation_question_about_diagnosis_produces_no_effect(self):
        for text in ("sistem taraması nedir", "arıza tespiti nasıl çalışır"):
            with self.subTest(text=text):
                self.seams["modules.diagnose.run"].reset_mock()
                self.turn(text)
                self.seams["modules.diagnose.run"].assert_not_called()

    def test_a_misspelled_domain_sentence_still_does_not_diagnose(self):
        # Yeni tanıyıcı hiçbir domain akışının yerine geçmez: düzeltilmiş görünümde de yalnız
        # tam-cümle teşhis kalıbı etki alır.
        for text in ("klasörleri duzenle", "masaüstünü duzenle", "takvimimi kotrol et"):
            with self.subTest(text=text):
                self.seams["modules.diagnose.run"].reset_mock()
                self.turn(text)
                self.seams["modules.diagnose.run"].assert_not_called()


class MisspelledExecutionFailsClosedTests(_RawDoorHarness):
    """Regresyon 2 (`masaüstünü duzenle`): yazım-düzeltilmiş ve yeteneği doğrulanmamış cümle hedef yürütmesi açamaz.

    Ölçülen taban (satır p486/phase2): base'de bu cümle ikinci geçişde `_extra_commands` düzenleme
    kapısına ulaşıp 30 dosyalık plan *önizlemesi* + tek onay üretiyordu; head tek geçişde hiçbir
    yetenekte karşılık bulamayınca PR10c catch-all'u `task` seçti ve `goal_executor.run` çağrıldı.
    Üretimde o yol kullanıcı onayı olmadan yeni GoalState kaydı yazar
    (`goal_executor._run` → `_save(job)`) ve planlayıcı modeli başlatır; mock testin
    `mutating_effects={}` kaydı bu yürütmeyi hiç kapsamıyordu. Kilit: yalnız Türkçe karakteri
    geri getirilen — kelimenin katlanmış kimliği değişmemiş — bir görünüm doğrulanmış bir yetenek
    bulamadığında Goal/Task yetkisi doğmaz. Düzeltici doğru yazılmış kelimeyi de bozabildiği için
    ("hazırla" -> "hatırla") kapı bilinçli olarak bu dar sınıfla sınırlandı: doğru yazılmış icra
    cümlelerinin catch-all sözleşmesi (PR10c) değişmez.
    """

    def goals_root(self) -> Path:
        from modules import goal_executor
        return Path(goal_executor.STORE)

    def test_the_gate_is_limited_to_identity_preserving_corrections(self):
        # Ölçülen sınır: düzeltici "hazırla"yı "hatırla"ya bozuyor — kimlik değiştiyse kapı çalışmaz.
        for text in ("masaüstünü duzenle", "konusmayi ozetle", "gorevlerimi listelee"):
            with self.subTest(text=text):
                self.assertTrue(typo.diacritic_correction(text), text)
        for text in ("araştırıp rapor hazırla", "masaüstünü düzenle", "yarış merhaba", "selam"):
            with self.subTest(text=text):
                self.assertFalse(typo.diacritic_correction(text), text)

    def test_a_correctly_spelled_sentence_the_corrector_mangles_keeps_the_catch_all(self):
        # Doğru yazılmış cümle, düzeltici onu bozsa da yetkisini kaybetmez (PR10c kilidi).
        _entry, out, _handle, _ = self.turn("Araştırıp rapor hazırla")
        self.assertEqual(out, "GOAL_RUN")
        self.run_goal.assert_called_once()

    def test_misspelled_organize_request_opens_no_goal_and_writes_no_record(self):
        _entry, out, _handle, _ = self.turn("masaüstünü duzenle")
        self.run_goal.assert_not_called()
        self.assertIn("işlem başlatılmadı", out)
        self.ctx.files.apply_organize.assert_not_called()
        self.assertEqual(list(self.goals_root().rglob("*.json")), [],
                         "onaysız yeni GoalState kaydı yazıldı")

    def test_misspelled_organize_request_never_hands_the_corrected_text_to_a_domain_door(self):
        # Eski ikinci typo geçişi geri gelmez: kapılar yalnız kullanıcının yazdığı cümleyi görür.
        self.turn("masaüstünü duzenle")
        self.assertEqual(self.turn_texts, ["masaüstünü duzenle"])
        seen = [call.args[0] for call in self.ctx._extra_commands.call_args_list if call.args]
        self.assertEqual(seen, ["masaüstünü duzenle"],
                         f"düzeltilmiş görünüm ham-komut kapısına ulaştı: {seen}")

    def test_correctly_spelled_organize_keeps_its_domain_owner(self):
        # Domain sahibi cümleyi aldığında catch-all hiç devreye girmez (base ile head aynı).
        self.ctx._extra_commands = Mock(
            return_value="Masaüstü klasöründeki 30 dosyayı klasörlere taşıyayım mı? (evet/hayır)")
        _entry, out, _handle, _ = self.turn("masaüstünü düzenle")
        self.assertIn("taşıyayım mı", out)
        self.run_goal.assert_not_called()
        self.ctx._extra_commands.assert_called_once()

    def test_a_correctly_spelled_unmapped_execution_request_keeps_the_pinned_catch_all(self):
        # PR10c kilidi: doğru yazılmış, yeteneksiz icra cümlesi yine hedef yürütücüsüne devredilir.
        _entry, out, _handle, _ = self.turn("maillerimi kontrol et")
        self.assertEqual(out, "GOAL_RUN")
        self.run_goal.assert_called_once()

    def test_the_fail_closed_turn_starts_no_file_or_domain_effect(self):
        # Erken dispatch kolları (task_agents/pc_guide/developer/selfctl) her cümleyi *görüşür* ve
        # None döner; burada kilitlenen şey effekte dokuyan sınırların hiç çağrılmamasıdır.
        self.turn("desktoptaki gereksizleri duzenle")
        self.assertEqual(self.silent("modules.file_ops", "modules.folder_analysis", "modules.filesend",
                                     "modules.notify", "modules.diagnose"), [])
        self.ctx.files.plan_organize.assert_not_called()
        self.ctx.files.apply_organize.assert_not_called()
        self.ctx._mail_handle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
