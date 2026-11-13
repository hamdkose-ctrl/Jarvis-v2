"""PR3C-4: klasör analizi (`folder_analysis`) kanonical hatta — parite kilitleri.

Tabanda (ed636bd) ölçülen: dokuz analiz/icra cümlesinin altısı kanonical kararsız (`capability_hint`
yok) legacy `_extra_commands` kapısından geçiyordu; kapı ham cümleyi kendi grameriyle yorumluyor,
gerçek dosya okuyor, bilgi tabanına yazıyor ve tek model çağrısı yapıyordu. Bu dosya aynı etkinliği
kanonical zincire kilitler:

    Understanding (tek anlamsal karar) → Core (kapalı anahtar + gerçek klasör kimliği)
    → mevcut folder_analysis.analyze yürütücüsü → rapor

Yürütücü değişmedi: izinli kökler, iki alt klasör derinliği, dosya/boyut/süre sınırları, gizli
dosyaların hiç açılmaması, OneDrive yalnız-çevrimiçi belgenin indirilmemesi, modelsiz rapor
yedeği ve bilgi tabanına kayıt aynen burada sınanır. Hiçbir test kullanıcının gerçek
Masaüstü/İndirilenler/Belgeler klasörünü veya `~/.jarvis` kaydını okumaz; her şey geçici köktedir
ve model/ağ çağrısı mock'tur.
"""
from __future__ import annotations

import ast
import importlib
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import test_brain_pr3b_legacy_front_door_authority as pr3b
from modules import brain_precedence, engine_intents, engine_tools, folder_analysis, kb, nxapi
from modules.brain_contracts import RequestKind
from modules.brain_understanding import FOLDER_ANALYSIS_CAPABILITY, FOLDER_ANALYSIS_OPERATION

ROOT = Path(__file__).resolve().parents[1]
ENGINE_TOOLS_SOURCE = (ROOT / "modules" / "engine_tools.py").read_text(encoding="utf-8")
MODEL_REPLY = "Klasör kira ve maliyet dosyalarıyla ilgili bir çalışma alanı."


