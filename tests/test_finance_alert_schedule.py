"""Pure scheduling/text helpers; the caller retains deferred notifications."""
import copy
from datetime import datetime, timezone
import unittest
from modules import finance_alert_schedule as schedule


def rule(ident='r1', **changes):
    return {'id': ident, 'kind': 'doviz', 'symbol': 'USD', 'op': 'above', 'value': 33.10, **changes}


class FinanceAlertScheduleTests(unittest.TestCase):
    def test_due_rules_first_check_and_interval_boundary(self):
        rules = [rule('first'), rule('recent'), rule('boundary'), rule('future')]
        state = {'recent': {'checked_at': 701}, 'boundary': {'checked_at': 700}, 'future': {'checked_at': 1001}}
        self.assertEqual(schedule.due_rules(rules, state, now=1000), [rules[0], rules[2]])
        self.assertEqual(schedule.due_rules([rule()], {'r1': {'checked_at': 1000}}, 1000, min_interval=0), [rule()])

    def test_due_rules_bad_rows_or_state_do_not_stop_valid_rule(self):
        rules = [None, {}, rule('bad', op=[]), rule('bad-time'), rule('good')]
        state = {'bad-time': {'checked_at': float('nan')}}
        self.assertEqual(schedule.due_rules(rules, state, 1000), [rules[-1]])
        for invalid in (None, {}, 'bad', 3):
            self.assertEqual(schedule.due_rules(invalid, {}, 1000), [])
        self.assertEqual(schedule.due_rules([rule()], [], 1000), [])

    def test_due_rules_does_not_use_fired_at_as_last_check_or_mutate_inputs(self):
        rules = [rule(), rule()]
        state = {'r1': {'price': 34, 'fired_at': 999}}
        before = copy.deepcopy((rules, state))
        result = schedule.due_rules(rules, state, 1000)
        self.assertEqual(result, [rule()])
        result[0]['symbol'] = 'changed'
        self.assertEqual((rules, state), before)

    def test_due_rules_invalid_clock_or_interval_rejected(self):
        for bad in (True, -1, None, '300', float('nan'), float('inf')):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):schedule.due_rules([rule()], {}, bad)
                with self.assertRaises(ValueError):schedule.due_rules([rule()], {}, 1000, bad)

    def test_threshold_notification_is_turkish_one_sentence_with_current_price(self):
        self.assertEqual(schedule.notification_text(rule(), 34),
                         "USD 33,10 TL'nin üstüne çıktı; güncel fiyat 34,00 TL.")
        self.assertEqual(schedule.notification_text(rule(op='below'), 32.5),
                         "USD 33,10 TL'nin altına indi; güncel fiyat 32,50 TL.")

    def test_percentage_notification_grouping_currency_and_rounding(self):
        self.assertEqual(schedule.notification_text(rule(op='pct_up', value=5, symbol='BTC'), 1234.565, 'USD'),
                         'BTC için %5,00 yükseliş alarmı; güncel fiyat 1.234,57 USD.')
        self.assertIn('düşüş alarmı', schedule.notification_text(rule(op='pct_down', value=5), 0, 'EUR'))

    def test_notification_invalid_rule_price_currency_cannot_invent_advice(self):
        for bad in (None, True, -1, float('nan'), float('inf'), '34'):
            with self.subTest(price=bad), self.assertRaises(ValueError):schedule.notification_text(rule(), bad)
        for bad in (None, {}, rule(op=[]), rule(symbol='USD\nSatın al')):
            with self.subTest(rule=bad), self.assertRaises(ValueError):schedule.notification_text(bad, 34)
        with self.assertRaises(ValueError):schedule.notification_text(rule(), 34, 'TRY\nBUY')
        for op in ('above', 'below', 'pct_up', 'pct_down'):
            text = schedule.notification_text(rule(op=op, value=5), 34).casefold()
            self.assertFalse(any(word in text for word in ('satın al', 'satmalısın', 'yatırım tavsiyesi', 'öneririm')))

    def test_quiet_hours_overnight_boundaries_and_daytime(self):
        for hour, expected in ((22, 'send'), (23, 'defer'), (0, 'defer'), (6, 'defer'), (7, 'send')):
            with self.subTest(hour=hour):
                self.assertEqual(schedule.quiet_hours(datetime(2026, 10, 19, hour)), expected)

    def test_quiet_hours_epoch_uses_istanbul_and_custom_same_day_range(self):
        moment = datetime(2026, 10, 19, 20, tzinfo=timezone.utc)
        self.assertEqual(schedule.quiet_hours(moment.timestamp()), 'defer')  # Istanbul 23:00
        self.assertEqual(schedule.quiet_hours(moment), 'defer')
        self.assertEqual(schedule.quiet_hours(datetime(2026, 10, 19, 10), 9, 17), 'defer')
        self.assertEqual(schedule.quiet_hours(datetime(2026, 10, 19, 17), 9, 17), 'send')
        self.assertEqual(schedule.quiet_hours(datetime(2026, 10, 19, 10), 9, 9), 'send')

    def test_quiet_hours_defer_retains_pending_payload_for_later_send(self):
        pending = {'rule': rule(), 'price': 34}
        before = copy.deepcopy(pending)
        self.assertEqual(schedule.quiet_hours(datetime(2026, 10, 19, 23)), 'defer')
        self.assertEqual(pending, before)
        self.assertEqual(schedule.quiet_hours(datetime(2026, 10, 20, 7)), 'send')
        self.assertIn('USD', schedule.notification_text(**pending))

    def test_quiet_hours_invalid_values_raise(self):
        for bad in (None, True, '23:00', float('nan'), float('inf')):
            with self.subTest(now=bad), self.assertRaises(ValueError):schedule.quiet_hours(bad)
        for bad in (True, -1, 24, 2.5, '23'):
            with self.subTest(hour=bad), self.assertRaises(ValueError):schedule.quiet_hours(1000, bad, 7)


if __name__ == '__main__':
    unittest.main()
