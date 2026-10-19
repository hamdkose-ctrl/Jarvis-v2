import math
import unittest

from modules import finance_alerts as alerts


def rule(op='above', value=100, **extra):
    row = {'kind': 'doviz', 'symbol': 'USD', 'op': op, 'value': value}
    row.update(extra)
    return row


class FinanceAlertsEdgeTests(unittest.TestCase):
    def test_invalid_rule_numbers_raise_value_error(self):
        invalid = [
            math.nan, math.inf, -math.inf, True, False, -1, 0,
            '12,5', '12.5', 10 ** 400,
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                alerts.evaluate(rule(value=value), 101, now=1000)

    def test_finite_very_large_and_very_small_thresholds_do_not_crash(self):
        rows = [
            (1e308, 1.1e308, True),
            (5e-324, 1e-323, True),
        ]
        for threshold, price, expected in rows:
            with self.subTest(threshold=threshold, price=price):
                result = alerts.evaluate(rule(value=threshold), price, None, now=1000)
                self.assertEqual(result['fire'], expected)

    def test_invalid_prices_never_fire_or_raise(self):
        previous = {'price': 99, 'fired_at': 500}
        invalid = [
            None, math.nan, math.inf, -math.inf, -1, True, False,
            '12,5', '12.5', 10 ** 400,
        ]
        for price in invalid:
            with self.subTest(price=price):
                result = alerts.evaluate(rule(), price, previous, now=1000)
                self.assertFalse(result['fire'])
                self.assertIn('Fiyat alınamadı', result['reason'])
                self.assertEqual(result['state'], {'price': 99.0, 'fired_at': 500.0})

    def test_missing_previous_fields_do_not_crash(self):
        rows = [
            ({}, 101),
            ({'price': None}, 101),
            ({'fired_at': None}, 101),
            ({'price': 99}, 101),
        ]
        for previous, price in rows:
            with self.subTest(previous=previous):
                result = alerts.evaluate(rule(), price, previous, now=1000)
                self.assertIsInstance(result['fire'], bool)
                self.assertEqual(result['state']['price'], float(price))

    def test_corrupt_previous_values_fail_safe_without_firing(self):
        corrupt = [
            {'price': '99', 'fired_at': None},
            {'price': math.nan, 'fired_at': None},
            {'price': math.inf, 'fired_at': None},
            {'price': True, 'fired_at': None},
            {'price': 99, 'fired_at': 'PRIVATE'},
            {'price': 99, 'fired_at': math.nan},
            {'price': 10 ** 400, 'fired_at': None},
        ]
        for previous in corrupt:
            with self.subTest(previous=previous):
                result = alerts.evaluate(rule(), 101, previous, now=1000)
                self.assertFalse(result['fire'])
                self.assertEqual(result['state']['price'], 101.0)

    def test_same_price_does_not_fire_twice(self):
        rows = [
            (rule('above', 100), 101),
            (rule('below', 100), 99),
            (rule('pct_up', 10), 110),
            (rule('pct_down', 10), 90),
        ]
        for alarm_rule, price in rows:
            with self.subTest(op=alarm_rule['op']):
                base = {'price': 100, 'fired_at': None}
                first = alerts.evaluate(alarm_rule, price, base, now=1000)
                self.assertTrue(first['fire'])
                second = alerts.evaluate(alarm_rule, price, first['state'], now=2000)
                self.assertFalse(second['fire'])


if __name__ == '__main__':
    unittest.main()