def _folder_analysis_touches(source: str) -> list[str]:
    """Kaynak kodun AST'sında `folder_analysis`'a temas eden halkalar (import, ad, nitelik).

    Docstring düzyazısı düğüm değildir; ham metin taraması yerine bu kullanılır."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(a.name == "folder_analysis" or a.name.endswith(".folder_analysis") for a in node.names):
                found.append(ast.unparse(node))
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[-1] == "folder_analysis":
                found.append(ast.unparse(node))
        elif isinstance(node, ast.Name) and node.id == "folder_analysis":
            found.append("folder_analysis")
    return found


class _FolderHarness(pr3b._RawDoorHarness):
    """Kanonical zincir + GERÇEK `folder_analysis` yürütücüsü, hepsi geçici kökte."""

    def setUp(self):
        super().setUp()
        # pr3b'nin kapı listesi domain yürütmesini Mock'lar; burada klasör analizi GERÇEK çalışmalıdır.
        # Reload yalnız bu modülün adlarını tazeler (HOME/FILES_DIR/kb yamaları başka modüllerde),
        # pr3b temizliği ise yamalandığı gerçek fonksiyonu geri yazıyor.
        importlib.reload(folder_analysis)
        home = Path(self.temp.name) / "home"
        self.downloads = home / "Downloads"
        self.desktop = home / "Desktop"
        self.documents = home / "Documents"
        self.pictures = home / "Pictures"
        self.jarvis = self.documents / "Jarvis Dosyaları"
        for folder in (self.downloads, self.desktop, self.documents, self.pictures, self.jarvis):
            folder.mkdir(parents=True)
        self.sub = self.downloads / "Proje"
        self.sub.mkdir()
        for target, attr, value in (
            (nxapi, "HOME", home),
            (nxapi, "FILES_DIR", self.jarvis),
            (nxapi, "known_folder", lambda name: None),
            (kb, "ROOT", Path(self.temp.name) / "kb"),
        ):
            starter = patch.object(target, attr, value)
            starter.start()
            self.addCleanup(starter.stop)

        # Yürütücü gerçek, ama çağrısı/etkisi sayılıyor: okunan dosya, indeks, model.
        self.analyzed: list[Path] = []
        self.reads: list[str] = []
        self.indexed: list[str] = []
        self.model: list[str] = []
        real_analyze = folder_analysis.analyze
        real_read = folder_analysis.docs.read_document
        real_add = kb.add

        def analyze(profile, folder, use_model=True):
            self.analyzed.append(Path(folder))
            return real_analyze(profile, folder, use_model=use_model)

        def read(path, **kwargs):
            self.reads.append(Path(path).name)
            return real_read(path, **kwargs)

        def add(profile, path):
            self.indexed.append(Path(path).name)
            return real_add(profile, path)

        def ask(prompt, **kwargs):
            self.model.append(prompt)
            return MODEL_REPLY

        for target, attr, value in ((folder_analysis, "analyze", analyze),
                                    (folder_analysis.docs, "read_document", read),
                                    (kb, "add", add)):
            starter = patch.object(target, attr, value)
            starter.start()
            self.addCleanup(starter.stop)
        # `folder_analysis._model_summary` çağrı anında `modules.llm.ask`'i alır: tek seam'den mock.
        starter = patch("modules.llm.ask", ask)
        starter.start()
        self.addCleanup(starter.stop)
        # The removed raw cascade is not reinstated in this harness.
        # Canonical folder analysis executes directly through its Core worker.
        self.assertFalse(hasattr(engine_tools, "_extra_commands"))
        self.ctx._session().pending_organize = None

    def seed(self, folder, *names):
        for name in names:
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{name} kira bedeli kira artışı maliyet tutarı\n" * 3, encoding="utf-8")
        return folder

    def decide(self, text):
        entry, out, _handle, _feedback = self.turn(text)
        return entry, out

    def hint_of(self, text):
        entry, _out = self.decide(text)
        return entry.understanding.capability_hint, dict(entry.understanding.arguments or {})


class CanonicalFolderAnalysisDecisionTests(_FolderHarness):
    def test_an_explicit_folder_request_is_a_canonical_capability(self):
        self.seed(self.downloads, "kira.txt", "maliyet.txt")
        entry, out = self.decide("indirilenler klasörünü incele")
        self.assertIs(entry.understanding.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(entry.understanding.capability_hint, FOLDER_ANALYSIS_CAPABILITY)
        self.assertEqual(entry.understanding.arguments.get("folder"), "downloads")
        self.assertEqual(self.analyzed, [self.downloads])
        self.assertIn("İndirilenler", out)
        self.assertIn("2 dosya var", out)

    def test_the_ascii_twin_is_the_same_decision_and_the_same_report(self):
        self.seed(self.downloads, "kira.txt", "maliyet.txt")
        typo_hint, typo_args = self.hint_of("indirilenler klasorunu incele")
        typo_analysis = list(self.analyzed)
        typo_indexed = list(self.indexed)
        self.assertEqual(typo_hint, FOLDER_ANALYSIS_CAPABILITY)
        correct_hint, correct_args = self.hint_of("indirilenler klasörünü incele")
        self.assertEqual(correct_hint, typo_hint)
        # Karar alanları birebir aynı; `original_text` kullanıcının kendi yazımıdır (Türkçe hali korunur).
        decision = {k: v for k, v in correct_args.items() if k != "original_text"}
        self.assertEqual(decision, {k: v for k, v in typo_args.items() if k != "original_text"})
        self.assertEqual(self.analyzed, typo_analysis * 2)
        self.assertEqual(self.indexed, typo_indexed * 2)
        # Okuma sayısı eşit değil: ikinci turda `kb.add` değişmemiş imzayı görüp dosyayı yeniden
        # açmıyor (mevcut yürütücü davranışı, §3) — rapor her iki türkende iki dosyayı da okur.
        self.assertEqual(sorted(self.reads[:2]), ["kira.txt", "maliyet.txt"])
        self.assertEqual(sorted(self.reads), ["kira.txt", "kira.txt", "kira.txt",
                                              "maliyet.txt", "maliyet.txt", "maliyet.txt"])

    def test_the_bare_listing_phrase_is_the_same_capability(self):
        self.seed(self.desktop, "kisa.txt")
        hint, args = self.hint_of("masaüstünde neler var")
        self.assertEqual(hint, FOLDER_ANALYSIS_CAPABILITY)
        self.assertEqual(args.get("folder"), "desktop")
        self.assertEqual(self.analyzed, [self.desktop])

    def test_the_diacritic_free_listing_phrase_matches_its_twin(self):
        self.seed(self.desktop, "kisa.txt")
        folded_hint, folded_args = self.hint_of("masaustunde ne var")
        self.assertEqual(folded_hint, FOLDER_ANALYSIS_CAPABILITY)
        self.assertEqual(folded_args.get("folder"), "desktop")
        self.assertEqual(self.analyzed, [self.desktop])

    def test_documents_pictures_and_jarvis_roots_are_all_supported(self):
        self.seed(self.documents, "sozlesme.txt")
        self.seed(self.pictures, "manzara.txt")
        self.seed(self.jarvis, "yuklenen.txt")
        for text, key, folder in (("belgeler klasörünü incele", "documents", self.documents),
                                  ("resimler klasörünü incele", "pictures", self.pictures),
                                  ("yüklediklerimi incele", "jarvis", self.jarvis),
                                  ("jarvis dosyalarini incele", "jarvis", self.jarvis)):
            self.analyzed.clear()
            with self.subTest(text):
                hint, args = self.hint_of(text)
                self.assertEqual(hint, FOLDER_ANALYSIS_CAPABILITY)
                self.assertEqual(args.get("folder"), key)
                self.assertEqual(self.analyzed, [folder])

    def test_the_quoted_subfolder_word_before_folder_keeps_the_base_answer(self):
        # TABAN (ed636bd, pr3c4_base3.json): "jarvis dosyaları klasöründe neler var" kullanıcıya
        # "'dosyaları' adlı bir klasör bulamadım" diye görünüyordu; kök tahminiyle genişletilmez.
        self.seed(self.jarvis, "yuklenen.txt")
        _entry, out = self.decide("jarvis dosyaları klasöründe neler var")
        self.assertIn("'dosyaları' adlı bir klasör bulamadım", out)
        self.assertEqual(self.analyzed, [])
        self.assertEqual(self.reads, [])

    def test_the_one_drive_redirected_and_known_folder_win_is_kept(self):
        # Emekli gramerin en dolu aday seçimi ve Windows Known Folder önceliği yürütücü tarafında kaldı.
        real = self.downloads.parent / "OneDrive" / "Desktop"
        real.mkdir(parents=True)
        (real / "b.txt").write_text("iki dosya", encoding="utf-8")
        _hint, args = self.hint_of("masaüstünde neler var")     # HOME'daki boş kalıntı değil, dolu OneDrive
        self.assertEqual(args.get("folder"), "desktop")
        self.assertEqual(self.analyzed, [real])
        with patch.object(nxapi, "known_folder", lambda name: real if name == "Desktop" else None):
            self.analyzed.clear()
            self.hint_of("masaüstünde neler var")
            self.assertEqual(self.analyzed, [real])             # Windows'un bildirdiği gerçek klasör
        # Bilinen klasör HOME dışında bir diske taşındıysa da hedef odur ve izinli kökler aynı kaynaktan çıkar.
        moved = Path(self.temp.name) / "tasinmis" / "Masaüstü"
        moved.mkdir(parents=True)
        (moved / "not.txt").write_text("taşınmış masaüstü kira", encoding="utf-8")
        with patch.object(nxapi, "known_folder", lambda name: moved if name == "Desktop" else None):
            self.analyzed.clear()
            _entry, out = self.decide("masaüstünde neler var")
            self.assertEqual(self.analyzed, [moved])
            self.assertIn("1 dosya var", out)

    def test_a_named_subfolder_is_resolved_to_that_directory(self):
        self.seed(self.downloads, "ust.txt")
        self.seed(self.sub, "proje-notu.txt")
        entry, out = self.decide("indirilenlerdeki proje klasörünü incele")
        self.assertEqual(entry.understanding.capability_hint, FOLDER_ANALYSIS_CAPABILITY)
        self.assertEqual(self.analyzed, [self.sub])
        self.assertIn("İndirilenler › Proje", out)

    def test_a_multiword_subfolder_name_is_resolved_by_core(self):
        self.seed(self.downloads / "Proje Çalışmaları", "not.txt")
        self.hint_of("indirilenlerdeki proje çalışmaları klasörünü incele")
        self.assertEqual(self.analyzed, [self.downloads / "Proje Çalışmaları"])

    def test_a_subfolder_mentioned_anywhere_in_the_sentence_is_still_evidence(self):
        # TABAN (pr3c4_base3.json): "…klasörü incele, proje var mı" İndirilenler › Proje'yi açtı;
        # kanonical zincir de aynı kanıtı kullanır: gerçek alt klasörün kendi adı sözün içinde geçiyor.
        self.seed(self.sub, "proje-notu.txt")
        self.seed(self.downloads, "ust.txt")
        _entry, out = self.decide("indirilenlerdeki klasörü incele, proje var mı")
        self.assertEqual(self.analyzed, [self.sub])
        self.assertIn("İndirilenler › Proje", out)

    def test_a_file_cue_in_the_sentence_keeps_the_files_read_owner(self):
        # TABAN: "indirilenlerdeki Proje Dosyaları klasörünü incele" cümlesini kanonical `files.read`
        # netleştirme sorusuyla üstleniyordu; klasör anahtarı o yüzeyin yetkisini geri almaz.
        self.seed(self.downloads / "Proje Dosyaları", "not.txt")
        _entry, out = self.decide("indirilenlerdeki Proje Dosyaları klasörünü incele")
        self.assertEqual(self.analyzed, [])
        self.assertEqual(self.reads, [])
        self.assertIn("Hangi dosyayı", str(out))

    def test_a_missing_subfolder_never_expands_to_its_parent(self):
        self.seed(self.downloads, "baska.txt")
        entry, out = self.decide("indirilenlerdeki olmayan klasörü incele")
        self.assertEqual(entry.understanding.capability_hint, FOLDER_ANALYSIS_CAPABILITY)
        self.assertEqual(self.analyzed, [], "bulunamayan alt klasör üst klasörü analiz edemez")
        self.assertEqual(self.reads, [])
        self.assertEqual(self.model, [])
        self.assertIn("'olmayan' adlı bir klasör bulamadım", out)
        self.assertNotIn("baska.txt", out)
        self.assertIsNone(self.ctx._session().pending_organize)

    def test_a_generic_word_before_folder_analyses_the_named_root(self):
        self.seed(self.downloads, "kira.txt")
        self.hint_of("şu klasörü incele")
        self.assertEqual(self.analyzed, [], "bilinen kök yoksa kanonical karar hiç claim etmez")
        self.hint_of("indirilenler klasörünü incele")
        self.assertEqual(self.analyzed, [self.downloads])

    def test_two_folder_words_go_to_the_folder_named_before_the_word_folder(self):
        self.seed(self.documents, "sozlesme.txt")
        self.hint_of("masaüstündeki belgeler klasörünü incele")
        self.assertEqual(self.analyzed, [self.documents])

    def test_a_real_subfolder_with_the_same_name_still_wins(self):
        child = self.desktop / "Belgeler"
        self.seed(child, "masaustu-calismasi.txt")
        self.seed(self.documents, "belgeler-koku.txt")
        self.hint_of("masaüstündeki belgeler klasörünü incele")
        self.assertEqual(self.analyzed, [child])

    def test_an_asking_verb_before_folder_is_not_a_name(self):
        # Emekli gramer: "… klasörünü özetle" fiilidir, alt klasör adı değil.
        self.seed(self.downloads, "kira.txt")
        self.hint_of("indirilenler klasörünü özetle")
        self.assertEqual(self.analyzed, [self.downloads])

    def test_the_preview_names_the_resolved_folder_once(self):
        self.seed(self.downloads, "kira.txt")
        entry, _out = self.decide("indirilenler klasörünü incele")
        self.assertIn("İndirilenler", str(entry.understanding.preview.text or ""))

    def test_the_request_is_never_reclassified_by_a_second_pass(self):
        self.seed(self.downloads, "kira.txt")
        self.decide("indirilenler klasörünü incele")
        self.assertEqual(self.turn_texts, [], "legacy yüzey aynı cümleyi ikinci kez yorumlayamaz")
        self.assertEqual(self.door.call_count, 0)

    def test_the_effect_is_read_plus_index_plus_exactly_one_model_call(self):
        self.seed(self.downloads, "kira.txt", "maliyet.txt")
        self.decide("indirilenler klasörünü incele")
        # Her dosya iki kez okunur — biri rapor, biri bilgi tabanı kaydı (tabanda da ölçülen aynı sayı).
        self.assertEqual(sorted(self.reads), ["kira.txt", "kira.txt", "maliyet.txt", "maliyet.txt"])
        self.assertEqual(sorted(self.indexed), ["kira.txt", "maliyet.txt"])
        self.assertEqual(len(self.model), 1)
        self.assertIn("kira", self.model[0])
        hits = [row["name"] for row in kb.file_hits(self.ctx.profile, "kira bedeli")]
        self.assertIn("kira.txt", hits)

    def test_a_model_failure_still_delivers_the_models_free_report(self):
        self.seed(self.downloads, "kira.txt")
        with patch("modules.llm.ask", side_effect=RuntimeError("429 kota")):
            _entry, out = self.decide("indirilenler klasörünü incele")
        self.assertIn("1 dosya var", out)
        self.assertIn("yapay zekâdan alamadım", out)

    def test_depth_secrets_and_cloud_only_limits_survive_the_canonical_path(self):
        self.seed(self.downloads, "yerel.txt")
        (self.downloads / "a" / "b" / "c").mkdir(parents=True)
        (self.downloads / "a" / "b" / "c" / "derin.txt").write_text("derin kira", encoding="utf-8")
        (self.downloads / "hesap şifreleri.txt").write_text("gmail 1234", encoding="utf-8")
        (self.downloads / "bulutta.txt").write_text("buluttaki kira", encoding="utf-8")
        real_stat = Path.stat

        def stat(self_, *args, **kwargs):
            result = real_stat(self_, *args, **kwargs)
            if self_.name == "bulutta.txt":
                class Cloud:
                    st_size, st_mtime, st_mode = result.st_size, result.st_mtime, result.st_mode
                    st_file_attributes = 0x400000
                return Cloud()
            return result

        with patch.object(Path, "stat", stat):
            _entry, out = self.decide("indirilenler klasörünü incele")
        self.assertIn("1 alt klasöre inmedim", out)
        self.assertIn("hiç açmadığım 1 dosya", out)
        self.assertIn("yalnız çevrimiçi", out)
        self.assertNotIn("derin.txt", self.reads)
        self.assertNotIn("hesap şifreleri.txt", self.reads)
        self.assertNotIn("bulutta.txt", self.reads)
        self.assertNotIn("1234", self.model[0])

    def test_a_folder_outside_the_permitted_roots_is_refused(self):
        outside = Path(self.temp.name) / "disari"
        outside.mkdir()
        (outside / "gizli.txt").write_text("dış", encoding="utf-8")
        _hint, args = self.hint_of("indirilenler klasörünü incele")
        self.assertEqual(args.get("folder"), "downloads")
        self.assertEqual(self.analyzed, [self.downloads])
        self.assertIn("erişemiyorum", folder_analysis.analyze(self.ctx.profile, outside))


class FolderAnalysisNeighboursTests(_FolderHarness):
    def test_desktop_organization_stays_with_the_pr3c3_owner(self):
        self.seed(self.desktop, "belge.txt")
        hint, args = self.hint_of("masaüstünü düzenle")
        self.assertEqual(hint, "files.organize")
        self.assertEqual(args.get("folder"), "desktop")
        self.assertEqual(self.analyzed, [], "düzenleme cümlesi klasör analizi yürütmez")

    def test_a_single_file_request_stays_with_files_read(self):
        self.seed(self.downloads, "rapor.txt")
        hint, _args = self.hint_of("indirilenlerdeki rapor dosyasını özetle")
        self.assertEqual(hint, "files.read")
        self.assertEqual(self.analyzed, [])

    def test_an_explanation_question_opens_and_reads_no_file(self):
        self.seed(self.downloads, "kira.txt")
        _entry, out = self.decide("klasör analizi nasıl çalışır?")
        self.assertEqual(self.analyzed, [])
        self.assertEqual(self.reads, [])
        self.assertEqual(self.model, [])
        self.assertEqual(self.indexed, [])
        self.assertEqual(out, "CHAT")

    def test_vetoed_verbs_never_claim_folder_analysis(self):
        self.seed(self.downloads, "kira.txt")
        for text in ("indirilenler klasörünü aç", "masaüstünü temizle", "indirilenleri izle",
                     "indirilenleri açar mısın", "masaüstünü düzenler misin", "bu klasörü sil",
                     "indirilenlerde kira geçiyor mu", "bugün ne var", "evde neler var",
                     "dosyalarımı göster", "resim nedir"):
            with self.subTest(text):
                self.analyzed.clear()
                hint, _args = self.hint_of(text)
                self.assertNotEqual(hint, FOLDER_ANALYSIS_CAPABILITY)
                self.assertEqual(self.analyzed, [])

    def test_an_unrelated_sentence_claims_no_folder_authority(self):
        self.seed(self.downloads, "kira.txt")
        hint, _args = self.hint_of("bana bir masal anlat")
        self.assertNotEqual(hint, FOLDER_ANALYSIS_CAPABILITY)
        self.assertEqual(self.analyzed, [])

    def test_no_pending_state_survives_the_analysis_turn(self):
        self.seed(self.downloads, "kira.txt")
        self.decide("indirilenler klasörünü incele")
        session = self.ctx._session()
        self.assertIsNone(session.pending_organize)
        self.assertIsNone(getattr(session, "pending_confirm", None))


class CoreValidationTests(_FolderHarness):
    def test_core_revalidates_the_key_in_the_closed_set(self):
        from modules import brain_core_map
        self.assertIsNone(brain_core_map.core_plan(
            FOLDER_ANALYSIS_CAPABILITY, {"operation": FOLDER_ANALYSIS_OPERATION, "folder": ".."}))
        self.assertIsNone(brain_core_map.core_plan(
            FOLDER_ANALYSIS_CAPABILITY, {"operation": FOLDER_ANALYSIS_OPERATION, "folder": "windows"}))
        self.assertIsNone(brain_core_map.core_plan(
            FOLDER_ANALYSIS_CAPABILITY, {"operation": "delete", "folder": "downloads"}))

    def test_core_does_not_take_a_path_from_the_proposal(self):
        from modules import brain_core_map
        self.assertIsNone(brain_core_map.core_plan(
            FOLDER_ANALYSIS_CAPABILITY,
            {"operation": FOLDER_ANALYSIS_OPERATION, "folder": "downloads",
             "path": str(self.downloads)}))

    def test_core_rejects_a_name_that_is_not_a_permitted_child(self):
        from modules import brain_core_map
        plan = brain_core_map.core_plan(
            FOLDER_ANALYSIS_CAPABILITY,
            {"operation": FOLDER_ANALYSIS_OPERATION, "folder": "downloads", "name": "../../Windows"})
        self.assertIsNone(plan)

    def test_core_carries_no_path_and_no_foreign_key(self):
        from modules import brain_core_map
        plan = brain_core_map.core_plan(
            FOLDER_ANALYSIS_CAPABILITY,
            {"operation": FOLDER_ANALYSIS_OPERATION, "folder": "downloads", "named": "", "name": ""})
        self.assertEqual(plan, ("folder_analyze", {"operation": FOLDER_ANALYSIS_OPERATION,
                                                   "folder": "downloads", "named": "", "name": ""}))
        self.assertNotIn("path", str(plan))

    def test_the_understanding_key_set_equals_the_domain_closed_set(self):
        from modules import brain_understanding
        self.assertEqual(tuple(key for key, _pattern in brain_understanding._FOLDER_ANALYSIS_WORDS),
                         tuple(folder_analysis.FOLDER_KEYS))

    def test_the_plan_dispatches_once_through_the_canonical_intent(self):
        self.seed(self.downloads, "kira.txt")
        calls = []
        real = engine_intents.dispatch

        def spy(runtime, intent, a, command, cmd_lower):
            calls.append((intent, dict(a), command))
            return real(runtime, intent, a, command, cmd_lower)

        with patch.object(engine_intents, "dispatch", spy):
            self.decide("indirilenler klasörünü incele")
        self.assertEqual([c[0] for c in calls], ["folder_analyze"])
        self.assertEqual(calls[0][1]["folder"], "downloads")
        self.assertEqual(calls[0][2], "indirilenler klasörünü incele")

    def test_precedence_keeps_the_legacy_gates_off_a_validated_folder_plan(self):
        plan = ("folder_analyze", {"operation": FOLDER_ANALYSIS_OPERATION, "folder": "downloads"})
        self.assertEqual(brain_precedence.FRONT_GATES, ("file_command", "macro_run"))
        self.assertFalse(hasattr(brain_precedence, "_gates"))
        self.assertFalse(hasattr(engine_tools, "_extra_commands"))
        self.assertIsNone(brain_precedence.claim(self.ctx, "indirilenler klasörünü incele", plan))



class RawDoorRetirementTests(unittest.TestCase):
    def test_the_cascade_no_longer_carries_the_folder_analysis_branch(self):
        # Yorum satırları ("klasör analizi artık kanonical hatta") serbest; AST teması yasak.
        self.assertEqual(_folder_analysis_touches(ENGINE_TOOLS_SOURCE), [],
                         "klasör analizi yetkisi kanonical hatta taşındı; ham kapı kolu kalmamalı")

    def test_the_executor_is_reached_only_from_the_canonical_seam(self):
        self.assertEqual(sorted(pr3b._source_calls("folder_analysis.analyze_turn")),
                         ["modules/engine_intents.py"])

    def test_the_ui_quoted_folder_answer_keeps_its_own_direct_call(self):
        # Kanonical zincir dışında kalan tek yürütücü çağrısı arayüzün alıntılanmış klasör cevabıdır.
        self.assertEqual(sorted(pr3b._source_calls("folder_analysis.analyze")),
                         ["modules/main_documents.py"])

    def test_the_raw_sentence_door_functions_are_gone(self):
        for name in ("handle", "resolve", "target"):
            self.assertFalse(hasattr(folder_analysis, name), f"{name} ham cümleyi yorumlayan eski kapı")


if __name__ == "__main__":
    unittest.main()
