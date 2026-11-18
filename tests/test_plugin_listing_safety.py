"""Paket 1: eklenti listeleme kod çalıştırmaz; bozuk eklenti diğerlerini düşürmez.

Üretime tek noktasından bakılır: `listing()` yalnız kaynak kodunu okur, `handle()`
gerçek komut dispatch'inde modülü yürütür. Yan etme (dosya yazma) tek kanıttır.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import plugins

GOOD = ('NAME = "Saat"\nDESCRIPTION = "Saati söyler"\n\n\n'
        'def handle(cmd_lower, command):\n    return "saat" if "saat" in cmd_lower else None\n')
SIDE_EFFECT = ('import pathlib\n'
               'pathlib.Path(%r).write_text("çalıştı")\n'
               'NAME = "İzleyen"\n\n\n'
               'def handle(cmd_lower, command):\n    return None\n')
BROKEN = 'def handle(:\n    ...\n'
NO_HANDLE = 'NAME = "Sessiz"\n'
COMPUTED = ('import os\nNAME = os.getcwd()\n\n\ndef handle(cmd_lower, command):\n    return None\n')


class PluginListingSafety(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.marker = self.folder / 'PLUGIN-CODE-EXECUTED.txt'
        for target, value in (('DIR', self.folder), ('_loaded', {})):
            p = patch.object(plugins, target, value)
            p.start()
            self.addCleanup(p.stop)

    def write(self, name, body):
        (self.folder / name).write_text(body, encoding='utf-8')

    def entry(self, name):
        return [item for item in plugins.listing() if item['file'] == name][0]

    def test_listing_never_executes_plugin_code(self):
        self.write('saat.py', GOOD)
        self.write('izleyen.py', SIDE_EFFECT % str(self.marker))
        self.assertEqual([item['file'] for item in plugins.listing()], ['izleyen.py', 'saat.py'])
        self.assertFalse(self.marker.exists())

    def test_listing_reads_the_declared_metadata_from_the_source(self):
        self.write('saat.py', GOOD)
        self.assertEqual(plugins.listing(), [{'file': 'saat.py', 'name': 'Saat',
                                             'description': 'Saati söyler', 'ok': True, 'error': ''}])

    def test_a_broken_plugin_does_not_drop_the_others(self):
        self.write('saat.py', GOOD)
        self.write('bozuk.py', BROKEN)
        self.assertTrue(self.entry('saat.py')['ok'])
        bozuk = self.entry('bozuk.py')
        self.assertFalse(bozuk['ok'])
        self.assertIn('SyntaxError', bozuk['error'])

    def test_a_plugin_without_handle_is_reported_not_ok(self):
        self.write('sessiz.py', NO_HANDLE)
        sessiz = self.entry('sessiz.py')
        self.assertFalse(sessiz['ok'])
        self.assertIn('handle', sessiz['error'])

    def test_a_computed_name_falls_back_to_the_file_stem_without_running_it(self):
        self.write('hesap.py', COMPUTED)
        hesap = self.entry('hesap.py')
        self.assertEqual(hesap['name'], 'hesap')
        self.assertTrue(hesap['ok'])

    def test_dispatch_is_the_only_path_that_runs_plugin_code(self):
        self.write('saat.py', GOOD)
        self.write('izleyen.py', SIDE_EFFECT % str(self.marker))
        plugins.listing()
        self.assertFalse(self.marker.exists())
        self.assertEqual(plugins.handle('Saat kaç', 'saat kaç'), 'saat')
        self.assertTrue(self.marker.is_file())


if __name__ == '__main__':
    unittest.main()
