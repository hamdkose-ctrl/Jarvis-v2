"""Modelsiz finans alarm komutları; kullanıcı deposu geçici dizinde."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from modules import finance_alert_store as store
from modules import finance_alert_commands as commands

class FinanceAlarmCommandsTests(unittest.TestCase):
    def setUp(self):
        td=tempfile.TemporaryDirectory();self.addCleanup(td.cleanup)
        self.enterContext(patch.object(store,'_ROOT',Path(td.name)/'rules'))
    def test_add_list_delete_and_owner_separation(self):
        self.assertIn('Alarm',commands.handle('alice',"USD 33 TL'nin üstüne çıkarsa haber ver"))
        self.assertEqual(store.list_rules('alice')[0]['op'],'above')
        self.assertEqual(store.list_rules('bob'),[])
        self.assertIn('USD',commands.handle('alice','alarmlarım'))
        self.assertIn('silindi',commands.handle('alice','alarmı sil 1'))
        self.assertEqual(store.list_rules('alice'),[])
    def test_variants_duplicate_and_invalid_threshold(self):
        for name,kind,symbol in [('dolar','doviz','USD'),('BTC','kripto','BTC'),('gram altın','altin','GRAM'),('THYAO hissesi','hisse','THYAO')]:
            with self.subTest(name=name):
                commands.handle('alice',name+" 33,50 TL altına inerse haber ver")
                row=store.list_rules('alice')[-1]
                self.assertEqual((row['kind'],row['symbol'],row['op'],row['value']),(kind,symbol,'below',33.5))
        commands.handle('alice',"dolar 33,50 TL altına inerse haber ver")
        self.assertEqual(len(store.list_rules('alice')),4)
        store.add_rule('alice',{'kind':'doviz','symbol':'EUR','op':'pct_up','value':5})
        listing=commands.handle('alice','alarmlarım')
        self.assertNotIn('pct_up',listing)
        self.assertIn('%5',listing)
        self.assertNotIn('above',listing)
        self.assertIn('33,5 TL',listing)
        self.assertIn('geçersiz',commands.handle('alice','USD 0 TL üstüne çıkarsa haber ver').lower())
    def test_unrelated_commands_not_captured_or_written(self):
        for text in ['dolar kaç lira','alarm kur yarın 7','alarmları kapat','USD al','USD sat','haber ver']:
            self.assertIsNone(commands.handle('alice',text),text)
        self.assertEqual(store.list_rules('alice'),[])
    def test_invalid_delete_and_path(self):
        self.assertIn('yok',commands.handle('alice','alarmı sil 99'))
        with self.assertRaises(ValueError):commands.handle('../bob','alarmlarım')

    def test_engine_entry_only_handles_its_own_commands(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from modules import engine_tools
        runtime=SimpleNamespace(profile=SimpleNamespace(slug='alice'),plugins=SimpleNamespace(handle=Mock(return_value='existing route')))
        result=engine_tools._extra_commands(runtime,"USD 33 TL üstüne çıkarsa haber ver",'')
        self.assertIn('Alarm kaydedildi',result)
        runtime.plugins.handle.assert_not_called()
        del runtime.profile
        self.assertEqual(engine_tools._extra_commands(runtime,'başka komut','başka komut'),'existing route')
        runtime.plugins.handle.assert_called_once()
