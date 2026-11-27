"""POLICIES schema (T3): fields are written down, a missing field is never filled in."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import router_quota as quota

NOW = 1794300000.


def policy(**changes):
    row = {'source_url': 'https://provider.example/rate-limits',
           'verified_at': NOW - 60, 'expires_at': NOW + 2 * 86400,
           'rpm': 1, 'rpd': 2}
    row.update(changes)
    return row


class PolicySchemaTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        p = patch.object(quota, 'POLICIES', {})
        p.start(); self.addCleanup(p.stop)

    def refuse(self, row, *, provider='groq', model='m', message=None):
        quota.POLICIES[(provider, model)] = row
        with self.assertRaises(quota.ReservationUnavailable) as caught:
            quota.reserve('alice', provider, model, directory=self.directory, now=NOW)
        text = str(caught.exception)
        if message:
            self.assertIn(message, text)
        return text

    def assert_accepted(self, row):
        quota.POLICIES[('groq', 'm')] = row
        self.assertTrue(quota.reserve('alice', 'groq', 'm',
                                      directory=self.directory, now=NOW))

    def test_schema_lists_exactly_the_fields_it_enforces(self):
        self.assertEqual(set(quota.POLICY_REQUIRED) | set(quota.POLICY_OPTIONAL),
                         set(quota.POLICY_FIELDS))
        self.assertEqual(quota.POLICY_REQUIRED,
                         frozenset({'source_url', 'verified_at', 'expires_at',
                                    'rpm', 'rpd'}))

    def test_complete_row_without_token_limits_is_accepted(self):
        self.assert_accepted(policy())

    def test_each_missing_required_field_is_named(self):
        for field in sorted(quota.POLICY_REQUIRED):
            with self.subTest(field=field):
                row = policy()
                row.pop(field)
                text = self.refuse(row, message=field)
                self.assertIn('eksik', text)

    def test_unknown_field_is_refused(self):
        text = self.refuse(policy(rpmm=5), message='rpmm')
        self.assertIn('bilinmeyen', text)

    def test_validation_never_writes_defaults_into_the_row(self):
        row = policy()
        before = dict(row)
        self.assertEqual(quota.validate_policy('groq', 'm', row, NOW),
                         (1, 2, None, None))
        self.assertEqual(row, before)          # eksik tpm/tpd yerine 0 yazılmadı

    def test_row_identity_must_match_its_key(self):
        self.refuse(policy(provider='gemini'), message='provider')
        self.refuse(policy(model='other'), message='model')
        self.assert_accepted(policy(provider='groq', model='m'))

    def test_source_url_must_be_https_without_credentials(self):
        for url in ('http://provider.example/x', 'https://user:pw@provider.example/x',
                    'https:///x', 'file:///tmp/x', 42, None, ''):
            with self.subTest(url=url):
                self.refuse(policy(source_url=url), message='source_url')

    def test_validity_window_is_at_most_31_days_and_never_in_the_future(self):
        for changes in ({'expires_at': NOW - 1}, {'verified_at': NOW + 100},
                        {'expires_at': NOW + 32 * 86400}, {'verified_at': '2026'},
                        {'expires_at': True}):
            with self.subTest(changes=changes):
                self.refuse(policy(**changes), message='geçerliliği')

    def test_request_limits_ranges(self):
        for changes in ({'rpm': 0}, {'rpm': 5001}, {'rpd': 500001},
                        {'rpm': 3, 'rpd': 2}, {'rpm': True}, {'rpm': 1.0}):
            with self.subTest(changes=changes):
                self.refuse(policy(**changes), message='istek limitleri')

    def test_token_limits_are_all_or_nothing_and_ranged(self):
        self.refuse(policy(tpm=100), message='yarım')
        self.refuse(policy(tpd=100), message='yarım')
        for changes in ({'tpm': 100, 'tpd': 90}, {'tpm': 0, 'tpd': 10},
                        {'tpm': 10, 'tpd': 1_000_000_001}):
            with self.subTest(changes=changes):
                self.refuse(policy(**changes), message='token limitleri')
        self.assertEqual(quota.validate_policy('groq', 'm', policy(tpm=100, tpd=180), NOW),
                         (1, 2, 100, 180))

    def test_non_dict_row_fails_closed(self):
        self.refuse(['rpm'], message='geçersiz')

    def test_no_registered_policy_still_means_no_guess(self):
        self.assertIsNone(quota._policy('groq', 'm', NOW))
        self.assertFalse(quota.reserve('alice', 'groq', 'm',
                                       directory=self.directory, now=NOW))


if __name__ == '__main__':
    unittest.main()
