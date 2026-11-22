"""Faz 3: Finance `source_verification` dalı — modülü olmayan dal kapatıldı.

Bulgu: sözleşmede `source_verification` dalı vardı ama `modules: ()` ve
`entry_points` **başka dalın** dosyasını gösteriyordu (`modules/finance.py:dated_rate`,
`_safe_xml`). Yani "kaynak/tarih/evidence doğrulaması" ayrı bir dal değil, `dated_rate`
içine gömülü satırlardı; `validate()` bunu yakalamıyordu.

Düzeltme: doğrulama `modules/finance_verification.py`'ye taşındı, `dated_rate` aynı
fonksiyonu çağırıyor, `validate()` artık hayalet dalı (giriş noktası dalın modülünde
değil / modülde tanımlı değil) hata olarak bildiriyor.
"""
import hashlib
import json
import unittest
from datetime import date
from pathlib import Path

from modules import finance_domain, finance_verification

ROOT = Path(__file__).resolve().parents[1]


def response(body, url='https://api.frankfurter.dev/v2/rate/usd/try'):
    return {'body': body if isinstance(body, bytes) else json.dumps(body).encode(), 'url': url}


class RateEvidenceTests(unittest.TestCase):
    def test_valid_response_carries_the_three_required_evidence_fields(self):
        data = {'base': 'USD', 'quote': 'TRY', 'rate': 34.2, 'date': '2026-11-20'}
        evidence = finance_verification.verify_rate_evidence(
            data, response(data), base='USD', quote='TRY', on_date='2026-11-21')
        self.assertEqual(evidence['source'], 'https://api.frankfurter.dev/v2/rate/usd/try')
        self.assertEqual(evidence['data']['date'], '2026-11-20')
        self.assertIsInstance(evidence['fetched_at'], float)
        self.assertEqual(evidence['sha256'], hashlib.sha256(json.dumps(data).encode()).hexdigest())
        self.assertIn('banka', evidence['scope'])

    def test_mismatched_currency_is_rejected(self):
        data = {'base': 'EUR', 'quote': 'TRY', 'rate': 34.2, 'date': '2026-11-20'}
        with self.assertRaises(ValueError):
            finance_verification.verify_rate_evidence(data, response(data), base='USD', quote='TRY')

    def test_future_date_and_bad_rate_are_rejected(self):
        future = {'base': 'USD', 'quote': 'TRY', 'rate': 34.2, 'date': '2026-11-25'}
        with self.assertRaises(ValueError):
            finance_verification.verify_rate_evidence(future, response(future),
                                                      base='USD', quote='TRY', on_date='2026-11-20')
        for bad in (0, -1, 'abc', None, float('nan')):
            data = {'base': 'USD', 'quote': 'TRY', 'rate': bad, 'date': '2026-11-20'}
            with self.assertRaises(ValueError, msg=bad):
                finance_verification.verify_rate_evidence(data, response(data), base='USD', quote='TRY')

    def test_missing_or_insecure_source_is_rejected(self):
        data = {'base': 'USD', 'quote': 'TRY', 'rate': 34.2, 'date': '2026-11-20'}
        for broken in ({'body': b'{}'}, {'body': b'{}', 'url': 'http://x.test'},
                       {'body': b'', 'url': 'https://x.test'}):
            with self.assertRaises(ValueError, msg=broken):
                finance_verification.verify_rate_evidence(data, broken, base='USD', quote='TRY')

    def test_broken_body_never_reaches_validation(self):
        for raw in (b'<not json>', b'[]', b'"metin"', b'null'):
            with self.assertRaises(ValueError, msg=raw):
                finance_verification.parse_rate_body(raw)

    def test_verification_grants_no_effect(self):
        """Kaynak doğrulaması izin/efekt yetkisi üretmez (sözleşme değişmezi)."""
        data = {'base': 'USD', 'quote': 'TRY', 'rate': 34.2, 'date': '2026-11-20'}
        evidence = finance_verification.verify_rate_evidence(data, response(data), base='USD', quote='TRY')
        self.assertEqual(set(evidence), {'data', 'source', 'fetched_at', 'sha256', 'scope'})
        source = ROOT.joinpath('modules/finance_verification.py').read_text(encoding='utf-8')
        for forbidden in ('outbox', 'payment', 'transfer', 'requests.post', 'urllib'):
            self.assertNotIn(forbidden, source, forbidden)


class BranchContractTests(unittest.TestCase):
    def test_every_branch_has_its_own_module_and_real_entry_point(self):
        self.assertEqual(finance_domain.validate(), [])
        for name, branch in finance_domain.BRANCHES.items():
            self.assertTrue(branch['modules'], name)
            for entry in branch['entry_points']:
                self.assertIn(entry.partition(':')[0], branch['modules'], entry)

    def test_phantom_branch_is_reported(self):
        """Kaynak tarama: hayalet dal kuralı validate() içinde yaşıyor."""
        source = ROOT.joinpath('modules/finance_domain.py').read_text(encoding='utf-8')
        self.assertIn('giriş noktası bu dalın modülünde değil', source)
        self.assertIn('giriş noktası modülde tanımlı değil', source)

    def test_dated_rate_uses_the_single_verification_function(self):
        source = ROOT.joinpath('modules/finance.py').read_text(encoding='utf-8')
        self.assertIn('finance_verification.verify_rate_evidence', source)
        self.assertIn('finance_verification.parse_rate_body', source)
        # Doğrulama kuralları ikinci kez dated_rate içinde yaşamaz.
        self.assertNotIn("para birimleriyle eşleşmiyor", source)
        self.assertNotIn('sonraki kuru döndürdü', source)

    def test_money_effect_and_account_read_stay_closed(self):
        for kind in ('account_read', 'money_effect'):
            self.assertEqual(finance_domain.BOUNDARY[kind]['state'], 'closed', kind)
            with self.assertRaises(PermissionError):
                finance_domain.route(kind)
        self.assertEqual(finance_domain.route('market_data')['owner'], 'finance')


if __name__ == '__main__':
    unittest.main()
