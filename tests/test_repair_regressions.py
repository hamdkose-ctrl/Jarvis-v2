import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from modules import diagnostics, privacy, developer, nxapi, conversion
from modules.document_conversion import Content
from modules.exam_conversion import Question

class RepairTests(unittest.TestCase):
    def test_provider_secrets_and_url_credentials_are_masked(self):
        secrets=['gsk_'+'a'*45,'github_pat_'+'b'*45,'gho_'+'c'*40]
        reason=diagnostics.safe_reason(ValueError(' '.join(secrets)+' https://user:secret@example.com/path?t=token#fragment'))
        for secret in secrets+['user:secret','t=token','fragment']:self.assertNotIn(secret,reason)
        self.assertIn('example.com/path',reason)

    def test_failed_windows_protection_never_saves_base64(self):
        with patch.object(privacy.sys,'platform','win32'),patch.object(privacy,'_dpapi',side_effect=OSError('failure')):
            with self.assertRaises(OSError):privacy.protect('fixture-only')

    def test_command_cannot_enable_authenticated_development(self):
        with tempfile.TemporaryDirectory() as td,patch.object(developer,'STORE',Path(td)),patch.object(developer,'_AUTH',{'alice'}):
            result=developer.handle('alice','geliştirme modunu aç')
            self.assertIn('arayüz düğmesinden',result)
            self.assertFalse(developer.status('alice')['enabled'])

    def test_file_refresh_really_bypasses_cache(self):
        # Önbellek boşaltmanın üretim yolu yoktur: arayüz "yenile"yi list_files(force=True)
        # ile yapar. Test soğuk önbelleği kendi içinde kurar, bitirince önceki kopyayı geri koyar.
        with tempfile.TemporaryDirectory() as td,patch.object(nxapi,'FILES_DIR',Path(td)),patch.object(nxapi,'_scan_files',return_value=[]) as scan:
            saved=dict(nxapi._FILE_CACHE)
            with nxapi._FILE_CACHE_LOCK:
                nxapi._FILE_CACHE.update(rows=None, ts=0.0)
            try:
                nxapi.list_files();self.assertEqual(scan.call_count,1)
                nxapi.list_files();self.assertEqual(scan.call_count,1)
                nxapi.list_files(force=True);self.assertEqual(scan.call_count,2)
            finally:
                with nxapi._FILE_CACHE_LOCK:
                    nxapi._FILE_CACHE.update(saved)

    def test_excel_has_editable_answer_and_no_fabricated_key(self):
        from openpyxl import load_workbook
        content=Content('Sorular',questions=[Question('Biyoloji','100',1,1,'Hücre nedir?',{'A':'Bir yapı','B':'=HYPERLINK("x")'},'A'),Question('Biyoloji','100',2,1,'İkinci soru?',{},'')])
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'test.xlsx';conversion.write_content(content,path)
            wb=load_workbook(path)
            try:
                self.assertEqual(wb.sheetnames[0],'Çalışma')
                self.assertIn('Anahtar yok',wb['Çalışma']['F3'].value)
                self.assertEqual(wb['Sorular']['F2'].data_type,'s')
                self.assertIn('CalismaSorulari',wb['Çalışma'].tables)
            finally:wb.close()

    def test_development_exit_preserves_disabled_microphone(self):
        from web_chat import WebChat
        with tempfile.TemporaryDirectory() as td,patch.object(developer,'STORE',Path(td)),patch.object(developer,'_AUTH',{'alice'}):
            flags={'mic':False};runtime=SimpleNamespace(engine=SimpleNamespace(flags=flags),_p=lambda:SimpleNamespace(slug='alice'),_set_mic=lambda on:flags.update(mic=on))
            bridge=WebChat();bridge._runtime=runtime
            bridge.development_enable();bridge.development_enable();bridge.development_disable()
            self.assertFalse(flags['mic'])
