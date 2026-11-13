"""Belge masası: belgeden tablo, Excel/CSV birleştirme-gruplama, çıktı dosyası ve yeni sürüm."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from modules import workbench


def _xlsx(path, rows):
    from openpyxl import Workbook
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    wb.save(path)


def _read_xlsx(path):
    from openpyxl import load_workbook
    wb = load_workbook(path)
    try:
        return {ws.title: [[c.value for c in r] for r in ws.iter_rows()] for ws in wb.worksheets}, wb
    finally:
        wb.close()


class NumberAndTextTests(unittest.TestCase):
    def test_turkish_and_english_numbers(self):
        cases = {"1.234,56": 1234.56, "1.234": 1234, "12,5": 12.5, "12.5": 12.5, "1,234,567": 1234567,
                 "1.234.567": 1234567, "0.125": 0.125, "250 TL": 250, "-3": -3, "abc": None, "": None, "12.": None, 7: 7}
        for text, expected in cases.items():
            self.assertEqual(workbench.tr_number(text), expected, text)

    def test_units_and_turkish_case(self):
        self.assertEqual(workbench.norm_text(" Ad. "), "adet")
        self.assertEqual(workbench.norm_text("MT"), "m")
        self.assertEqual(workbench.norm_text("IŞIK  Vİda"), "ışık vida")

    def test_intent_needs_a_table_request(self):
        self.assertTrue(workbench.wants("önemli yerleri excelde bir tablo yap"))
        self.assertTrue(workbench.wants("iki şartnameyi karşılaştır"))
        self.assertFalse(workbench.wants("tablodaki değer ne anlama geliyor"))
        self.assertFalse(workbench.wants("bu iki pdf'i birleştir", ["a.pdf", "b.pdf"]))
        self.assertTrue(workbench.wants("bunları birleştir", ["a.xlsx", "b.csv"]))
        self.assertEqual(workbench.output_ext("word'de tablo yap"), ".docx")
        self.assertEqual(workbench.output_ext("pdf olarak tablo ver"), ".pdf")
        self.assertEqual(workbench.output_ext("tablo yap"), ".xlsx")


class TableOperationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        _xlsx(self.tmp / "a.xlsx", [["Malzeme", "Birim", "Tutar"], ["Vida M8", "ad", "1.250,50"], ["Kablo", "mt", 100],
                                    ["Vida M8", "Adet", 10], [None, None, None], ["Vida M 8", "adet", 5]])
        (self.tmp / "b.csv").write_text("malzeme;birim;tutar\nKablo;m;50\nkablo;M;50\n", encoding="utf-8")

    def tables(self):
        return [(p, *workbench.load_table(self.tmp / p)) for p in ("a.xlsx", "b.csv")]

    def run_both(self, steps):
        with_pandas = workbench.run_steps(steps, self.tables())
        with patch.object(workbench, "_pandas", return_value=None):
            plain = workbench.run_steps(steps, self.tables())
        return with_pandas, plain

    def test_load_table_skips_blank_rows_and_reads_csv(self):
        header, rows = workbench.load_table(self.tmp / "a.xlsx")
        self.assertEqual(header, ["Malzeme", "Birim", "Tutar"])
        self.assertEqual(len(rows), 4)
        header, rows = workbench.load_table(self.tmp / "b.csv")
        self.assertEqual(rows[0], {"malzeme": "Kablo", "birim": "m", "tutar": "50"})

    def test_merge_maps_same_headers_and_records_source(self):
        header, rows = workbench.op_merge(self.tables())
        self.assertEqual(header, ["Malzeme", "Birim", "Tutar", "Kaynak dosya"])
        self.assertEqual(rows[-1], {"Malzeme": "kablo", "Birim": "M", "Tutar": "50", "Kaynak dosya": "b.csv"})

    def test_group_sum_is_computed_by_code_with_and_without_pandas(self):
        for header, rows in self.run_both([{"op": "merge"}, {"op": "group_sum", "by": ["malzeme", "birim"], "sum": ["tutar"]}]):
            self.assertEqual(header, ["Malzeme", "Birim", "Tutar"])
            self.assertEqual(rows, [{"Malzeme": "Vida M8", "Birim": "ad", "Tutar": 1260.5},
                                    {"Malzeme": "Kablo", "Birim": "mt", "Tutar": 200},
                                    {"Malzeme": "Vida M 8", "Birim": "adet", "Tutar": 5}])

    def test_dedupe_uses_normalized_values(self):
        for header, rows in self.run_both([{"op": "merge"}, {"op": "dedupe", "columns": ["Malzeme", "Birim", "Tutar"]}]):
            self.assertEqual([r["Malzeme"] for r in rows], ["Vida M8", "Kablo", "Vida M8", "Vida M 8", "Kablo"])

    def test_join_columns_and_unknown_column(self):
        header, rows = workbench.op_join_columns(*workbench.load_table(self.tmp / "a.xlsx"), ["Malzeme", "Birim"], "Kalem", " / ")
        self.assertEqual(rows[0]["Kalem"], "Vida M8 / ad")
        with self.assertRaisesRegex(ValueError, "Fiyat"):
            workbench.op_group_sum(header, rows, ["Malzeme"], ["Fiyat"])

    def test_text_in_sum_column_is_refused(self):
        header, rows = workbench.load_table(self.tmp / "a.xlsx")
        rows[0]["Tutar"] = "yok"
        with self.assertRaisesRegex(ValueError, "sayı olmayan"):
            workbench.op_group_sum(header, rows, ["Malzeme"], ["Tutar"])

    def test_similar_items_are_listed_not_merged(self):
        pairs = workbench.similar_items(["Malzeme"], [{"Malzeme": "Vida M8"}, {"Malzeme": "Vida M 8"}, {"Malzeme": "Kablo"}])
        self.assertEqual(pairs, [["Malzeme", "Vida M8", "Vida M 8"]])

    def test_plan_rejects_operations_outside_the_whitelist(self):
        with patch.object(workbench.llm, "ask", return_value='{"steps":[{"op":"eval","code":"x"}]}'):
            with self.assertRaisesRegex(ValueError, "Desteklenmeyen"):
                workbench.plan_steps("topla", self.tables())
        with patch.object(workbench.llm, "ask", return_value='{"steps":[{"op":"dedupe"}]}'):
            self.assertEqual(workbench.plan_steps("tekrar edenleri sil", self.tables())[0], {"op": "merge"})

    def test_handle_writes_a_new_excel_with_preview_and_check_sheet(self):
        plan = json.dumps({"steps": [{"op": "merge"}, {"op": "group_sum", "by": ["Malzeme"], "sum": ["Tutar"]}]})
        before = (self.tmp / "a.xlsx").read_bytes()
        with patch.object(workbench.llm, "ask", return_value=plan):
            answer = workbench.handle("hamdi", [str(self.tmp / "a.xlsx"), str(self.tmp / "b.csv")], "malzemeye göre topla")
        out = self.tmp / "a_grup_toplam.xlsx"
        self.assertIn(str(out), answer)
        self.assertIn("| Vida M8 | 1260.5 |", answer)
        self.assertIn("Kontrol et", answer)
        self.assertEqual((self.tmp / "a.xlsx").read_bytes(), before)
        sheets, _ = _read_xlsx(out)
        self.assertEqual(sheets["Sonuç"][1], ["Vida M8", 1260.5])
        self.assertEqual(sheets["Kontrol et"][1], ["Malzeme", "Vida M8", "Vida M 8"])
        with patch.object(workbench.llm, "ask", return_value=plan):
            workbench.handle("hamdi", [str(self.tmp / "a.xlsx"), str(self.tmp / "b.csv")], "malzemeye göre topla")
        self.assertTrue((self.tmp / "a_grup_toplam_2.xlsx").exists())


class DocumentTableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pdf = self.tmp / "sartname.pdf"
        self.pdf.write_bytes(b"%PDF-1.4")
        self.text = "Teslim süresi 45 gündür.\fGeçici teminat %3 oranındadır. Ceza günlük 1.500 TL."
        workbench._LAST.clear()

    def answer(self, *rows):
        return json.dumps({"rows": [{"cells": list(r[:-1]), "kaynak": r[-1]} for r in rows]}, ensure_ascii=False)

    def test_rows_are_checked_against_the_source_and_formulas_stay_text(self):
        reply = self.answer(["Teslim", "Süre", "45 gün", "sayfa 1"], ["Ceza", "Günlük ceza", "2.500 TL", "sayfa 2"],
                            ["=HYPERLINK(\"x\")", "Kötü", "", "sayfa 2"])
        with patch.object(workbench.docs, "read_document", return_value=self.text) as read, \
             patch.object(workbench.llm, "ask", return_value=reply) as ask:
            answer = workbench.handle("hamdi", [str(self.pdf)], "önemli yerleri excelde tablo yap")
        read.assert_called_once_with(str(self.pdf), keep_pages=True, cache=True)
        self.assertEqual(ask.call_count, 1)
        self.assertIn("[sayfa 2]", ask.call_args.args[0])
        self.assertIn("1 satırdaki", answer)
        sheets, wb = _read_xlsx(self.tmp / "sartname_tablo.xlsx")
        rows = sheets["Tablo"]
        self.assertEqual(rows[0], ["Konu", "Önemli husus", "Değer / süre / tutar", "Kaynak", "Kontrol"])
        self.assertIsNone(rows[1][4])
        self.assertIn("2.500", rows[2][4])
        self.assertEqual(wb["Tablo"]["A4"].data_type, "s")

    def test_custom_columns_word_output_and_followup_version(self):
        reply = self.answer(["Teslim süresi", "45 gün", "sayfa 1"])
        with patch.object(workbench.docs, "read_document", return_value=self.text), \
             patch.object(workbench.llm, "ask", return_value=reply) as ask, \
             patch("modules.nxapi.allowed",
                   side_effect=lambda path: self.pdf if path == str(self.pdf) else None):
            workbench.handle("hamdi", [str(self.pdf)], "tablo yap sütunlar: Madde, Değer")
            self.assertIn('["Madde", "Değer"]', ask.call_args.args[0])
            self.assertFalse(hasattr(workbench, "followup"))
            self.assertIsNone(workbench.snapshot_digest("ebru"))
            digest = workbench.snapshot_digest("hamdi")
            self.assertEqual(len(digest), 64)
            answer = workbench.followup_typed(
                "hamdi", "tabloyu word olarak ver, açıklama sütunu ekle",
                expected_digest=digest, fmt=".docx")
        self.assertTrue((self.tmp / "sartname_tablo.xlsx").exists())
        self.assertIn(str(self.tmp / "sartname_tablo.docx"), answer)
        self.assertIn("Ek istek: tabloyu word", ask.call_args.args[0])
        current_digest = workbench.snapshot_digest("hamdi")
        workbench._LAST["hamdi"]["at"] -= workbench.FOLLOW_SECONDS + 1
        self.assertIsNone(workbench.snapshot_digest("hamdi"))
        self.assertIn(
            "süresi doldu",
            workbench.followup_typed(
                "hamdi", "tutar sütunu ekle", expected_digest=current_digest))

    def test_long_document_is_capped_with_a_note(self):
        long_text = "\f".join(f"Madde {i}: " + "x" * 11000 for i in range(20))
        with patch.object(workbench.docs, "read_document", return_value=long_text), \
             patch.object(workbench.llm, "ask", return_value=self.answer(["a", "b", "c", "sayfa 1"])) as ask:
            answer = workbench.handle("hamdi", [str(self.pdf)], "önemli yerleri tablo yap")
        self.assertEqual(ask.call_count, workbench.MAX_CALLS)
        self.assertIn("yalnız ilk 12 bölüm", answer)

    def test_scanned_or_empty_document_and_nothing_found(self):
        with patch.object(workbench.docs, "read_document", return_value="  "):
            with self.assertRaisesRegex(ValueError, "taranmış"):
                workbench.handle("hamdi", [str(self.pdf)], "tablo yap")
        with patch.object(workbench.docs, "read_document", return_value=self.text), \
             patch.object(workbench.llm, "ask", return_value="cevap yok"):
            with self.assertRaisesRegex(ValueError, "bulamadım"):
                workbench.handle("hamdi", [str(self.pdf)], "tablo yap")


class WorkbenchPhysicalClaimTests(unittest.TestCase):
    def setUp(self):
        from modules import file_resource_guard
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        patch_root = patch.object(
            file_resource_guard, '_FILE_EFFECT_CLAIM_ROOT',
            self.folder / 'same-os-account' / 'claims',
        )
        patch_root.start()
        self.addCleanup(patch_root.stop)

    def test_preexisting_workbook_is_never_replaced_after_unique_name_selection(self):
        output = self.folder / 'valuable.xlsx'
        output.write_bytes(b'original user bytes')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            workbench.write_output(output, 'Claimed', [('Sheet1', [['a'], ['b']])])
        self.assertEqual(output.read_bytes(), b'original user bytes')
        self.assertEqual(list(self.folder.glob('.jarvis-table-*')), [])

    def test_competing_physical_claim_blocks_workbook_write_before_conversion(self):
        from modules import file_resource_guard, resource_leases, conversion
        output = self.folder / 'claimed.xlsx'
        with file_resource_guard.claim_paths(output):
            with patch.object(conversion, 'write_content') as writer:
                with self.assertRaises(resource_leases.LeaseConflict):
                    workbench.write_output(output, 'Claimed', [('Sheet1', [['a']])])
                writer.assert_not_called()
        self.assertFalse(output.exists())

    def test_workbook_is_published_atomically_without_replace(self):
        from modules import file_resource_guard, resource_leases
        output = self.folder / 'fresh.xlsx'
        workbench.write_output(output, 'Ready', [('Sheet1', [['header'], ['value']])])
        self.assertTrue(output.exists())
        from openpyxl import load_workbook
        workbook = load_workbook(output)
        try:
            self.assertEqual(workbook.active['A2'].value, 'value')
        finally:
            workbook.close()
        with self.assertRaises(resource_leases.LeaseConflict):
            workbench.write_output(output, 'Overwrite', [('Sheet1', [['new']])])
        workbook = load_workbook(output)
        try:
            self.assertEqual(workbook.active['A2'].value, 'value')
        finally:
            workbook.close()


class FileCommandTests(unittest.TestCase):
    def runtime(self):
        import re
        return SimpleNamespace(_FILE_CMD=re.compile(r'^((?:"[^"]{4,400}"\s+){1,10})(.+)$'), _tr_lower=str.lower, re=re,
                               _IMG_EXT=(".png",), profile=SimpleNamespace(slug="hamdi"),
                               tr=SimpleNamespace(target_from_command=lambda a: None))

    def test_several_files_go_to_the_workbench_together(self):
        from modules import main_documents, nxapi
        tmp = Path(tempfile.mkdtemp())
        a, b = tmp / "a.pdf", tmp / "b.docx"
        a.write_bytes(b"x")
        b.write_bytes(b"x")
        with patch.object(nxapi, "allowed", side_effect=lambda p: Path(p)), \
             patch.object(workbench, "handle", return_value="Hazır") as handle:
            self.assertEqual(main_documents._file_command(self.runtime(), f'"{a}" "{b}" iki şartnameyi karşılaştır'), "Hazır")
        handle.assert_called_once_with("hamdi", [str(a), str(b)], "iki şartnameyi karşılaştır")

    def test_quoted_path_ui_does_not_turn_negative_words_into_effects(self):
        from modules import main_documents, nxapi, filesend
        runtime = self.runtime()
        for command in (
            '"C:/Docs/report.pdf" telefonuma gönderme',
            '"C:/Docs/report.pdf" telefonuma gönder, ama silme',
            '"C:/Docs/report.pdf" dosyasını dönüştürme',
            '"C:/Docs/report.pdf" dosyasını görselleştirme',
            '"C:/Docs/report.pdf" telefonuma gönder?',
            '"C:/Docs/report.pdf" telefonuma gönder ne demek?',
        ):
            with self.subTest(command=command), \
                 patch.object(nxapi, "allowed",
                              side_effect=AssertionError("untrusted file path opened")) as allowed, \
                 patch.object(filesend, "send",
                              side_effect=AssertionError("negative send executed")) as send:
                self.assertFalse(
                    main_documents.explicit_ui_file_command(command, runtime._FILE_CMD))
                self.assertIsNone(main_documents._file_command(runtime, command))
                allowed.assert_not_called()
                send.assert_not_called()

    def test_quoted_path_ui_accepts_only_known_positive_whole_actions(self):
        from modules import main_documents
        runtime = self.runtime()
        for action in ("özetle", "yerel OCR ile oku", "dosyasını Türkçeye çevir",
                       "dosyasını görselleştir", "pdf'e dönüştür", "telefonuma gönder",
                       "iki şartnameyi karşılaştır", "tablo yap"):
            with self.subTest(action=action):
                self.assertTrue(main_documents.explicit_ui_file_command(
                    f'"C:/Docs/report.pdf" {action}', runtime._FILE_CMD))

    def test_disallowed_file_and_followup_without_paths(self):
        from modules import main_documents, nxapi
        with patch.object(nxapi, "allowed", return_value=None):
            self.assertIn("erişemiyorum", main_documents._file_command(self.runtime(), '"C:/gizli/a.pdf" "C:/x/b.pdf" tablo yap'))
        # The raw language-followup adapter was physically retired.
        self.assertFalse(hasattr(workbench, "followup"))
        self.assertIsNone(main_documents._file_command(self.runtime(), "merhaba"))


if __name__ == "__main__":
    unittest.main()
