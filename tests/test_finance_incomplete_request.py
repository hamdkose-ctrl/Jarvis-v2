"""Eksik alanlı kur/altın isteği turu düşürmemeli.

Canlı çökme (23 Kasım 22:33): model "asset" alanını verdi ama kind/target/amount
vermedi; finance._asset_answer KeyError attı, Core handoff CORE_HANDLER_FAILED
oldu ve kullanıcı hiç cevap alamadı (log: finance.py:331:_asset_answer KeyError).
Kural: eksik alan tahmin edilmez, tek cümleyle geri sorulur.
"""
import unittest
from unittest.mock import patch

from modules import finance


class IncompleteRequest(unittest.TestCase):
    def test_asset_without_kind_asks_back(self):
        reply = finance.answer_request({'asset': 'GOLD'})
        self.assertIn('anlayamadım', reply)
        self.assertNotIn('Traceback', reply)

    def test_empty_request_asks_back(self):
        reply = finance.answer_request({})
        self.assertIn('anlayamadım', reply)

    def test_non_dict_does_not_crash(self):
        self.assertIn('anlayamadım', finance.answer_request(None))

    def test_missing_list_key_is_not_keyerror(self):
        # 'list' anahtarı yoksa kod eskiden KeyError atıyordu (satır 390).
        reply = finance.answer_request({'source': None, 'target': None})
        self.assertIn('anlayamadım', reply)

    def test_every_answer_is_a_string(self):
        # Ağ yok: kur/piyasa gerçekten çekilirse test yavaş ve kararsız olur.
        from decimal import Decimal
        with patch.object(finance, "rates", return_value=({"USD": Decimal("40"), "TRY": Decimal(1)}, "test")),              patch.object(finance, "_asset_answer", return_value="tam"):
            for request in ({}, {'asset': 'GOLD'}, {'asset': 'USD', 'kind': 'gram'},
                            {'source': 'USD'}, {'list': []}):
                self.assertIsInstance(finance.answer_request(request), str, request)

    def test_complete_asset_request_still_reaches_market_path(self):
        """Eksik alan kontrolü tam isteği engellemez: piyasa yoluna girer."""
        import modules.finance as mod
        calls = {}
        original = mod._asset_answer
        def _fake(request):
            calls['hit'] = True
            return 'tam'
        mod._asset_answer = _fake
        try:
            reply = finance.answer_request({'asset': 'USD', 'kind': 'gram',
                                            'target': 'TRY', 'amount': 1})
        finally:
            mod._asset_answer = original
        self.assertEqual(reply, 'tam')
        self.assertTrue(calls.get('hit'))


if __name__ == "__main__":
    unittest.main()
