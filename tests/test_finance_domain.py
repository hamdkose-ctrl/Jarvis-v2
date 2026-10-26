"""Finance domain sözleşmesi: dallar, sınır ve göç planı statik olarak tutarlı kalır."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import finance_domain


class FinanceDomainContractTests(unittest.TestCase):
    def test_contract_is_internally_consistent(self):
        self.assertEqual(finance_domain.validate(), [])
        self.assertEqual(set(finance_domain.BRANCHES), {'data', 'alarm', 'analysis', 'source_verification'})

    def test_current_repository_respects_finance_boundary(self):
        self.assertEqual(finance_domain.check(), [])

    def test_no_branch_opens_money_message_or_publish(self):
        for name, branch in finance_domain.BRANCHES.items():
            with self.subTest(branch=name):
                self.assertNotIn(branch['permission_class'], {'money_credential', 'message_out', 'publish', 'external_write'})
                self.assertIn(branch['effect_policy'], {'read_only', 'local_reversible'})

    def test_route_closes_money_and_account_and_rejects_unknown(self):
        for kind in ('money_effect', 'account_read'):
            with self.assertRaises(PermissionError):
                finance_domain.route(kind)
        with self.assertRaises(ValueError):
            finance_domain.route('trade')
        self.assertEqual(finance_domain.route('send_to_person')['owner'], 'communication')
        self.assertEqual(finance_domain.route('alarm_delivery')['owner'], 'communication')
        self.assertEqual(finance_domain.route('market_data')['permission_class'], 'read')

    def test_validate_flags_opened_money_path(self):
        boundary = dict(finance_domain.BOUNDARY, money_effect={'owner': 'finance', 'permission_class': 'money_credential', 'state': 'open'})
        with patch.object(finance_domain, 'BOUNDARY', boundary):
            self.assertTrue(finance_domain.validate())

    def test_branch_of_maps_owned_modules_only(self):
        self.assertEqual(finance_domain.branch_of('modules/finance.py'), 'data')
        self.assertEqual(finance_domain.branch_of('modules/finance_watchlist.py'), 'alarm')
        self.assertIsNone(finance_domain.branch_of('modules/watcher.py'))

    def _tree(self, td, replace=None):
        root = Path(td)
        for rel in finance_domain.owned_modules():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('', encoding='utf-8')
        for row in finance_domain.MIGRATION:
            rel, symbol = row['location'].split(':', 1)
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a', encoding='utf-8') as handle:
                handle.write(f'def {symbol}():\n    pass\n')
        for branch in finance_domain.BRANCHES.values():
            for entry in branch['entry_points']:
                rel, symbol = entry.split(':', 1)
                with (root / rel).open('a', encoding='utf-8') as handle:
                    handle.write(f'def {symbol}():\n    pass\n')
        for rel, text in (replace or {}).items():
            with (root / rel).open('a', encoding='utf-8') as handle:
                handle.write(text)
        return root

    def test_synthetic_clean_tree_passes(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(finance_domain.check(self._tree(td)), [])

    def test_finance_module_importing_communication_is_flagged(self):
        for source in ('from modules import notify\n', 'import modules.outbox\n',
                       'from modules.permission_grants import grant\n'):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as td:
                root = self._tree(td, {'modules/finance_alerts.py': source})
                self.assertIn('FIN-001', {row['rule'] for row in finance_domain.check(root)})

    def test_tool_finance_effectful_action_is_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td, {'modules/tool_finance.py': "CONTRACT = {'actions': [{'class': 'money_credential'}]}\n"})
            self.assertIn('FIN-002', {row['rule'] for row in finance_domain.check(root)})

    def test_open_migration_requires_plan_location_to_exist(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            (root / 'modules/watcher.py').write_text('', encoding='utf-8')
            rules = {row['rule'] for row in finance_domain.check(root)}
            self.assertIn('FIN-003', rules)

    def test_completed_migration_is_not_a_live_static_obligation(self):
        completed = ({'step': '3-D', 'branch': 'alarm',
                      'location': 'modules/moved.py:old_entry',
                      'target': 'modules/finance_alert_tick.py:tick',
                      'status': 'completed'},)
        with tempfile.TemporaryDirectory() as td, \
                patch.object(finance_domain, 'MIGRATION', completed):
            self.assertNotIn('FIN-003', {row['rule'] for row in finance_domain.check(td)})

    def test_check_does_not_import_or_run_finance_code(self):
        with patch('modules.finance.answer', side_effect=AssertionError('Canlı finans yasak')), \
                patch('modules.public_sources.fetch', side_effect=AssertionError('Ağ yasak')):
            self.assertEqual(finance_domain.check(), [])


if __name__ == '__main__':
    unittest.main()
