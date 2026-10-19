import copy
import math
import unittest
from unittest.mock import patch

from modules import finance_alerts as alerts


def rule(op='above', value=100, **extra):
    row = {'kind': 'doviz', 'symbol': 'USD', 'op': op, 'value': value}
    row.update(extra)
    return row


class FinanceAlertsTests(unittest.TestCase):
    def test_above_and_below_edge_transitions(self):
        rows = [
            (rule('above', 100), 101, {'price': 99, 'fired_at': None}, True),
            (rule('above', 100), 102, {'price': 101, 'fired_at': None}, False),
            (rule('below', 100), 99, {'price': 101, 'fired_at': None}, True),
            (rule('below', 100), 98, {'price': 99, 'fired_at': None}, False),
        ]
        for alarm_rule, price, previous, expected in rows:
            with self.subTest(op=alarm_rule['op'], price=price, previous=previous):
                result = alerts.evaluate(alarm_rule, price, previous, now=1000)
                self.assertEqual(result['fire'], expected)
                self.assertEqual(result['state']['price'], float(price))

    def test_equality_never_fires_absolute_threshold(self):
        for op in ['above', 'below']:
            with self.subTest(op=op):
                result = alerts.evaluate(rule(op, 100), 100, {'price': 99 if op == 'above' else 101, 'fired_at': None}, now=1000)
                self.assertFalse(result['fire'])
        self.assertFalse(alerts.evaluate(rule('above', 100), 101, {'price': 100, 'fired_at': None}, now=1000)['fire'])
        self.assertFalse(alerts.evaluate(rule('below', 100), 99, {'price': 100, 'fired_at': None}, now=1000)['fire'])

    def test_first_absolute_observation_can_fire(self):
        rows = [('above', 101, True), ('above', 99, False), ('below', 99, True), ('below', 101, False)]
        for op, price, expected in rows:
            with self.subTest(op=op, price=price):
                self.assertEqual(alerts.evaluate(rule(op, 100), price, None, now=500)['fire'], expected)

    def test_cooldown_inside_and_outside(self):
        alarm_rule = rule('above', 100, cooldown_s=60)
        previous = {'price': 99, 'fired_at': 1000}
        inside = alerts.evaluate(alarm_rule, 101, previous, now=1059)
        self.assertFalse(inside['fire'])
        self.assertIn('bekleme süresinde', inside['reason'])
        self.assertEqual(inside['state'], {'price': 101.0, 'fired_at': 1000.0})

        outside = alerts.evaluate(alarm_rule, 101, previous, now=1060)
        self.assertTrue(outside['fire'])
        self.assertEqual(outside['state'], {'price': 101.0, 'fired_at': 1060.0})

    def test_pct_up_and_down_use_previous_price(self):
        rows = [
            ('pct_up', 10, 100, 110, True),
            ('pct_up', 10, 100, 109, False),
            ('pct_down', 10, 100, 90, True),
            ('pct_down', 10, 100, 91, False),
        ]
        for op, value, old_price, price, expected in rows:
            with self.subTest(op=op, price=price):
                previous = {'price': old_price, 'fired_at': None}
                result = alerts.evaluate(rule(op, value), price, previous, now=1000)
                self.assertEqual(result['fire'], expected)
                self.assertIn(str(value), result['reason'])

    def test_pct_without_previous_price_waits_and_zero_base_errors(self):
        result = alerts.evaluate(rule('pct_up', 5), 105, None, now=1000)
        self.assertFalse(result['fire'])
        self.assertIn('önceki fiyat yok', result['reason'])
        self.assertEqual(result['state'], {'price': 105.0, 'fired_at': None})
        with self.assertRaisesRegex(ValueError, 'önceki fiyat sıfır'):
            alerts.evaluate(rule('pct_down', 5), 90, {'price': 0, 'fired_at': None}, now=1000)

    def test_invalid_rules_and_values_raise_value_error(self):
        invalid = [
            {'kind': 'fon', 'symbol': 'USD', 'op': 'above', 'value': 1},
            {'kind': 'doviz', 'symbol': '', 'op': 'above', 'value': 1},
            rule('unknown', 1),
            rule('above', 0),
            rule('above', -1),
            rule('above', True),
            rule('above', math.nan),
            rule('above', math.inf),
            rule('pct_up', 101),
            rule('pct_down', 0),
            rule('above', 1, cooldown_s=59),
            rule('above', 1, cooldown_s=604801),
            rule('above', 1, cooldown_s=True),
        ]
        for alarm_rule in invalid:
            with self.subTest(alarm_rule=alarm_rule), self.assertRaises(ValueError):
                alerts.evaluate(alarm_rule, 10, now=1000)

    def test_unavailable_prices_do_not_fire_and_preserve_previous_state(self):
        previous = {'price': 98, 'fired_at': 777}
        for price in [None, math.nan, math.inf, -1, True, '101']:
            with self.subTest(price=price):
                result = alerts.evaluate(rule('above', 100), price, previous, now=1000)
                self.assertFalse(result['fire'])
                self.assertIn('Fiyat alınamadı', result['reason'])
                self.assertEqual(result['state'], {'price': 98.0, 'fired_at': 777.0})

    def test_inputs_are_not_mutated(self):
        alarm_rule = rule('above', 100, cooldown_s=120)
        previous = {'price': 99, 'fired_at': 10}
        rule_before = copy.deepcopy(alarm_rule)
        previous_before = copy.deepcopy(previous)
        alerts.evaluate(alarm_rule, 101, previous, now=200)
        self.assertEqual(alarm_rule, rule_before)
        self.assertEqual(previous, previous_before)

    def test_now_defaults_to_time_time(self):
        with patch.object(alerts.time, 'time', return_value=4321.5) as clock:
            result = alerts.evaluate(rule('above', 100), 101, None)
        clock.assert_called_once_with()
        self.assertTrue(result['fire'])
        self.assertEqual(result['state']['fired_at'], 4321.5)

    def test_reason_contains_price_and_threshold_without_investment_instruction(self):
        result = alerts.evaluate(rule('above', 100), 101, None, now=1000)
        self.assertIn('101', result['reason'])
        self.assertIn('100', result['reason'])
        lowered = result['reason'].lower()
        self.assertNotIn('kesin al', lowered)
        self.assertNotIn('kesin sat', lowered)


if __name__ == '__main__':
    unittest.main()
