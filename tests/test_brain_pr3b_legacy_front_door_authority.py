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
import re
import unittest
import uuid
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
