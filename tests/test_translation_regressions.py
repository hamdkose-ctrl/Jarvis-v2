"""Target routing, complete output and formula-safe spreadsheet translation."""
import json
import tempfile
import re
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from openpyxl import Workbook,load_workbook
from modules import translate as tr,router


class TranslationTests(unittest.TestCase):
    def test_turkish_spellings_and_source_language(self):
        for text in ('Türkçeye çevir','turkceye cevir','TÜRKÇEYE ÇEVİR','İngilizceden Türkçeye çevir'):
            self.assertEqual(tr.target_from_command(text),'Türkçe')
        self.assertEqual(tr.target_from_command('Türkçeden İngilizceye çevir'),'İngilizce')

    def test_language_translation_beats_file_format_words(self):
        ask=Mock(side_effect=AssertionError('model router must not run'))
        for text in ('Excel dosyasını Türkçeye çevir','PDF belgeyi turkceye cevir','Word Türkçeye çevir'):
            result=router.classify(text,ask)
            self.assertEqual(result['intent'],'doc_translate')
            self.assertEqual(result['args']['target'],'Türkçe')

    def test_file_button_uses_turkish_without_format_conversion(self):
        from modules.main_documents import _file_command
        from modules import nxapi
        runtime=SimpleNamespace(_FILE_CMD=re.compile(r'^((?:"[^"]{4,400}"\s+){1,10})(.+)$'),_tr_lower=str.lower,
            _IMG_EXT=('.png',),re=re,tr=tr,_translate_file=Mock(return_value='Türkçe sonuç'))
        source=Mock();source.is_file.return_value=True;source.__str__=Mock(return_value='example.docx')
        with patch.object(nxapi,'allowed',return_value=source):
            self.assertEqual(_file_command(runtime,'"example.docx" dosyasını Türkçeye çevir'),'Türkçe sonuç')
        runtime._translate_file.assert_called_once_with('example.docx','Türkçe')
        self.assertIn('Türkçeye',nxapi.ACTIONS['cevir_tr'])

    def test_long_translation_is_complete_and_target_preserved(self):
        text=('The pump must be inspected tomorrow.\n'*350)
        chunks=tr.split_text(text)
        self.assertEqual(''.join(chunks),text)
        self.assertTrue(all(len(c)<=3501 for c in chunks))
        with patch.object(tr,'ask',return_value='ÇEVİRİ: Pompa yarın kontrol edilmeli.\nNOTLAR: yok') as ask:
            result=tr.translate(text,'Türkçe')
            self.assertEqual(ask.call_count,len(chunks))
            self.assertEqual(result.count('Pompa'),len(chunks))
            for call in ask.call_args_list:
                self.assertIn('Hedef dil: Türkçe',call.args[0])
                self.assertEqual(call.kwargs['max_tokens'],8000)

    def test_incomplete_translation_is_rejected(self):
        with patch.object(tr,'ask',return_value='ÇEVİRİ: yarıda kaldı'):
            with self.assertRaisesRegex(ValueError,'tamamlandığı'):tr.translate('source','Türkçe')

    def test_long_operation_keeps_cancellation_and_user_scope(self):
        from modules import requests_state as state
        records={('alice','a'):{'state':'running','deadline':200},('bob','b'):{'state':'running','deadline':200}}
        with patch.object(state,'_records',records),patch.object(state.time,'monotonic',return_value=100),patch.object(state,'_save'):
            token=state._current.set(('alice','a'))
            try:
                state.allow_long_operation(400)
                self.assertEqual(records[('alice','a')]['deadline'],500)
                self.assertEqual(records[('bob','b')]['deadline'],200)
                records[('alice','a')]['state']='cancelled'
                with self.assertRaises(state.Cancelled):state.allow_long_operation(400)
                self.assertEqual(records[('alice','a')]['state'],'cancelled')
            finally:state._current.reset(token)

    def test_provider_failure_is_not_saved_as_translation(self):
        with patch.object(tr,'ask',side_effect=RuntimeError('provider failed')):
            with self.assertRaises(RuntimeError):tr.translate('source','Türkçe')

    def test_excel_preserves_numbers_formulas_and_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.xlsx';target=Path(folder)/'translated.xlsx'
            wb=Workbook();ws=wb.active;ws['A1']='English';ws['B1']=42;ws['C1']='=B1*2';wb.save(source)
            original=source.read_bytes()
            with patch.object(tr.output,'choose_excel_translation_path',return_value=str(target)),patch.object(tr,'ask',return_value=json.dumps([{'id':0,'translation':'=Türkçe metin'}])):
                tr.translate_excel_document(str(source),'Türkçe')
            translated=load_workbook(target)
            try:
                self.assertEqual(translated.active['A1'].value,'=Türkçe metin')
                self.assertEqual(translated.active['A1'].data_type,'s')
                self.assertEqual(translated.active['B1'].value,42)
                self.assertEqual(translated.active['C1'].data_type,'f')
            finally:translated.close()
            self.assertEqual(source.read_bytes(),original)

    def test_missing_excel_results_leave_output_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.xlsx';target=Path(folder)/'translated.xlsx'
            wb=Workbook();wb.active['A1']='English';wb.save(source);target.write_bytes(b'previous')
            with patch.object(tr.output,'choose_excel_translation_path',return_value=str(target)),patch.object(tr,'ask',return_value='[]'):
                with self.assertRaises(ValueError):tr.translate_excel_document(str(source),'Türkçe')
            self.assertEqual(target.read_bytes(),b'previous')

if __name__=='__main__':unittest.main()
