"""PR3C-3: masaüstü düzenleme (klasör organize) kanonical parite.

PR #507 sonrası `masaüstünü düzenle` tek kanonical sahibinden çıkmıştı: ham cümle legacy
`_extra_commands` içindeki kendi kalıbını arıyordu, bozuk yazım ("duzenle") ise hiçbir yetenekte
karşılık bulup önizleme üretemiyordu. Bu dosya akışı kanonical hatta kilitler:

    istek → önizleme (HİÇBİR DOSYA TAŞINMAZ) → tek onay → düzenleme → geri alma

Kanıtlanan tek `files.py` kusuru (paylaşılan/ düşen geri alma kaydı) ayrı dosyadadır:
`test_folder_organize_owner.py`. Buradaki her dosya efekti GEÇİCİ dizinde gerçekten çalışır;
hiçbir test kullanıcının gerçek Masaüstü/İndirilenler/Belgeler klasörünü veya `~/.jarvis`
geri alma kaydını okumaz/yazmaz.
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import test_brain_pr3b_legacy_front_door_authority as pr3b
from modules import brain_entry, brain_precedence, engine_tools, files, file_resource_guard
from modules.brain_contracts import RequestKind
from modules.brain_understanding import ORGANIZE_CAPABILITY, ORGANIZE_TARGET_AMBIGUOUS

ROOT = Path(__file__).resolve().parents[1]
ENGINE_TOOLS_SOURCE = (ROOT / "modules" / "engine_tools.py").read_text(encoding="utf-8")


class _OrganizeHarness(pr3b._RawDoorHarness):
    """Kanonical zincir + gerçek `files` domain'i, hepsi geçici kökte."""

    def setUp(self):
        super().setUp()
        root = Path(self.temp.name)
        self.desktop = root / "Masaüstü"
        self.downloads = root / "İndirilenler"
        self.documents = root / "Belgeler"
        for folder in (self.desktop, self.downloads, self.documents):
            folder.mkdir(parents=True, exist_ok=True)
        self._folders = {
            "Desktop": self.desktop, "OneDrive/Desktop": self.desktop,
            "OneDrive/Masaüstü": self.desktop, "Masaüstü": self.desktop,
            "Downloads": self.downloads, "İndirilenler": self.downloads,
            "Documents": self.documents, "OneDrive/Documents": self.documents,
            "OneDrive/Belgeler": self.documents, "Belgeler": self.documents,
        }
        self.apply_spy = Mock(side_effect=files.apply_organize)
        self.undo_spy = Mock(side_effect=files.undo_organize)
        for target, attr, value in (
            (files, "folder_path", lambda cands: self._folders.get(next((c for c in cands if c in self._folders), ""))),
            (files, "DATA_DIR", root / "state"),
            (files, "apply_organize", self.apply_spy),
            (files, "undo_organize", self.undo_spy),
            (brain_entry, "build_candidates", lambda **kw: ()),
        ):
            starter = patch.object(target, attr, value)
            starter.start()
            self.addCleanup(starter.stop)
        claim_patch = patch.object(
            file_resource_guard, '_FILE_EFFECT_CLAIM_ROOT',
            root / 'os-claims',
        )
        claim_patch.start()
        self.addCleanup(claim_patch.stop)
        self.ctx.files = files
        # Geri alma kolunun gerçek sahibi cascade'de kalır: pr3b onu Mock'lar.
        extra = engine_tools._extra_commands
        self.ctx._extra_commands = lambda command, lowered: extra(self.ctx, command, lowered)
        self.ctx._session().pending_organize = None

    def seed(self, folder, *names):
        for name in names:
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{name} içeriği", encoding="utf-8")
        return folder

    def tree(self, folder):
        return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())

    def preview(self, text):
        return self.turn(text)


