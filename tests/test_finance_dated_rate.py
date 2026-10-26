import json
import unittest

from modules import finance


class FinanceDatedRateTests(unittest.TestCase):
    def test_dated_rate_returns_verified_finance_evidence(self):
        body = json.dumps({
            'base': 'USD', 'quote': 'TRY', 'rate': 34.25, 'date': '2026-01-15',
        }).encode('utf-8')

        result = finance.dated_rate(
            'alice', 'USD', 'TRY', '2026-01-15',
            fetcher=lambda _url: {'url': 'https://example.test/rate', 'body': body},
        )

        self.assertEqual(result['data']['rate'], 34.25)
        self.assertEqual(result['source'], 'https://example.test/rate')
        self.assertIn('Günlük kaynak kuru', result['scope'])


if __name__ == '__main__':
    unittest.main()
