from decimal import Decimal
import unittest
from unittest.mock import patch

from modules import finance, watcher


class FinanceQuoteTests(unittest.TestCase):
    def test_public_price_entry_preserves_each_alarm_price_kind(self):
        with patch.object(finance, 'rates', return_value=({'USD': Decimal('34')}, {})), \
             patch.object(finance, '_yahoo', return_value={'last': Decimal('60')}), \
             patch.object(finance, '_market', return_value={'last': finance.TROY_OUNCE_GRAMS * 50}) as market:
            self.assertEqual(finance.quote('doviz', 'USD'), 34)
            self.assertEqual(finance.quote('hisse', 'THYAO'), 60)
            self.assertEqual(finance.quote('altin', 'GRAM'), 50)
            market.assert_called_with('PAXGTRY')
            finance.quote('kripto', 'BTC')
            market.assert_called_with('BTCTRY')

    def test_watcher_delegates_price_to_finance(self):
        with patch.object(finance, 'quote', return_value=42) as quote:
            self.assertEqual(watcher._finance_price('hisse', 'THYAO'), 42)
        quote.assert_called_once_with('hisse', 'THYAO')

    def test_unsupported_kind_does_not_fetch(self):
        with patch.object(finance, '_market') as market:
            with self.assertRaises(ValueError):
                finance.quote('trade', 'BTC')
        market.assert_not_called()
