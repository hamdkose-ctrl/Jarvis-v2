import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from modules import finance_readonly as finance


class FinanceReadonlyTests(unittest.TestCase):
    def test_ohlcv_rejects_invalid_candles_and_marks_freshness(self):
        now = datetime.now(timezone.utc)
        rows = finance.normalize_ohlcv([{
            "date": now.isoformat(), "open": "10", "high": "12", "low": "9",
            "close": "11", "volume": "100",
        }])
        self.assertEqual(rows[0]["close"], Decimal("11"))
        self.assertEqual(finance.freshness(rows[0]["observed_at"], now=now)["state"], "fresh")

    def test_comparison_and_portfolio_keep_assumptions_visible(self):
        comparison = finance.compare_equities({
            "AAA": {"price": "10", "market_cap": "100", "pe": "5"},
            "BBB": {"price": "20", "market_cap": "200", "pe": "8"},
        })
        self.assertEqual(comparison["rows"][0]["ticker"], "AAA")
        portfolio = finance.portfolio_summary([
            {"ticker": "AAA", "quantity": "2", "price": "10", "currency": "TRY"}
        ])
        self.assertEqual(portfolio["total_value"], Decimal("20"))
        self.assertIn("fiyat", portfolio["assumptions"][0])

    def test_evidence_and_valuation_are_not_investment_advice(self):
        pack = finance.evidence_pack("AAA", [{"source": "Yahoo Finance", "observed_at": "2026-10-26T00:00:00+00:00"}])
        self.assertEqual(pack["disclaimer"], finance.NOT_INVESTMENT_ADVICE)
        dcf = finance.dcf({"free_cash_flow": "100", "discount_rate": "0.1", "terminal_growth": "0.03"})
        self.assertGreater(dcf["enterprise_value"], Decimal("0"))
        with self.assertRaises(finance.FinanceReadonlyError):
            finance.dcf({"free_cash_flow": "100", "discount_rate": "0.03", "terminal_growth": "0.03"})

    def test_lbo_and_ticker_validation_are_bounded(self):
        self.assertEqual(finance.validate_ticker("thyao"), "THYAO")
        model = finance.lbo({"entry_equity": "100", "debt": "50", "exit_multiple": "8", "ebitda": "30"})
        self.assertIn("equity_value", model)
        with self.assertRaises(finance.FinanceReadonlyError):
            finance.validate_ticker("../../bad")


if __name__ == "__main__":
    unittest.main()
