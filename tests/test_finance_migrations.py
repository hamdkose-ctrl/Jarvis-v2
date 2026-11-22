"""Faz 3 göçleri: eski çağrı yolları Finance modülüne devreder, kendi mantığını yazmaz.

Yol haritası "3-B…3-F başlamadı" diyordu; kodda dört yol da devrettiği hâlde kayıt
açık kalmıştı. Bu testler devri davranışla kilitler (kaynak taraması değil).
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from modules import domain_tools, finance_domain, watcher


class MigrationDelegationTests(unittest.TestCase):
    def test_price_quote_delegates_to_finance(self):          # 3-B
        with patch('modules.finance.quote', return_value=42.5) as quote:
            self.assertEqual(watcher._finance_price('equity', 'ASELS'), 42.5)
        quote.assert_called_once_with('equity', 'ASELS')

    def test_alert_tick_delegates_to_finance_module(self):    # 3-C
        seen = []
        with patch('modules.finance_alert_tick.tick', return_value='ok') as tick:
            sonuc = watcher.finance_tick('hamdi', seen.append, now=100.0, price_getter=str)
        self.assertEqual(sonuc, 'ok')
        self.assertEqual(tick.call_args.kwargs, {'now': 100.0, 'price_getter': str})

    def test_dated_exchange_delegates_to_finance(self):      # 3-E
        with patch('modules.finance.dated_rate', return_value={'rate': 50.5}) as rate:
            sonuc = domain_tools.exchange('hamdi', 'USD', 'TRY', '2026-11-22', fetcher=str)
        self.assertEqual(sonuc, {'rate': 50.5})
        self.assertEqual(rate.call_args.args, ('hamdi', 'USD', 'TRY', '2026-11-22'))

    def test_csv_finance_branch_delegates_to_analysis(self):  # 3-F
        with patch('modules.finance_analysis.csv_summary', return_value={'rows': 3}) as summary:
            sonuc = domain_tools.csv_analysis('hamdi', 'finance', 'x.csv', {'amount': 'Tutar'})
        self.assertEqual(sonuc, {'rows': 3})
        summary.assert_called_once()


class MigrationRecordTests(unittest.TestCase):
    def test_all_five_phase3_steps_are_recorded(self):
        steps = {row['step'] for row in finance_domain.MIGRATION}
        self.assertEqual(steps, {'3-B', '3-C', '3-D', '3-E', '3-F'})

    def test_completed_steps_name_their_target_module(self):
        for row in finance_domain.MIGRATION:
            self.assertEqual(row['status'], 'completed', row['step'])
            self.assertTrue(row['target'].startswith('modules/'), row['step'])
            self.assertTrue(row['note'], row['step'])

    def test_no_migration_is_left_open(self):
        açık = [row for row in finance_domain.MIGRATION if row.get('status') != 'completed']
        self.assertEqual(açık, [])
