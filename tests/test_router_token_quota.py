"""Developer token-cap reservations; all data and model adapters are synthetic."""
import concurrent.futures
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from modules import router_quota as q, smart_router as router

NOW = 1794300000.

def policy(**changes):
    row = dict(rpm=5, rpd=9, tpm=100, tpd=180,
               source_url='https://provider.example/rates',
               verified_at=NOW-60, expires_at=NOW+2*86400)
    row.update(changes)
    return row

class AtomicTokenQuotaTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        p = patch.object(q, 'POLICIES', {('groq', 'exact'):policy()})
        p.start()
        self.addCleanup(p.stop)

    def reserve(self, units=60, *, owner='alice', now=NOW):
        return q.reserve(owner, 'groq', 'exact', directory=self.directory,
                         token_budget=units, now=now)

    def test_tpm_and_tpd_rolling_windows(self):
        self.assertTrue(self.reserve(60))
        with self.assertRaises(q.ReservationExhausted) as one:
            self.reserve(50)
        self.assertEqual(one.exception.retry_after, 60)
        self.assertTrue(self.reserve(50, now=NOW+60))
        self.assertTrue(self.reserve(60, now=NOW+120))
        with self.assertRaises(q.ReservationExhausted) as later:
            self.reserve(20, now=NOW+120)
        self.assertGreater(later.exception.retry_after, 60)
        self.assertTrue(self.reserve(60, now=NOW+86400))

    def test_invalid_or_missing_token_budget_refuses_before_db(self):
        for units in (None, 0, -1, True, 1.5, 2_000_001):
            with self.subTest(units=units), self.assertRaises(q.ReservationUnavailable):
                self.reserve(units)
        self.assertFalse((self.directory/'atomic_requests.sqlite3').exists())

    def test_expired_trusted_policy_still_fails_closed(self):
        with self.assertRaises(q.ReservationUnavailable):
            self.reserve(25, now=NOW+2*86400)
        self.assertFalse((self.directory/'atomic_requests.sqlite3').exists())

    def test_malformed_or_partial_token_policy_fails_closed(self):
        for bad in ({'tpm':True}, {'tpd':None}, {'tpm':None},
                    {'tpm':101, 'tpd':100}, {'tpm':0},
                    {'tpd':-1}, {'tpm':100_000_000}):
            with self.subTest(bad=bad):
                q.POLICIES[('groq','exact')] = policy(**bad)
                with self.assertRaises(q.ReservationUnavailable):
                    self.reserve(25)

    def test_legacy_request_counts_have_unknown_cost_not_zero(self):
        path=self.directory/'atomic_requests.sqlite3'
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE requests (owner TEXT, provider TEXT, '
                       'model TEXT, stamp REAL)')
            db.execute('INSERT INTO requests VALUES(?,?,?,?)',
                       ('alice','groq','exact',NOW))
        with self.assertRaises(q.ReservationUnavailable):
            self.reserve(25)
        # The unknown row may expire, but cannot be silently counted as free.
        self.assertTrue(self.reserve(25, now=NOW+86400))

    def test_switching_from_request_only_policy_does_not_erase_usage(self):
        q.POLICIES[('groq','exact')]=policy(tpm=None,tpd=None)
        self.assertTrue(self.reserve(None))
        q.POLICIES[('groq','exact')]=policy()
        with self.assertRaises(q.ReservationUnavailable):
            self.reserve(25)
        self.assertTrue(self.reserve(25,now=NOW+86400))

    def test_owner_and_exact_model_isolation(self):
        self.assertTrue(self.reserve(95))
        self.assertTrue(self.reserve(95,owner='bob'))
        q.POLICIES[('groq','other')]=policy()
        self.assertTrue(q.reserve('alice','groq','other',
                                  directory=self.directory,now=NOW,token_budget=95))
        with self.assertRaises(q.ReservationExhausted):
            self.reserve(15)

    def test_concurrent_reservations_cannot_oversubscribe_tokens(self):
        q.POLICIES[('groq','exact')]=policy(tpm=50,tpd=50,rpm=8,rpd=8)
        def worker(_):
            try:
                return self.reserve(25)
            except q.ReservationExhausted:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            result=list(pool.map(worker,range(8)))
        self.assertEqual(result.count(True),2)

    def test_router_skips_model_without_trusted_budget(self):
        adapter=Mock(return_value='ok')
        specs=(router.ModelSpec('groq','exact'),)
        with patch.object(router,'plan',return_value=router.RoutePlan(specs,(),2)), \
             patch.object(router,'_STORE',self.directory), \
             patch.object(router,'_HEALTH',{}):
            with self.assertRaises(Exception):
                router.run_request(router.ModelRequest(owner='alice'),adapter)
            self.assertEqual(router.status('alice')['last']['skipped'][0]['reason_code'],
                             'PROVIDER_LOCAL_QUOTA_UNAVAILABLE')
        adapter.assert_not_called()

    def test_router_accepts_trusted_bound_only_when_output_fits(self):
        with self.assertRaises(ValueError):
            router.plan(router.ModelRequest(owner='alice',max_output_tokens=100,
                                            token_budget=50))
        adapter=Mock(return_value='ok')
        specs=(router.ModelSpec('groq','exact'),)
        # The fixture's verified policy is anchored to NOW. Exercise the
        # real SQLite quota reservation at that same synthetic instant:
        # otherwise this test starts failing just because wall time passed
        # expires_at, not because the token-budget acceptance regressed.
        real_reserve = q.reserve
        def reserve_at_fixture_clock(*args, **kwargs):
            return real_reserve(*args, now=NOW, **kwargs)
        with patch.object(router,'plan',return_value=router.RoutePlan(specs,(),2)), \
             patch.object(router,'_STORE',self.directory), \
             patch.object(router,'_HEALTH',{}), \
             patch.object(q,'reserve',side_effect=reserve_at_fixture_clock):
            result=router.run_request(router.ModelRequest(owner='alice',
                       max_output_tokens=25,token_budget=95),adapter)
        self.assertEqual(result.text,'ok')
        adapter.assert_called_once()

if __name__ == '__main__':
    unittest.main()
