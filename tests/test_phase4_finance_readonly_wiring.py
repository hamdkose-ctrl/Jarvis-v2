import json
import unittest
from decimal import Decimal
from unittest.mock import patch

from modules import task_workers


class Phase4FinanceReadonlyWiringTests(unittest.TestCase):
    def test_finance_worker_uses_readonly_portfolio_summary_and_returns_disclaimer(self):
        positions = [{"ticker": "THYAO", "quantity": "2", "price": "100", "currency": "TRY"}]
        expected = {
            "positions": [{"ticker": "THYAO", "quantity": Decimal("2"), "price": Decimal("100"),
                           "currency": "TRY", "value": Decimal("200")}],
            "total_value": Decimal("200"),
            "assumptions": ["Salt-okunur özet.", "Bilgi amaçlıdır; yatırım tavsiyesi değildir."],
        }
        with patch("modules.finance_readonly.portfolio_summary", return_value=expected) as summary:
            result = task_workers.run("alice", {
                "id": "finance-1", "agent": "finance",
                "input": {"operation": "portfolio_summary", "payload": json.dumps(positions)},
                "execution": {},
            }, {})

        summary.assert_called_once_with(positions)
        self.assertEqual(result["state"], "done")
        self.assertEqual(result["analysis"]["total_value"], "200")
        self.assertIn("yatırım tavsiyesi değildir", result["disclaimer"])


if __name__ == "__main__":
    unittest.main()
