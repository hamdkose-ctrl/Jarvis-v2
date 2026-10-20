"""Dosya ve Hoca sözleşmeleri mevcut girişleri tanımlar; işlem başlatmaz."""
import inspect
import json
import unittest
from unittest.mock import patch
from modules import file_ops, hoca, requests_state, tool_contract
from modules import tool_files, tool_hoca


class FilesHocaContractsTests(unittest.TestCase):
    def test_valid_discoverable_contracts_match_existing_entries(self):
        loaded = tool_contract.load_all()
        for module, existing in ((tool_files, file_ops), (tool_hoca, hoca)):
            with self.subTest(tool=module.CONTRACT['id']):
                self.assertEqual(tool_contract.validate(module.CONTRACT), [])
                self.assertIn(module.CONTRACT['id'], loaded)
                view = tool_contract.describe(module.CONTRACT)
                json.dumps(view)
                for action in view['actions']:
                    self.assertIn(action['class'], ('read', 'local_reversible'))
                    self.assertTrue({'id', 'name', 'desc', 'class', 'params'} <= set(action))
                    entry = getattr(existing, action['id'])
                    self.assertTrue(callable(entry))
                    self.assertTrue(set(action['params']) <= set(inspect.signature(entry).parameters))

    def test_status_and_cancel_do_not_start_or_alter_existing_work(self):
        with patch.object(file_ops, 'handle', side_effect=AssertionError('Dosya işlemi yasak')), \
                patch.object(file_ops, 'undo', side_effect=AssertionError('Geri alma yasak')), \
                patch.object(hoca, 'handle', side_effect=AssertionError('Ders başlatma yasak')), \
                patch.object(hoca, 'stop', side_effect=AssertionError('Mevcut dersi değiştirme yasak')), \
                patch.object(requests_state, 'cancel') as cancel, \
                patch('modules.llm.ask', side_effect=AssertionError('Model yasak')):
            for module in (tool_files, tool_hoca):
                self.assertEqual(module.status()['state'], 'ready')
                self.assertEqual(module.cancel()['cancelled'], False)
            cancel.assert_not_called()

    def test_missing_entry_is_error_not_false_readiness(self):
        for module, existing in ((tool_files, file_ops), (tool_hoca, hoca)):
            with patch.object(existing, 'handle', None), patch.object(module, '_record_failure') as record:
                self.assertEqual(module.status()['state'], 'error')
                record.assert_called_once()


if __name__ == '__main__':
    unittest.main()
