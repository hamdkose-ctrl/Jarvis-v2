"""Tek seferlik alarm değerlendirmesi; gerçek fiyat, ağ, model veya zamanlayıcı yok."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch


class FinanceAlertRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)
        self.enterContext(patch.dict(os.environ, {'JARVIS_DATA_DIR': str(self.data)}))
        from modules import finance_alert_runner, finance_alert_store, finance_alerts
        self.runner, self.store, self.alerts = finance_alert_runner, finance_alert_store, finance_alerts
        self.enterContext(patch.object(self.store, '_ROOT', self.data / 'finance_alerts'))
        self.diagnostic = self.enterContext(patch.object(self.runner, '_record_failure'))

    def add(self, owner='alice', **changes):
        return self.store.add_rule(owner, {'kind': 'doviz', 'symbol': 'USD', 'op': 'above',
                                          'value': 40, 'cooldown_s': 60, **changes})

    def test_no_rules_does_not_request_prices(self):
        getter = Mock()
        self.assertEqual(self.runner.run_once('alice', getter, now=100), [])
        getter.assert_not_called()
        self.assertFalse(self.store._ROOT.exists())

    def test_above_threshold_fires_once_and_preserves_exact_evaluator_reason(self):
        rule = self.add()
        expected = self.alerts.evaluate(rule, 41, None, 100)
        getter = Mock(return_value=41)
        fired = self.runner.run_once('alice', getter, now=100)
        self.assertEqual(fired, [{**{k: rule[k] for k in ('id', 'kind', 'symbol', 'op', 'value')},
                                 'reason': expected['reason']}])
        self.assertEqual(self.store.get_state('alice', rule['id']), expected['state'])
        self.assertEqual(self.runner.run_once('alice', getter, now=200), [])
        self.assertEqual(self.store.get_state('alice', rule['id']), {'price': 41, 'fired_at': 100})

    def test_nonfiring_observation_is_saved_before_crossing(self):
        rule = self.add()
        self.assertEqual(self.runner.run_once('alice', lambda *_: 39, now=90), [])
        self.assertEqual(self.store.get_state('alice', rule['id']), {'price': 39, 'fired_at': None})
        self.assertEqual(len(self.runner.run_once('alice', lambda *_: 41, now=100)), 1)

    def test_cooldown_keeps_last_fire_and_updates_price(self):
        rule = self.add()
        getter = Mock(side_effect=[41, 39, 41, 39, 41])
        self.assertEqual(len(self.runner.run_once('alice', getter, now=100)), 1)
        self.assertEqual(self.runner.run_once('alice', getter, now=110), [])
        self.assertEqual(self.runner.run_once('alice', getter, now=120), [])
        self.assertEqual(self.store.get_state('alice', rule['id']), {'price': 41, 'fired_at': 100})
        self.assertEqual(self.runner.run_once('alice', getter, now=150), [])
        self.assertEqual(len(self.runner.run_once('alice', getter, now=160)), 1)
        self.assertEqual(self.store.get_state('alice', rule['id'])['fired_at'], 160)

    def test_three_rules_two_symbols_request_only_two_prices(self):
        first = self.add()
        self.add(value=42)
        self.add(symbol='EUR')
        getter = Mock(return_value=41)
        self.assertEqual(len(self.runner.run_once('alice', getter, now=100)), 2)
        self.assertEqual(getter.call_args_list, [call('doviz', 'USD'), call('doviz', 'EUR')])
        self.assertEqual(self.store.get_state('alice', first['id'])['price'], 41)

    def test_same_symbol_in_different_kinds_is_not_the_same_price_key(self):
        self.add()
        self.add(kind='kripto')
        getter = Mock(return_value=41)
        self.runner.run_once('alice', getter, now=100)
        self.assertEqual(getter.call_args_list, [call('doviz', 'USD'), call('kripto', 'USD')])

    def test_missing_price_preserves_state_and_is_cached(self):
        first = self.add()
        second = self.add(value=42)
        previous = {'price': 39, 'fired_at': 10}
        for rule in (first, second):
            self.store.set_state('alice', rule['id'], previous)
        getter = Mock(return_value=None)
        self.assertEqual(self.runner.run_once('alice', getter, now=100), [])
        getter.assert_called_once_with('doviz', 'USD')
        for rule in (first, second):
            self.assertEqual(self.store.get_state('alice', rule['id']), previous)
        self.diagnostic.assert_not_called()

    def test_getter_exception_is_cached_and_other_symbol_still_runs(self):
        first = self.add()
        self.add(value=42)
        good = self.add(symbol='EUR')
        getter = Mock(side_effect=[RuntimeError('kaynak hatası'), 41])
        fired = self.runner.run_once('alice', getter, now=100)
        self.assertEqual([row['id'] for row in fired], [good['id']])
        self.assertEqual(getter.call_args_list, [call('doviz', 'USD'), call('doviz', 'EUR')])
        self.assertIsNone(self.store.get_state('alice', first['id']))
        self.diagnostic.assert_called_once_with('modules/finance_alert_runner.py:price')

    def test_two_users_do_not_share_rules_state_or_price_cache(self):
        alice, bob = self.add(), self.add(owner='bob')
        getter = Mock(return_value=41)
        self.runner.run_once('alice', getter, now=100)
        self.assertIsNone(self.store.get_state('bob', bob['id']))
        alice_state = self.store.get_state('alice', alice['id'])
        self.assertEqual([r['id'] for r in self.runner.run_once('bob', getter, now=200)], [bob['id']])
        self.assertEqual(self.store.get_state('alice', alice['id']), alice_state)
        self.assertEqual(getter.call_count, 2)

    def test_invalid_owner_keeps_store_value_error_and_never_calls_getter(self):
        getter = Mock()
        with self.assertRaises(ValueError) as original:
            self.store.list_rules('../x')
        with self.assertRaises(ValueError) as result:
            self.runner.run_once('../x', getter, now=100)
        self.assertEqual(str(result.exception), str(original.exception))
        getter.assert_not_called()
        self.diagnostic.assert_not_called()

    def test_corrupt_rule_is_reported_and_valid_rule_continues(self):
        bad, good = self.add(), self.add(symbol='EUR')
        for invalid in ({**bad, 'op': 'unknown'}, {**bad, 'value': 'bozuk'},
                        {**bad, 'kind': []}, {'id': bad['id']}, None):
            with self.subTest(invalid=invalid):
                self.store.set_state('alice', good['id'], {'price': 39, 'fired_at': None})
                self.diagnostic.reset_mock()
                with patch.object(self.store, 'list_rules', return_value=[invalid, good]):
                    fired = self.runner.run_once('alice', lambda *_: 41, now=100)
                self.assertEqual([r['id'] for r in fired], [good['id']])
                self.assertIsNone(self.store.get_state('alice', bad['id']))
                self.diagnostic.assert_called_once_with('modules/finance_alert_runner.py:evaluate')

    def test_invalid_evaluator_value_is_reported_without_state_change(self):
        rule = self.add()
        self.assertEqual(self.runner.run_once('alice', lambda *_: 41, now='bozuk'), [])
        self.assertIsNone(self.store.get_state('alice', rule['id']))
        self.diagnostic.assert_called_once_with('modules/finance_alert_runner.py:evaluate')

    def test_default_time_is_sampled_once_for_all_rules(self):
        first, second = self.add(), self.add(symbol='EUR')
        with patch.object(self.runner.time, 'time', return_value=1234) as clock:
            self.assertEqual(len(self.runner.run_once('alice', lambda *_: 41)), 2)
        clock.assert_called_once_with()
        for rule in (first, second):
            self.assertEqual(self.store.get_state('alice', rule['id'])['fired_at'], 1234)


if __name__ == '__main__':
    unittest.main()
