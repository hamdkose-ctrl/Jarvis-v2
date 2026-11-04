"""PR3C-1: canonical yazım toleransı — iki kaybedilen kullanıcı davranışı.

PR #507 sonrası `chromu acar misin` ve `şu pdfyi worde cevir` hiçbir doğrulanmış yeteneğe
bağlanmıyordu (ölçüldü: capability yok, etki yok, genel cümle çiti). Bu dosya toleransı
*yalnız* canonical Understanding katmanında kilitler:

- düzeltilmiş/katlanmış görünüm yürütülebilir komut değildir; ikinci `handle()` geçişi yoktur,
- uygulama hedefi yalnız kapalı `app_identities.APPS` kimliğine katlanmış eşitlik/tek düzenleme
  ile çözüldüğünde `app.open` doğar; çözülemezse etki değil netleştirme sorusu doğar,
- `worde çevir` dil çevirisi değil dosya dönüştürmedir; doğrulanmış dosya referansı yoksa hangi
  dosya olduğu sorulur.

Üretim zinciri sınanır (`brain_entry.prepare → handoff → EngineContext.handle`); canlı kullanıcı
state'i okunmaz ve kullanıcının gerçek dosyalarına yazılmaz.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import test_brain_closeout_a  # noqa: F401  (shared test stubs)
import test_brain_pr3b_legacy_front_door_authority as pr3b
import test_brain_production_entry as fx
from modules import brain_entry, brain_understanding as understanding, nxapi, typo
from modules.brain_contracts import ContextReference, RequestKind
from modules.brain_understanding import (APP_CLOSE_CAPABILITY, APP_OPEN_CAPABILITY, APP_TARGET_MISSING,
                                         FILE_CONVERT, FILE_TARGET_UNRESOLVED)


def file_ref(path, owner=fx.OWNER):
    path = str(path)
    return ContextReference(
        id=path,
        kind="file",
        source="nxapi.file_inventory",
        owner=owner,
        provenance={"inventory_scope": "global_pc", "path": path, "name": Path(path).name},
    )


class _UnderstandingCase(unittest.TestCase):
    def understand(self, text, refs=()):
        refs = tuple(refs)
        return understanding.understand(
            owner=fx.OWNER,
            request_id=fx.RID,
            text=text,
            active_context=fx.context(),
            candidates=refs,
            references=refs,
        )


class AppTypoDecisionTests(_UnderstandingCase):
    def test_a_typoed_app_open_is_the_same_typed_capability_with_one_verified_identity(self):
        result = self.understand("chromu acar misin")
        self.assertIs(result.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(result.capability_hint, APP_OPEN_CAPABILITY)
        self.assertEqual(result.arguments.get("app"), "chrome")
        self.assertFalse(result.needs_input)

    def test_the_correctly_spelled_twins_keep_their_existing_proposals(self):
        opened = self.understand("chrome'u açar mısın")
        self.assertEqual(opened.capability_hint, APP_OPEN_CAPABILITY)
        self.assertEqual(opened.arguments.get("app"), "chrome'u")
        closed = self.understand("chrome'u kapat")
        self.assertEqual(closed.capability_hint, APP_CLOSE_CAPABILITY)
        self.assertEqual(closed.arguments.get("app"), "chrome'u")

    def test_an_unverified_typoed_target_asks_instead_of_proposing_an_effect(self):
        result = self.understand("qwerty acar misin")
        self.assertIs(result.request_kind, RequestKind.CLARIFY)
        self.assertTrue(result.needs_input)
        self.assertIn(APP_TARGET_MISSING, result.ambiguities)
        self.assertEqual(result.arguments.get("app_target_kind"), APP_OPEN_CAPABILITY)
        self.assertNotIn("app", result.arguments)

    def test_a_deictic_ambiguous_target_declines_the_legacy_action(self):
        # Corpus satırı `orda bi tane vardı onu ac` 20d9886'da eski handler'ın task projection'ıydı;
        # katlanmış aç grameri hedefi doğrulayamaz, etki yerine netleştirme sorusu üretir.
        result = self.understand("orda bi tane vardı onu ac")
        self.assertIs(result.request_kind, RequestKind.CLARIFY)
        self.assertIn(APP_TARGET_MISSING, result.ambiguities)
        self.assertNotIn("app", result.arguments)

    def test_tolerance_never_bypasses_the_blocked_owner_list(self):
        # Ses/medya/bilgisayar hedefleri kendi tipli yollarına aittir; katlanmış aç grameri
        # bir uygulama hedefi üretmez.
        for text in ("sesi acar misin", "muzigi acar misin", "bilgisayari acar misin"):
            with self.subTest(text=text):
                result = self.understand(text)
                self.assertNotEqual(result.capability_hint, APP_OPEN_CAPABILITY)
                self.assertNotIn("app", result.arguments)

    def test_tolerance_never_claims_a_chain_or_a_web_page(self):
        for text in ("chromu acar misin ve kapat", "chromu acar misin, sonra kapat",
                     "windows terminal indirme sayfasini acar misin"):
            with self.subTest(text=text):
                self.assertIsNone(understanding._app_request(text), text)

    def test_the_folded_view_is_length_preserving_so_spans_stay_aligned(self):
        for text in ("chromu acar misin", "şu pdfyi worde cevir", "chrome'u açar mısın"):
            with self.subTest(text=text):
                self.assertEqual(len(typo.fold(text)), len(text))


class AliasVerificationTests(unittest.TestCase):
    """Hedef çözümlemesi kapalı sabit listeye bağlıdır; liste dışı ya da çoklu eşleşme fail-closed."""

    def test_exact_and_one_edit_forms_resolve_to_the_static_alias(self):
        for spoken, alias in (("chrome", "chrome"), ("chromu", "chrome"), ("chrome'u", "chrome"),
                              ("not defterini", "not defteri")):
            with self.subTest(spoken=spoken):
                self.assertEqual(understanding._verified_app_alias(spoken), alias)

    def test_an_unknown_or_ambiguous_target_is_not_resolved(self):
        self.assertIsNone(understanding._verified_app_alias("qwerty"))
        # Tam eşleşme yokken iki sabit kimlik de tek düzenleme uzaklığındaysa hedef seçilmez.
        with patch("modules.app_identities.APPS", {"alpha": "a.exe", "alpah": "b.exe"}):
            self.assertIsNone(understanding._verified_app_alias("alph"))
        # Tam eşleşme tek başına kesin kanıttır.
        with patch("modules.app_identities.APPS", {"alpha": "a.exe", "alpah": "b.exe"}):
            self.assertEqual(understanding._verified_app_alias("alpha"), "alpha")

    def test_the_resolver_never_reads_raw_text_paths_or_installed_apps(self):
        # Çözümleme yalnız sabit tablodan okur: kurulu-uygulama taraması (makineye özgü) burada
        # ikinci bir kimlik otoritesi değildir.
        with patch("modules.system_control._match_installed",
                   side_effect=AssertionError("kurulu uygulama taraması çözümleme otoritesi değildir")):
            self.assertEqual(understanding._verified_app_alias("chromu"), "chrome")


class FileConversionTypoDecisionTests(_UnderstandingCase):
    def test_a_typoed_pdf_to_word_request_is_a_file_conversion_not_a_translation(self):
        result = self.understand("şu pdfyi worde cevir")
        self.assertIs(result.request_kind, RequestKind.CLARIFY)
        self.assertEqual(result.capability_hint, "files.read")
        self.assertTrue(result.needs_input)
        self.assertIn(FILE_TARGET_UNRESOLVED, result.ambiguities)
        self.assertNotIn("operation", result.arguments)

    def test_a_verified_reference_turns_the_request_into_one_convert_proposal(self):
        ref = file_ref("/data/rapor.pdf")
        result = self.understand("şu pdfyi worde cevir", [ref])
        self.assertIs(result.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(result.capability_hint, "files.read")
        self.assertEqual(result.arguments.get("operation"), FILE_CONVERT)
        self.assertEqual(result.arguments.get("format"), "docx")
        self.assertEqual(result.arguments.get("path"), "/data/rapor.pdf")
        self.assertNotIn("target", result.arguments)

    def test_the_correctly_spelled_conversion_forms_are_unchanged(self):
        ref = file_ref("/data/rapor.pdf")
        for text in ("rapor.pdf dosyasını word'e çevir", "rapor.pdf dosyasını Word'e dönüştür"):
            with self.subTest(text=text):
                result = self.understand(text, [ref])
                self.assertEqual(result.arguments.get("operation"), FILE_CONVERT, text)
                self.assertEqual(result.arguments.get("format"), "docx", text)
                self.assertEqual(result.arguments.get("path"), "/data/rapor.pdf", text)

    def test_a_language_target_keeps_the_translation_operation(self):
        ref = file_ref("/data/rapor.pdf")
        for text in ("rapor.pdf dosyasını İngilizceye çevir", "rapor.pdf dosyasını ingilizceye cevir"):
            with self.subTest(text=text):
                result = self.understand(text, [ref])
                self.assertEqual(result.arguments.get("operation"), "translate", text)
                self.assertEqual(result.arguments.get("target"), "İngilizce", text)
                self.assertNotIn("format", result.arguments, text)

    def test_other_file_operations_keep_their_owners(self):
        ref = file_ref("/data/rapor.docx")
        summarized = self.understand("rapor.docx dosyasını özetle", [ref])
        self.assertEqual(summarized.arguments.get("operation"), "summarize")
        analyzed = self.understand("rapor.docx dosyasını analiz et", [ref])
        self.assertEqual(analyzed.arguments.get("operation"), "analyze")


class UnrelatedCapabilityRegressionTests(_UnderstandingCase):
    def test_correctly_spelled_reminder_and_research_keep_their_capabilities(self):
        reminder = self.understand("bana yarın 9'da ilaç hatırlat")
        self.assertEqual(reminder.capability_hint, "reminder.propose")
        research = self.understand("son yapay zeka haberlerini araştır")
        self.assertEqual(research.capability_hint, "research.search")


class _TypoToleranceHarness(pr3b._RawDoorHarness):
    def with_document(self, name="rapor.pdf"):
        path = Path(self.temp.name) / name
        path.write_bytes(b"%PDF-1.4\n")
        rows = [{"path": str(path), "name": name, "ext": path.suffix}]
        original = brain_entry.build_candidates
        candidates = patch.object(
            brain_entry, "build_candidates",
            lambda **kw: original(**{**kw, "file_reader": lambda *, limit: rows[:limit]}),
        )
        candidates.start()
        self.addCleanup(candidates.stop)
        roots = patch.object(nxapi, "_roots", return_value=[Path(self.temp.name)])
        roots.start()
        self.addCleanup(roots.stop)
        return path


class ProductionChainEffectTests(_TypoToleranceHarness):
    def test_a_typoed_app_open_runs_the_verified_core_effect_exactly_once(self):
        entry, out, _handle, _feedback = self.turn("chromu acar misin")
        self.assertIs(entry.understanding.request_kind, RequestKind.CAPABILITY)
        self.ctx.system_control.open_application.assert_called_once_with("chrome")
        self.assertEqual(self.turn_texts, [], "typo turu legacy kapıya ikinci kez düşmemeli")
        self.assertIn("Chrome penceresi açık", out)

    def test_the_correctly_spelled_close_still_opens_the_existing_confirmation(self):
        # Yazım toleransı kapatma yolunu değiştirmez: doğru yazılmış kapatma tek onay sorusudur,
        # uygulama kapatılmaz ve legacy kapıya ikinci geçiş olmaz.
        entry, out, _handle, _feedback = self.turn("chrome'u kapat")
        self.assertEqual(entry.understanding.capability_hint, APP_CLOSE_CAPABILITY)
        self.assertEqual(self.ctx._session().pending_confirm, {"action": "close_app", "name": "chrome'u"})
        self.ctx.system_control.close_application.assert_not_called()
        self.assertEqual(self.turn_texts, [])
        self.assertIn("onaylıyor musun", out)

    def test_a_typoed_file_conversion_asks_the_file_question_without_an_effect(self):
        entry, out, _handle, _feedback = self.turn("şu pdfyi worde cevir")
        self.assertIs(entry.understanding.request_kind, RequestKind.CLARIFY)
        self.assertIn(FILE_TARGET_UNRESOLVED, entry.understanding.ambiguities)
        self.ctx.output.convert_document.assert_not_called()
        self.ctx.tr.translate.assert_not_called()
        self.assertIn("Hangi dosyayı", out)

    def test_a_typoed_file_conversion_with_one_verified_reference_converts_once(self):
        # "şu pdfyi" deiktik hedefi doğrulanmış referans üretmez (fail-closed soru); adı geçen
        # dosya çözümlenir ve dönüştürme tek etkiyle yürür.
        pdf = self.with_document()
        self.ctx.output.convert_document.return_value = {"path": str(pdf.with_suffix(".docx")), "note": ""}
        entry, out, _handle, _feedback = self.turn("rapor.pdf dosyasını worde cevir")
        self.assertIs(entry.understanding.request_kind, RequestKind.CAPABILITY)
        self.assertEqual(entry.understanding.arguments.get("format"), "docx")
        self.ctx.output.convert_document.assert_called_once()
        called_path, called_format = self.ctx.output.convert_document.call_args.args
        self.assertEqual(Path(called_path).resolve(), pdf.resolve())
        self.assertEqual(called_format, "docx")
        self.ctx.tr.translate.assert_not_called()
        self.assertEqual(self.turn_texts, [])
        self.assertIn("DOCX", out)

    def test_the_correctly_spelled_twins_keep_their_effects(self):
        self.turn("chrome'u açar mısın")
        self.ctx.system_control.open_application.assert_called_once_with("chrome'u")
        self.with_document()
        self.ctx.tr.translate_text_document = Mock(return_value="ÇEVİRİ")
        self.turn("rapor.pdf dosyasını İngilizceye çevir")
        self.ctx.tr.translate_text_document.assert_called_once()
        self.ctx.output.convert_document.assert_not_called()


class NegativeAndRegressionLocks(_TypoToleranceHarness):
    def test_a_mispelled_desktop_edit_still_never_reaches_the_goal_runner(self):
        _entry, out, _handle, _ = self.turn("masaüstünü duzenle")
        self.run_goal.assert_not_called()
        self.assertIn("işlem başlatılmadı", out)
        self.ctx.files.apply_organize.assert_not_called()

    def test_a_meta_question_about_the_typoed_sentence_starts_no_effect(self):
        _entry, _out, _handle, _ = self.turn('"chromu acar misin" ne demek?')
        self.ctx.system_control.open_application.assert_not_called()
        self.ctx.output.convert_document.assert_not_called()
        self.assertEqual(self.turn_texts, ["\"chromu acar misin\" ne demek?"])

    def test_a_multi_step_sentence_is_never_one_app_or_file_effect(self):
        _entry, _out, _handle, _ = self.turn("chromu acar misin ve worde cevir")
        self.ctx.system_control.open_application.assert_not_called()
        self.ctx.output.convert_document.assert_not_called()
        self.assertEqual(self.turn_texts, ["chromu acar misin ve worde cevir"])


if __name__ == "__main__":
    unittest.main()
