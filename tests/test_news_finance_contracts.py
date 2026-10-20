"""Haber/finans keşfi salt okunur mevcut girişleri tanımlar."""
import inspect
import json
import unittest
from unittest.mock import patch
from modules import domain_tools, finance, requests_state, tool_contract
from modules import tool_news, tool_finance


class NewsFinanceContractsTests(unittest.TestCase):
    def test_valid_discoverable_contracts_match_existing_entry_points(self):
        loaded = tool_contract.load_all()
        for module, existing in ((tool_news, domain_tools), (tool_finance, finance)):
            with self.subTest(tool=module.CONTRACT['id']):
                self.assertEqual(tool_contract.validate(module.CONTRACT), [])
                self.assertIn(module.CONTRACT['id'], loaded)
                json.dumps(tool_contract.describe(module.CONTRACT))
                for action in module.CONTRACT['actions']:
                    self.assertEqual(action['class'], 'read')
                    self.assertTrue({'id', 'name', 'desc', 'class', 'params'} <= set(action))
                    entry = getattr(existing, action['id'])
                    self.assertTrue(callable(entry))
                    self.assertTrue(set(action['params']) <= set(inspect.signature(entry).parameters))

    def test_status_does_not_fetch_prices_news_or_call_models(self):
        with patch.object(domain_tools, 'headlines', side_effect=AssertionError('Canlı haber yasak')), \
                patch.object(finance, 'answer', side_effect=AssertionError('Canlı finans yasak')), \
                patch('modules.llm.ask', side_effect=AssertionError('Model yasak')):
            for module in (tool_news, tool_finance):
                self.assertEqual(module.status()['state'], 'ready')

    def test_cancel_does_not_cancel_another_request(self):
        with patch.object(requests_state, 'cancel') as cancel:
            for module in (tool_news, tool_finance):
                self.assertEqual(module.cancel()['cancelled'], False)
            cancel.assert_not_called()

    def test_missing_entry_reports_error_and_records_failure(self):
        for module, existing, entry in ((tool_news, domain_tools, 'headlines'), (tool_finance, finance, 'answer')):
            with patch.object(existing, entry, None), patch.object(module, '_record_failure') as record:
                self.assertEqual(module.status()['state'], 'error')
                record.assert_called_once()


if __name__ == '__main__':
    unittest.main()
