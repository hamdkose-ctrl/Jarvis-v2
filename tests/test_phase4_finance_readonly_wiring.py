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

    def test_finance_worker_returns_trade_plan_draft_without_execution_fields(self):
        payload = {
            "ticker": "THYAO", "current_price": "105", "price_observed_at": "2026-10-27T10:00:00+00:00",
            "source": "Yahoo Finance", "evidence": [{"source": "Yahoo Finance", "observed_at": "2026-10-27T10:00:00+00:00"}],
            "candles": [
                {"date": "2026-10-25T10:00:00+00:00", "open": "100", "high": "108", "low": "96", "close": "104", "volume": "10"},
                {"date": "2026-10-26T10:00:00+00:00", "open": "104", "high": "112", "low": "99", "close": "106", "volume": "11"},
            ],
        }
        result = task_workers.run("alice", {"id": "finance-plan", "agent": "finance",
            "input": {"operation": "trade_plan_draft", "payload": json.dumps(payload)}, "execution": {}}, {})
        self.assertEqual(result["state"], "done")
        self.assertEqual(result["analysis"]["state"], "ready")
        self.assertNotIn("order", result["analysis"])
        self.assertNotIn("position_size", result["analysis"])


if __name__ == "__main__":
    unittest.main()
