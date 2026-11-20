"""Envanter köprüsü: web_files API projeksiyon sözleşmesi (arayüz bağımsız).

Arayüzde köklü yeniden tasarım beklenirken düğme taşınabilir; kalıcı sözleşme
`file_inventory_run` / `file_inventory_excel` API adları ve dönüş biçimidir.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _report(folder):
    from modules.file_inventory import InventoryReport
    return InventoryReport(folder=folder, total_files=3, by_extension={'.txt': 3},
                           duplicate_groups=[[{'name': 'a.txt', 'path': 'x/a.txt', 'size': 1, 'ext': 'txt'}]],
                           similar_name_groups=[],
                           empty_file_candidates=[{'name': 'b.txt', 'path': 'x/b.txt', 'size': 0, 'ext': 'txt'}],
                           old_file_candidates=[],
                           temp_name_candidates=[],
                           truncated=False)


class InventoryBridgeTests(unittest.TestCase):
    def test_run_projection_and_excel_receipt(self):
        import web_files
        wf = web_files.WebFiles()
        with tempfile.TemporaryDirectory() as td, \
                patch('modules.file_inventory.build_report', side_effect=lambda folder: _report(folder)), \
                patch('modules.file_inventory.export_xlsx',
                      return_value=str(Path(td) / 'Klasor_Envanteri.xlsx')):
            out = wf.file_inventory_run(td)
            self.assertEqual(out['folder'], td)
            self.assertEqual(out['total_files'], 3)
            self.assertEqual(out['by_extension'], {'.txt': 3})
            self.assertEqual(out['duplicate_groups'][0][0]['name'], 'a.txt')
            self.assertEqual(out['empty'][0]['path'], 'x/b.txt')
            self.assertFalse(out['truncated'])
            exc = wf.file_inventory_excel(td)
            self.assertTrue(exc['path'].endswith('.xlsx'))
            self.assertEqual(exc['duplicates'], 1)
            self.assertEqual(exc['similar'], 0)
            self.assertEqual(exc['empty'], 1)


if __name__ == '__main__':
    unittest.main()
