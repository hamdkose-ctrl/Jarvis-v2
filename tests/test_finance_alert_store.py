"""Local alarm rule/state persistence; all writes use a temporary DATA_DIR/root."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from modules import finance_alert_store as store


def rule(**changes):
    return {'kind': 'doviz', 'symbol': 'USD', 'op': 'above', 'value': 40, **changes}


class FinanceAlertStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data_dir = Path(temporary.name)
        self.root = self.data_dir / 'finance_alerts'
        self.enterContext(patch.object(store, '_ROOT', self.root))

    def path(self, owner='alice'):
        return self.root / (owner + '.json')

    def test_add_list_remove_and_clear(self):
        self.assertEqual(store.list_rules('alice'), [])
        first = store.add_rule('alice', rule())
        second = store.add_rule('alice', rule(symbol='EUR'))
        self.assertRegex(first['id'], r'^[a-z0-9]{8,24}$')
        self.assertGreaterEqual(first['created'], 0)
        self.assertEqual(store.list_rules('alice'), [first, second])
        self.assertTrue(store.remove_rule('alice', first['id']))
        self.assertFalse(store.remove_rule('alice', first['id']))
        self.assertEqual(store.clear('alice'), 1)
        self.assertEqual(store.clear('alice'), 0)
        self.assertEqual(store.list_rules('alice'), [])

    def test_duplicate_identity_keeps_id_created_and_original_cooldown(self):
        first = store.add_rule('alice', rule())
        again = store.add_rule('alice', rule(value=40.0, cooldown_s=60))
        self.assertEqual(first, again)
        self.assertEqual(len(store.list_rules('alice')), 1)
        self.assertEqual(first['cooldown_s'], 3600)
        # All four identity fields matter.
        for other in [rule(kind='kripto'), rule(symbol='EUR'), rule(op='below'), rule(value=41)]:
            self.assertNotEqual(store.add_rule('alice', other)['id'], first['id'])

    def test_twenty_first_rule_is_rejected_without_changing_file(self):
        saved = [store.add_rule('alice', rule(symbol=f'S{i}')) for i in range(20)]
        before = self.path().read_bytes()
        with self.assertRaisesRegex(ValueError, r'^Alarm listesi dolu \(en fazla 20\)\.$'):
            store.add_rule('alice', rule(symbol='S20'))
        self.assertEqual(self.path().read_bytes(), before)
        self.assertEqual(store.add_rule('alice', rule(symbol='S0')), saved[0])

    def test_invalid_rules_never_create_storage(self):
        invalid = [None, [], rule(op='unknown'), rule(value=float('nan')), rule(symbol='  '),
                   rule(cooldown_s=59), rule(value=True), rule(kind=[]), rule(op=[])]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                store.add_rule('alice', value)
        self.assertFalse(self.root.exists())

    def test_invalid_rule_cannot_modify_existing_or_corrupt_file(self):
        store.add_rule('alice', rule())
        before = self.path().read_bytes()
        with self.assertRaises(ValueError):store.add_rule('alice', rule(value=float('nan')))
        self.assertEqual(self.path().read_bytes(), before)
        self.path().write_bytes(b'{broken')
        with self.assertRaises(ValueError):store.add_rule('alice', rule(cooldown_s=59))
        self.assertEqual(self.path().read_bytes(), b'{broken')
        self.assertFalse(self.path().with_suffix('.bozuk').exists())

    def test_state_round_trip_and_evaluator_integration(self):
        from modules import finance_alerts
        saved = store.add_rule('alice', rule())
        self.assertIsNone(store.get_state('alice', saved['id']))
        result = finance_alerts.evaluate(saved, 41, previous=store.get_state('alice', saved['id']), now=100)
        store.set_state('alice', saved['id'], result['state'])
        self.assertEqual(store.get_state('alice', saved['id']), {'price': 41, 'fired_at': 100})
        store.set_state('alice', saved['id'], {'price': None, 'fired_at': None})
        self.assertEqual(store.get_state('alice', saved['id']), {'price': None, 'fired_at': None})
        store.set_state('alice', saved['id'], {'price': 0, 'fired_at': 0})
        self.assertEqual(store.get_state('alice', saved['id']), {'price': 0, 'fired_at': 0})

    def test_invalid_states_do_not_change_existing_state(self):
        saved = store.add_rule('alice', rule())
        store.set_state('alice', saved['id'], {'price': 40, 'fired_at': 100})
        before = self.path().read_bytes()
        states = [None, [], {}, {'price': 1}, {'price': None, 'fired_at': None, 'extra': 1}]
        for field in ('price', 'fired_at'):
            for invalid in (float('nan'), float('inf'), -1, True, False, '10'):
                states.append({'price': 1, 'fired_at': 1, field: invalid})
        for state in states:
            with self.subTest(state=state), self.assertRaises(ValueError):
                store.set_state('alice', saved['id'], state)
            self.assertEqual(self.path().read_bytes(), before)

    def test_unknown_rules_and_removal_clear_state(self):
        saved = store.add_rule('alice', rule())
        store.set_state('alice', saved['id'], {'price': 40, 'fired_at': 100})
        self.assertTrue(store.remove_rule('alice', saved['id']))
        for name in (saved['id'], 'missing'):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, r'^Bilinmeyen alarm kuralı\.$'):
                    store.get_state('alice', name)
                with self.assertRaisesRegex(ValueError, r'^Bilinmeyen alarm kuralı\.$'):
                    store.set_state('alice', name, {'price': 1, 'fired_at': None})
        self.assertNotIn(saved['id'], self.path().read_text())

    def test_two_users_do_not_share_rules_or_state(self):
        alice = store.add_rule('alice', rule())
        bob = store.add_rule('bob', rule(symbol='BTC', kind='kripto'))
        store.set_state('alice', alice['id'], {'price': 40, 'fired_at': 100})
        self.assertEqual(store.list_rules('bob'), [bob])
        with self.assertRaisesRegex(ValueError, 'Bilinmeyen alarm kuralı'):
            store.get_state('bob', alice['id'])
        self.assertIsNone(store.get_state('bob', bob['id']))
        store.clear('alice')
        self.assertEqual(store.list_rules('bob'), [bob])

    def test_every_entry_point_rejects_traversal_and_device_names(self):
        owners = ['../x', '..\\x', '/tmp/x', 'C:\\x', '', '.', 'Alice', 'a/b', 'con', 'nul', 'com1', 'lpt9']
        for owner in owners:
            calls = [lambda: store.add_rule(owner, rule()), lambda: store.list_rules(owner),
                     lambda: store.remove_rule(owner, 'missing'), lambda: store.clear(owner),
                     lambda: store.get_state(owner, 'missing'),
                     lambda: store.set_state(owner, 'missing', {'price': None, 'fired_at': None})]
            for call in calls:
                with self.subTest(owner=owner), self.assertRaises(ValueError):call()
        self.assertFalse(self.root.exists())

    def test_corrupt_file_is_backed_up_and_empty_store_recovers(self):
        self.root.mkdir()
        content = b'{not-json'
        self.path().write_bytes(content)
        with patch.object(store, '_record_failure') as diagnostic:
            self.assertEqual(store.list_rules('alice'), [])
        diagnostic.assert_called_once_with('modules/finance_alert_store.py:read')
        backup = self.path().with_suffix('.bozuk')
        self.assertEqual(backup.read_bytes(), content)
        self.assertFalse(self.path().exists())
        saved = store.add_rule('alice', rule())
        self.assertEqual(store.list_rules('alice'), [saved])
        self.assertEqual(backup.read_bytes(), content)
        self.path().write_bytes(b'broken again')
        self.assertEqual(store.list_rules('alice'), [])
        self.assertEqual(backup.read_bytes(), content)
        self.assertEqual((self.root / 'alice.1.bozuk').read_bytes(), b'broken again')

    def test_deeply_nested_json_is_backed_up(self):
        self.root.mkdir(parents=True)
        raw = b'[' * 2000 + b'0' + b']' * 2000
        self.path().write_bytes(raw)
        with patch.object(store.json, 'loads', side_effect=RecursionError('nested JSON')):
            self.assertEqual(store.list_rules('alice'), [])
        self.assertEqual(self.path().with_suffix('.bozuk').read_bytes(), raw)

    def test_malformed_structure_and_state_are_also_backed_up(self):
        saved = store.add_rule('alice', rule())
        document = json.loads(self.path().read_text())
        document['states'][saved['id']] = {'price': float('nan'), 'fired_at': 0}
        self.path().write_text(json.dumps(document), encoding='utf-8')
        self.assertEqual(store.list_rules('alice'), [])
        self.assertTrue(self.path().with_suffix('.bozuk').is_file())

    def test_symbol_is_not_required_in_watchlist_and_returns_are_detached(self):
        input_rule = rule(symbol=' unlisted-symbol ')
        saved = store.add_rule('alice', input_rule)
        self.assertEqual(saved['symbol'], 'unlisted-symbol')
        self.assertEqual(input_rule['symbol'], ' unlisted-symbol ')
        saved['symbol'] = 'changed'
        rows = store.list_rules('alice');rows[0]['value'] = 999
        self.assertEqual(store.list_rules('alice')[0]['value'], 40)
        self.assertEqual(store.list_rules('alice')[0]['symbol'], 'unlisted-symbol')

    def test_failed_atomic_write_preserves_original_and_removes_temporary(self):
        store.add_rule('alice', rule())
        before = self.path().read_bytes()
        with patch.object(store.os, 'replace', side_effect=OSError('disk error')), patch.object(store, '_record_failure') as diagnostic:
            with self.assertRaises(OSError):store.add_rule('alice', rule(symbol='EUR'))
        diagnostic.assert_called_once_with('modules/finance_alert_store.py:write')
        self.assertEqual(self.path().read_bytes(), before)
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_write_cannot_create_a_file_the_reader_would_reject_for_size(self):
        store.add_rule('alice', rule())
        before = self.path().read_bytes()
        with patch.object(store, '_MAX_BYTES', len(before) + 10):
            with self.assertRaises(ValueError):store.add_rule('alice', rule(symbol='EUR'))
        self.assertEqual(self.path().read_bytes(), before)
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_symlink_and_junction_paths_are_refused_without_using_them(self):
        for attribute in ('is_symlink', 'is_junction'):
            for blocked in (self.root, self.path(), self.root.parent):
                with self.subTest(attribute=attribute, blocked=blocked):
                    with patch.object(Path, attribute, lambda p: p == blocked, create=True):
                        with self.assertRaises(ValueError):store.add_rule('alice', rule())
        self.assertFalse(self.root.exists())

    def test_threads_cannot_exceed_limit_or_create_duplicates(self):
        with ThreadPoolExecutor(max_workers=6) as workers:
            ids = list(workers.map(lambda _: store.add_rule('alice', rule())['id'], range(12)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(len(store.list_rules('alice')), 1)

    def test_data_dir_environment_selects_temporary_store(self):
        isolated = self.data_dir / 'isolated-data'
        env = os.environ.copy();env['JARVIS_DATA_DIR'] = str(isolated)
        script = "from modules import finance_alert_store as s; r=s.add_rule('alice', {'kind':'doviz','symbol':'USD','op':'above','value':40}); print(s._ROOT); print(s.list_rules('alice')[0]['id']==r['id'])"
        result = subprocess.run([sys.executable, '-X', 'utf8', '-c', script], env=env,
                                text=True, capture_output=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(isolated), result.stdout)
        self.assertIn('True', result.stdout)
        self.assertTrue((isolated / 'finance_alerts' / 'alice.json').exists())


if __name__ == '__main__':
    unittest.main()
