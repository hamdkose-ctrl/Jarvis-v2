from decimal import Decimal
import unittest
from unittest.mock import patch

from modules import finance


class TypedFinanceAmountTests(unittest.TestCase):
    def test_typed_amount_is_preserved_as_a_decimal(self):
        request = finance.request_from_slots({
            "kind": "rate", "amount": "6", "source": "USD", "target": "TRY",
        })
        self.assertEqual(request["amount"], Decimal(6))
        self.assertEqual(request["source"], "USD")

    def test_typed_amount_uses_only_fake_rates(self):
        request = finance.request_from_slots({
            "kind": "rate", "amount": "6", "source": "USD", "target": "TRY",
        })
        with patch.object(finance, "rates",
                          return_value=({"USD": Decimal(40), "TRY": Decimal(1)}, "Taklit kaynak")) as rates:
            reply = finance.answer_request(request)
        self.assertIn("6 dolar", reply)
        self.assertIn("TL eder", reply)
        self.assertIn("Taklit kaynak", reply)
        self.assertNotIn("e-posta", reply)
        rates.assert_called_once_with(["USD", "TRY"])


if __name__ == "__main__":
    unittest.main()