class CanonicalOrganizePreviewTests(_OrganizeHarness):
    def test_a_misspelled_desktop_organize_previews_and_moves_nothing(self):
        self.seed(self.desktop, "belge.txt", "foto.png")
        entry, out, _handle, feedback = self.preview("masaüstünü duzenle")
        self.assertIs(entry.understanding.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(entry.understanding.capability_hint, ORGANIZE_CAPABILITY)
        self.assertEqual(entry.understanding.arguments.get("folder"), "desktop")
        self.assertEqual(self.turn_texts, [], "kanonical plan legacy kapıya ikinci kez düşmemeli")
        self.run_goal.assert_not_called()
        job = self.ctx._session().pending_organize
        self.assertIsNotNone(job)
        self.assertEqual(Path(job["folder"]), self.desktop)
        self.assertEqual(sorted(str(src).replace("\\", "/").rpartition("/")[2] for src, _ in job["plan"]),
                         ["belge.txt", "foto.png"])
        self.assertIn("taşıyayım mı", out)
        self.assertEqual(result_status(feedback), "needs_input")
        # Önizleme tek başına etki üretmez: hiçbir dosya yerinden kıpırdamadı.
        self.assertEqual(self.tree(self.desktop), ["belge.txt", "foto.png"])
        self.apply_spy.assert_not_called()

    def test_the_correctly_spelled_twin_is_the_same_plan(self):
        self.seed(self.desktop, "belge.txt", "foto.png")
        typo_entry, typo_out, _, _ = self.preview("masaüstünü duzenle")
        first = dict(self.ctx._session().pending_organize or {})
        self.ctx._session().pending_organize = None
        correct_entry, correct_out, _, _ = self.preview("masaüstünü düzenle")
        self.assertEqual(correct_entry.understanding.capability_hint, typo_entry.understanding.capability_hint)
        self.assertEqual(correct_entry.understanding.arguments.get("folder"), "desktop")
        second = dict(self.ctx._session().pending_organize or {})
        self.assertEqual([str(s) for s, _ in first.get("plan", [])], [str(s) for s, _ in second.get("plan", [])])
        self.assertEqual(typo_out, correct_out)
        self.assertEqual(self.tree(self.desktop), ["belge.txt", "foto.png"])

    def test_an_english_desktop_word_resolves_to_the_same_verified_folder(self):
        self.seed(self.desktop, "not.txt")
        entry, _out, _, _ = self.preview("desktoptaki gereksizleri duzenle")
        self.assertEqual(entry.understanding.arguments.get("folder"), "desktop")
        self.assertEqual(Path(self.ctx._session().pending_organize["folder"]), self.desktop)

    def test_a_gereksizleri_request_never_grants_deletion(self):
        self.seed(self.desktop, "eski.log", "belge.txt")
        _entry, out, _handle, _ = self.preview("masaüstündeki gereksizleri duzenle")
        self.assertEqual(self.tree(self.desktop), ["belge.txt", "eski.log"])
        self.apply_spy.assert_not_called()
        for verb in ("sildim", "sileceğim", "silecek"):
            self.assertNotIn(verb, out)

    def test_downloads_and_documents_use_their_own_verified_folders(self):
        self.seed(self.downloads, "kurulum.exe")
        self.seed(self.documents, "ozet.docx")
        _entry, out, _, _ = self.preview("indirilenleri düzenle")
        self.assertEqual(Path(self.ctx._session().pending_organize["folder"]), self.downloads)
        self.assertIn("İndirilenler", out)
        self.ctx._session().pending_organize = None
        self.preview("belgeleri topla")
        self.assertEqual(Path(self.ctx._session().pending_organize["folder"]), self.documents)
        self.assertEqual(self.tree(self.downloads), ["kurulum.exe"])
        self.assertEqual(self.tree(self.documents), ["ozet.docx"])

    def test_two_folders_in_one_request_ask_which_and_move_nothing(self):
        self.seed(self.desktop, "a.txt")
        self.seed(self.downloads, "b.txt")
        entry, out, _handle, _ = self.preview("masaüstünü ve indirilenleri düzenle")
        self.assertIs(entry.understanding.request_kind, RequestKind.CLARIFY)
        self.assertIn(ORGANIZE_TARGET_AMBIGUOUS, entry.understanding.ambiguities)
        self.assertIsNone(self.ctx._session().pending_organize)
        self.assertIn("Hangi klasörü", out)
        self.assertEqual(self.tree(self.desktop), ["a.txt"])
        self.assertEqual(self.tree(self.downloads), ["b.txt"])
        self.apply_spy.assert_not_called()

    def test_the_meta_question_starts_no_preview_and_no_pending(self):
        self.seed(self.desktop, "a.txt")
        entry, _out, _handle, _ = self.preview("masaüstünü düzenlemek nasıl çalışır?")
        self.assertIs(entry.understanding.request_kind, RequestKind.CHAT)
        self.assertIsNone(entry.understanding.capability_hint)
        self.assertIn("EXPLANATION_REQUEST", tuple(entry.understanding.reason_codes))
        self.assertIsNone(self.ctx._session().pending_organize)
        self.assertEqual(self.tree(self.desktop), ["a.txt"])
        self.apply_spy.assert_not_called()

    def test_an_advisory_sentence_about_organizing_stays_a_conversation(self):
        # Acceptance `rota-e5618a6aef` (465 satır): "…masaüstünü düzenleyeceğim nereden başlamak
        # mantıklı" tabanda sohbet yanıtıydı. Gelecek zamanlı birinci kişi bir emir değildir; fiil
        # listesi kapalı tutulur ki öğüt sorusu önizleme + onay yetkisi almasın.
        self.seed(self.desktop, "a.txt")
        entry, _out, _handle, _ = self.preview("şimdi diyelim ki masaüstünü düzenleyeceğim nereden başlamak mantıklı")
        self.assertNotEqual(entry.understanding.capability_hint, ORGANIZE_CAPABILITY)
        self.assertIsNone(self.ctx._session().pending_organize)
        self.assertEqual(self.tree(self.desktop), ["a.txt"])
        self.apply_spy.assert_not_called()

    def test_the_undo_sentence_is_not_an_organize_preview(self):
        self.seed(self.desktop, "a.txt")
        entry, _out, _handle, _ = self.preview("düzenlemeyi geri al")
        self.assertNotEqual(entry.understanding.capability_hint, ORGANIZE_CAPABILITY)
        self.assertIsNone(self.ctx._session().pending_organize)
        self.assertEqual(self.tree(self.desktop), ["a.txt"])

    def test_an_empty_folder_previews_without_a_pending_confirmation(self):
        _entry, out, _handle, _ = self.preview("masaüstünü düzenle")
        self.assertIn("düzenlenecek dosya yok", out)
        self.assertIsNone(self.ctx._session().pending_organize)

    def test_shortcuts_temporary_files_and_folders_stay_out_of_the_plan(self):
        self.seed(self.desktop, "masaustu.lnk", "indirilen.pdf.tmp", "kaldirilan.txt.part")
        (self.desktop / "klasör").mkdir()
        (self.desktop / "klasör" / "içerik.txt").write_text("x", encoding="utf-8")
        _entry, _out, _, _ = self.preview("masaüstünü düzenle")
        self.assertIsNone(self.ctx._session().pending_organize)
        self.assertEqual(self.tree(self.desktop), ["indirilen.pdf.tmp", "kaldirilan.txt.part",
                                                   "klasör/içerik.txt", "masaustu.lnk"])


class CanonicalOrganizeApprovalTests(_OrganizeHarness):
    def test_one_yes_applies_the_previewed_plan_exactly_once(self):
        self.seed(self.desktop, "belge.txt", "foto.png")
        self.preview("masaüstünü duzenle")
        self.apply_spy.reset_mock()
        _entry, out, _handle, _ = self.turn("evet")
        self.apply_spy.assert_called_once()
        self.assertIn("düzenledim", out)
        self.assertEqual(self.tree(self.desktop), ["Belgeler/belge.txt", "Resimler/foto.png"])
        self.assertIsNone(self.ctx._session().pending_organize)

    def test_a_repeated_yes_starts_no_second_effect(self):
        self.seed(self.desktop, "belge.txt")
        self.preview("masaüstünü düzenle")
        self.turn("evet")
        after = self.tree(self.desktop)
        self.apply_spy.reset_mock()
        self.turn("evet")
        self.apply_spy.assert_not_called()
        self.assertEqual(self.tree(self.desktop), after)

    def test_no_and_cancel_leave_every_file_where_it_was(self):
        for answer in ("hayır", "iptal", "boşver"):
            with self.subTest(answer=answer):
                self.seed(self.desktop, "belge.txt")
                self.preview("masaüstünü düzenle")
                self.apply_spy.reset_mock()
                _entry, out, _handle, _ = self.turn(answer)
                self.assertIn("dosyalara dokunmadım", out)
                self.apply_spy.assert_not_called()
                self.assertEqual(self.tree(self.desktop), ["belge.txt"])
                self.assertIsNone(self.ctx._session().pending_organize)

    def test_an_unrelated_answer_does_not_consume_the_organize_approval(self):
        self.seed(self.desktop, "belge.txt")
        self.preview("masaüstünü düzenle")
        self.apply_spy.reset_mock()
        _entry, _out, _handle, _ = self.turn("yarın hava nasıl")
        self.apply_spy.assert_not_called()
        self.assertEqual(self.tree(self.desktop), ["belge.txt"])
        self.assertIsNotNone(self.ctx._session().pending_organize)

    def test_two_open_confirmations_own_the_same_answer_and_neither_moves(self):
        self.seed(self.desktop, "belge.txt")
        self.preview("masaüstünü düzenle")
        self.ctx._session().pending_confirm = {"action": "close_app", "name": "chrome"}
        self.apply_spy.reset_mock()
        entry, out, _handle, _ = self.turn("evet")
        self.assertEqual(entry.state_gate.reason_code, "MULTIPLE_BOUNDED_STATE_MATCHES")
        self.assertIn("netleştir", out)
        self.apply_spy.assert_not_called()
        self.assertEqual(self.tree(self.desktop), ["belge.txt"])
        self.assertIsNotNone(self.ctx._session().pending_organize)
        self.assertIsNotNone(self.ctx._session().pending_confirm)

    def test_a_folder_that_changed_since_the_preview_is_re_previewed_not_moved(self):
        self.seed(self.desktop, "belge.txt")
        self.preview("masaüstünü düzenle")
        self.seed(self.desktop, "yeni.xlsx")
        self.apply_spy.reset_mock()
        _entry, out, _handle, _ = self.turn("evet")
        self.apply_spy.assert_not_called()
        self.assertIn("taşıyayım mı", out)
        self.assertEqual(self.tree(self.desktop), ["belge.txt", "yeni.xlsx"])
        job = self.ctx._session().pending_organize
        self.assertEqual(len(job["plan"]), 2)
        self.turn("evet")
        self.assertEqual(sorted(self.tree(self.desktop)), ["Belgeler/belge.txt", "Belgeler/yeni.xlsx"])

    def test_a_source_deleted_after_the_preview_is_dropped_without_moving_others(self):
        self.seed(self.desktop, "belge.txt", "ozet.docx")
        self.preview("masaüstünü düzenle")
        (self.desktop / "belge.txt").unlink()
        self.apply_spy.reset_mock()
        _entry, out, _handle, _ = self.turn("evet")
        self.apply_spy.assert_not_called()
        self.assertEqual(self.tree(self.desktop), ["ozet.docx"])
        self.assertIn("taşıyayım mı", out)
        self.assertEqual(len(self.ctx._session().pending_organize["plan"]), 1)

    def test_a_destination_collision_never_overwrites_the_existing_file(self):
        self.seed(self.desktop, "belge.txt")
        self.seed(self.desktop / "Belgeler", "belge.txt")
        before = (self.desktop / "Belgeler" / "belge.txt").read_text(encoding="utf-8")
        self.preview("masaüstünü düzenle")
        _entry, _out, _handle, _ = self.turn("evet")
        self.assertEqual((self.desktop / "Belgeler" / "belge.txt").read_text(encoding="utf-8"), before)
        self.assertEqual(sorted(self.tree(self.desktop)), ["Belgeler/belge (1).txt", "Belgeler/belge.txt"])

    def test_a_file_edited_after_the_preview_is_not_moved_under_the_old_approval(self):
        # Red: tazelik yalnız yol çiftlerini karşılaştırıyordu; önizlemeden sonra içeriği değişen
        # dosya aynı yol ve aynı hedefle planı "değişmemiş" gösterip ESKİ onayla taşınıyordu.
        self.seed(self.desktop, "rapor.txt")
        self.preview("masaüstünü düzenle")
        (self.desktop / "rapor.txt").write_text("kullanıcının yeni uzun içeriği", encoding="utf-8")
        self.apply_spy.reset_mock()
        _entry, out, _handle, _ = self.turn("evet")
        self.apply_spy.assert_not_called()
        self.assertIn("taşıyayım mı", out)
        self.assertEqual(self.tree(self.desktop), ["rapor.txt"])
        self.assertEqual(self.ctx._session().pending_organize["plan"], [(self.desktop / "rapor.txt",
                                                                          self.desktop / "Belgeler" / "rapor.txt")])
        # Taze önizleme onaylanınca gerçek içerik korunarak taşınır.
        self.turn("evet")
        self.assertEqual(self.tree(self.desktop), ["Belgeler/rapor.txt"])
        self.assertEqual((self.desktop / "Belgeler" / "rapor.txt").read_text(encoding="utf-8"),
                         "kullanıcının yeni uzun içeriği")

    def test_a_different_file_swapped_into_the_previewed_path_is_not_moved(self):
        # Red: aynı adda ve aynı boyda başka bir dosya konduğunda yol karşılaştırması hiçbir şey
        # görmüyordu; eski onay yabancı dosyayı kategoriye taşıyordu.
        self.seed(self.desktop, "rapor.txt")
        self.preview("masaüstünü düzenle")
        swap = self.downloads / "baska.txt"
        swap.write_text("baska dosya icerigi", encoding="utf-8")
        original = self.desktop / "rapor.txt"
        stamp = original.stat()
        os.replace(swap, original)
        os.utime(original, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        self.assertEqual(original.stat().st_size, stamp.st_size)
        self.apply_spy.reset_mock()
        _entry, out, _handle, _ = self.turn("evet")
        self.apply_spy.assert_not_called()
        self.assertIn("taşıyayım mı", out)
        self.assertEqual(self.tree(self.desktop), ["rapor.txt"])
        self.assertEqual(original.read_text(encoding="utf-8"), "baska dosya icerigi")

    def test_an_unchanged_folder_still_applies_after_the_freshness_stamp(self):
        # Kilit: tazelik denetimi sıradan akışı bozmaz — dokunulmamış klasör tek onayla bir kez yürür.
        self.seed(self.desktop, "belge.txt")
        self.preview("masaüstünü düzenle")
        self.apply_spy.reset_mock()
        self.turn("evet")
        self.apply_spy.assert_called_once()
        self.assertEqual(self.tree(self.desktop), ["Belgeler/belge.txt"])

    def test_a_chained_or_ambiguous_request_starts_no_move_without_approval(self):
        self.seed(self.desktop, "belge.txt")
        self.seed(self.downloads, "paket.zip")
        self.apply_spy.reset_mock()
        _entry, _out, _handle, _ = self.turn("masaüstünü düzenle sonra indirilenleri düzenle")
        self.apply_spy.assert_not_called()
        self.assertEqual(self.tree(self.desktop), ["belge.txt"])
        self.assertEqual(self.tree(self.downloads), ["paket.zip"])


class CanonicalOrganizeUndoTests(_OrganizeHarness):
    def test_undo_returns_every_moved_file_to_its_original_place(self):
        self.seed(self.desktop, "belge.txt", "foto.png")
        self.preview("masaüstünü düzenle")
        self.turn("evet")
        self.assertEqual(self.tree(self.desktop), ["Belgeler/belge.txt", "Resimler/foto.png"])
        _entry, out, _handle, _ = self.turn("düzenlemeyi geri al")
        self.assertIn("eski yerine", out)
        self.assertEqual(self.tree(self.desktop), ["belge.txt", "foto.png"])
        self.assertEqual(self.undo_spy.call_args.args, (self.owner,))

    def test_a_second_undo_reports_no_record_and_touches_nothing(self):
        self.seed(self.desktop, "belge.txt")
        self.preview("masaüstünü düzenle")
        self.turn("evet")
        self.turn("düzenlemeyi geri al")
        _entry, out, _handle, _ = self.turn("düzenlemeyi geri al")
        self.assertIn("kaydı yok", out)
        self.assertEqual(self.tree(self.desktop), ["belge.txt"])

    def test_undo_never_reaches_for_another_users_record(self):
        self.seed(self.desktop, "belge.txt")
        self.preview("masaüstünü düzenle")
        self.turn("evet")
        other = files._undo_file("baska-kullanici")
        other.parent.mkdir(parents=True, exist_ok=True)
        other.write_text('[["x", "y"]]', encoding="utf-8")
        self.turn("düzenlemeyi geri al")
        self.assertTrue(other.is_file(), "kullanıcının geri alma hakkı başka kayda sızmış")


class CanonicalOrganizeOwnerLocksTests(_OrganizeHarness):
    def test_the_organize_plan_shadows_the_raw_text_domain_gates(self):
        # Plan sahibi olan cümle planner/cascade kapılarına ikinci kez sorulmaz (§25 B).
        self.seed(self.desktop, "belge.txt")
        gates = brain_precedence._gates(self.ctx, "masaüstünü düzenle", "masaüstünü düzenle",
                                        ("file_organize", {"operation": "organize", "folder": "desktop"}))
        self.assertIsNone(gates["planner_command"]())
        self.assertIsNone(gates["extra_commands"]())
        self.ctx._planner_command.assert_not_called()
        self.assertEqual(self.tree(self.desktop), ["belge.txt"])

    def test_no_file_is_moved_by_the_preview_turn_alone(self):
        self.seed(self.desktop, "belge.txt")
        self.turn("masaüstünü düzenle")
        self.apply_spy.assert_not_called()
        self.assertEqual(self.tree(self.desktop), ["belge.txt"])


class LegacyOrganizeFrontDoorRetiredTests(unittest.TestCase):
    """§4/§25: anlam artık kanonical karar; legacy ham-metin kalıbı üretimde kalamaz."""

    def test_the_legacy_raw_text_preview_branch_is_gone(self):
        self.assertNotIn("wants_organize", ENGINE_TOOLS_SOURCE)
        self.assertNotIn("pending_organize = {\"folder\"", ENGINE_TOOLS_SOURCE)

    def test_the_domain_no_longer_reads_the_raw_sentence(self):
        self.assertFalse(hasattr(files, "wants_organize"),
                         "files.py ham cümleden düzenleme niyeti çıkarmaya devam ediyor")

    def test_the_undo_branch_stays_with_its_owner(self):
        self.assertIn("undo_organize(runtime.profile.slug)", ENGINE_TOOLS_SOURCE)


def result_status(feedback) -> str:
    return str(getattr(feedback, "result_status", ""))


if __name__ == "__main__":
    unittest.main()
