"""Finans takip listesi depolaması; gerçek kullanıcı DATA_DIR alanına yazmaz."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import finance_watchlist as watchlist


class FinanceWatchlistTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'finance_watchlists'
        patcher = patch.object(watchlist, '_ROOT', self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def rows(self, owner='alice'):
        return json.loads((self.root / f'{owner}.json').read_text(encoding='utf-8'))

    def test_add_list_remove_and_clear(self):
        self.assertEqual(watchlist.add('alice', 'doviz', 'usd'), {'kind': 'doviz', 'symbol': 'USD'})
        self.assertEqual(watchlist.add('alice', 'kripto', 'btc'), {'kind': 'kripto', 'symbol': 'BTC'})
        self.assertEqual(watchlist.list_items('alice'), [
            {'kind': 'doviz', 'symbol': 'USD'},
            {'kind': 'kripto', 'symbol': 'BTC'},
        ])
        self.assertTrue(watchlist.remove('alice', 'doviz', 'usd'))
        self.assertFalse(watchlist.remove('alice', 'doviz', 'usd'))
        self.assertEqual(watchlist.clear('alice'), 1)
        self.assertEqual(watchlist.list_items('alice'), [])

    def test_duplicate_add_returns_existing_without_new_row(self):
        first = watchlist.add('alice', 'kripto', 'btc')
        second = watchlist.add('alice', 'kripto', 'BTC')
        self.assertEqual(second, first)
        self.assertEqual(self.rows(), [{'kind': 'kripto', 'symbol': 'BTC'}])

    def test_twenty_first_item_is_rejected(self):
        for i in range(20):
            watchlist.add('alice', 'hisse', f'S{i}')
        with self.assertRaisesRegex(ValueError, r'^Takip listesi dolu \(en fazla 20\)\.$'):
            watchlist.add('alice', 'hisse', 'S20')
        self.assertEqual(len(watchlist.list_items('alice')), 20)

    def test_invalid_inputs_do_not_write(self):
        invalid = [
            ('fon', 'USD'),
            (None, 'USD'),
            ('doviz', ''),
            ('doviz', 'ABCDEFGHIJKLM'),
            ('kripto', 'BTC-USD'),
            ('hisse', 'A/B'),
            ('hisse', None),
            ('altin', 'XAU'),
        ]
        for kind, symbol in invalid:
            with self.subTest(kind=kind, symbol=symbol), self.assertRaises(ValueError):
                watchlist.add('alice', kind, symbol)
        self.assertFalse(self.root.exists())

    def test_lowercase_and_turkish_i_are_normalised(self):
        self.assertEqual(watchlist.add('alice', 'doviz', 'usd')['symbol'], 'USD')
        self.assertEqual(watchlist.add('alice', 'hisse', 'bİt')['symbol'], 'BIT')
        self.assertEqual(watchlist.add('alice', 'kripto', 'bıt')['symbol'], 'BIT')
        self.assertEqual(watchlist.add('alice', 'altin', 'gram')['symbol'], 'GRAM')

    def test_users_are_isolated(self):
        watchlist.add('alice', 'doviz', 'USD')
        watchlist.add('bob', 'kripto', 'BTC')
        self.assertEqual(watchlist.list_items('alice'), [{'kind': 'doviz', 'symbol': 'USD'}])
        self.assertEqual(watchlist.list_items('bob'), [{'kind': 'kripto', 'symbol': 'BTC'}])
        watchlist.clear('alice')
        self.assertEqual(watchlist.list_items('bob'), [{'kind': 'kripto', 'symbol': 'BTC'}])

    def test_corrupt_json_is_backed_up_and_recovers_empty(self):
        self.root.mkdir(parents=True)
        path = self.root / 'alice.json'
        path.write_text('[{"kind":', encoding='utf-8')
        with patch.object(watchlist, '_record_failure') as diagnostic:
            self.assertEqual(watchlist.list_items('alice'), [])
        diagnostic.assert_called_once_with('modules/finance_watchlist.py:read')
        backup = self.root / 'alice.bozuk'
        self.assertTrue(backup.exists())
        self.assertEqual(backup.read_text(encoding='utf-8'), '[{"kind":')
        self.assertFalse(path.exists())
        watchlist.add('alice', 'doviz', 'EUR')
        self.assertEqual(watchlist.list_items('alice'), [{'kind': 'doviz', 'symbol': 'EUR'}])
        self.assertEqual(backup.read_text(encoding='utf-8'), '[{"kind":')

    def test_busy_owner_watchlist_does_not_lose_concurrent_updates(self):
        from modules import file_resource_guard, resource_leases
        watchlist.add('alice', 'doviz', 'USD')
        path = self.root / 'alice.json'
        before = path.read_bytes()
        with file_resource_guard.claim_paths(path):
            for operation in (
                lambda: watchlist.add('alice', 'kripto', 'BTC'),
                lambda: watchlist.remove('alice', 'doviz', 'USD'),
                lambda: watchlist.list_items('alice'),
                lambda: watchlist.clear('alice'),
            ):
                with self.subTest(operation=operation), self.assertRaises(
                        resource_leases.LeaseConflict):
                    operation()
            # A distinct owner remains independent, rather than sharing
            # a fake global finance resource.
            self.assertEqual(watchlist.add('bob', 'kripto', 'BTC')['symbol'], 'BTC')
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(watchlist.list_items('alice'),
                         [{'kind': 'doviz', 'symbol': 'USD'}])

    def test_corrupt_list_backup_is_create_only(self):
        self.root.mkdir()
        path = self.root / 'alice.json'
        path.write_text('[{"kind":')
        backup = self.root / 'alice.bozuk'
        backup.write_bytes(b'foreign previous backup')
        self.assertEqual(watchlist.list_items('alice'), [])
        self.assertEqual(backup.read_bytes(), b'foreign previous backup')
        self.assertEqual((self.root / 'alice.1.bozuk').read_bytes(),
                         b'[{"kind":')
        self.assertFalse(path.exists())

    def test_path_traversal_is_rejected_by_every_entry_point(self):
        for owner in ['../x', '..\\x', 'C:\\x', '/x', '', '.', 'Alice', 'a/b']:
            calls = [
                lambda owner=owner: watchlist.add(owner, 'doviz', 'USD'),
                lambda owner=owner: watchlist.remove(owner, 'doviz', 'USD'),
                lambda owner=owner: watchlist.list_items(owner),
                lambda owner=owner: watchlist.clear(owner),
            ]
            for call in calls:
                with self.subTest(owner=owner), self.assertRaises(ValueError):
                    call()
        self.assertFalse(self.root.exists())

    def test_uses_patched_temporary_root_not_real_data_dir(self):
        watchlist.add('alice', 'doviz', 'USD')
        self.assertTrue((self.root / 'alice.json').is_file())
        self.assertEqual(watchlist._path('alice').parent, self.root)


if __name__ == '__main__':
    unittest.main()
