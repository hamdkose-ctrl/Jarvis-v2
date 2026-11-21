"""Synthetic tests of SQLite cross-process request reservations; no HTTP/network."""
import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from modules import router_quota as quota

NOW = 1794300000.

def policy(**updates):
    row = {'rpm':1, 'rpd':2, 'source_url':'https://provider.example/rate-limits',
           'verified_at':NOW-60, 'expires_at':NOW+2*86400}
    row.update(updates)
    return row

class AtomicQuotaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        p = patch.object(quota, 'POLICIES', {})
        p.start(); self.addCleanup(p.stop)

    def reserve(self, owner='alice', model='m', now=NOW):
        return quota.reserve(owner, 'groq', model, directory=self.folder, now=now)

    def test_no_configured_policy_does_not_guess_rate_limit(self):
        self.assertFalse(self.reserve())
        self.assertFalse((self.folder/'atomic_requests.sqlite3').exists())

    def test_minute_and_rolling_day_limits(self):
        quota.POLICIES[('groq','m')] = policy()
        self.assertTrue(self.reserve())
        with self.assertRaises(quota.ReservationExhausted) as caught:
            self.reserve()
        self.assertEqual(caught.exception.retry_after, 60)
        self.assertTrue(self.reserve(now=NOW+60))
        with self.assertRaises(quota.ReservationExhausted):
            self.reserve(now=NOW+120)
        self.assertTrue(self.reserve(now=NOW+86400))

    def test_isolated_by_owner_provider_and_exact_model(self):
        quota.POLICIES[('groq','m')] = policy()
        quota.POLICIES[('groq','m2')] = policy()
        self.assertTrue(self.reserve())
        self.assertTrue(self.reserve(owner='bob'))
        self.assertTrue(self.reserve(model='m2'))
        with self.assertRaises(quota.ReservationExhausted):
            self.reserve()

    def test_eight_parallel_connections_never_overbook_one_slot(self):
        quota.POLICIES[('groq','m')] = policy()
        def one(_):
            try:
                self.reserve()
                return True
            except quota.ReservationExhausted:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            result = list(executor.map(one, range(8)))
        self.assertEqual(result.count(True), 1)
        self.assertEqual(result.count(False), 7)

    def test_expired_invalid_or_unreadable_policy_fails_closed(self):
        for update in ({'expires_at':NOW-1}, {'rpm':True}, {'rpd':0},
                       {'source_url':'http://example.invalid'},
                       {'verified_at':NOW+100}):
            with self.subTest(update=update):
                quota.POLICIES[('groq','m')] = policy(**update)
                with self.assertRaises(quota.ReservationUnavailable):
                    self.reserve()
        quota.POLICIES[('groq','m')] = policy()
        with patch.object(quota.sqlite3, 'connect',
                          side_effect=quota.sqlite3.OperationalError('locked')):
            with self.assertRaises(quota.ReservationUnavailable):
                self.reserve()


if __name__ == '__main__':
    unittest.main()
