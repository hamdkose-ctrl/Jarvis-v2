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

    def test_trade_plan_uses_fresh_evidenced_prices_and_observed_range(self):
        now = datetime(2026, 10, 27, 10, tzinfo=timezone.utc)
        plan = finance.trade_plan_draft({
            "ticker": "THYAO", "current_price": "105", "price_observed_at": now.isoformat(),
            "source": "Yahoo Finance", "evidence": [{"source": "Yahoo Finance", "observed_at": now.isoformat()}],
            "candles": [
                {"date": "2026-10-25T10:00:00+00:00", "open": "100", "high": "108", "low": "96", "close": "104", "volume": "10"},
                {"date": "2026-10-26T10:00:00+00:00", "open": "104", "high": "112", "low": "99", "close": "106", "volume": "11"},
            ],
        }, now=now)
        self.assertEqual(plan["state"], "ready")
        self.assertEqual(plan["ticker"], "THYAO")
        self.assertEqual(plan["used_price"], Decimal("105"))
        self.assertEqual(plan["entry_zone"], {"low": Decimal("99"), "high": Decimal("106")})
        self.assertEqual(plan["stop"], Decimal("96"))
        self.assertEqual(plan["targets"], [Decimal("112")])
        self.assertEqual(plan["method"], "son iki doğrulanmış mumun gözlenen aralığı")
        self.assertEqual(plan["evidence"][0]["source"], "Yahoo Finance")
        self.assertTrue(plan["assumptions"])

    def test_trade_plan_never_invents_levels_when_evidence_or_freshness_is_missing(self):
        now = datetime(2026, 10, 27, 10, tzinfo=timezone.utc)
        missing = finance.trade_plan_draft({"ticker": "THYAO"}, now=now)
        self.assertEqual(missing["state"], "incomplete")
        self.assertIsNone(missing["stop"])
        self.assertEqual(missing["targets"], [])
        self.assertTrue(missing["missing_data"])

        stale = finance.trade_plan_draft({
            "ticker": "THYAO", "current_price": "105", "price_observed_at": "2026-10-20T10:00:00+00:00",
            "source": "Yahoo Finance", "evidence": [{"source": "Yahoo Finance", "observed_at": "2026-10-20T10:00:00+00:00"}],
            "candles": [{"date": "2026-10-20T10:00:00+00:00", "open": "100", "high": "112", "low": "96", "close": "105", "volume": "1"}],
        }, now=now)
        self.assertEqual(stale["state"], "incomplete")
        self.assertEqual(stale["freshness"]["state"], "stale")
        self.assertIsNone(stale["entry_zone"])

    def test_trade_plan_is_deterministic_and_read_only(self):
        now = datetime(2026, 10, 27, 10, tzinfo=timezone.utc)
        payload = {
            "ticker": "THYAO", "current_price": "105", "price_observed_at": now.isoformat(),
            "source": "Yahoo Finance", "evidence": [{"source": "Yahoo Finance", "observed_at": now.isoformat()}],
            "candles": [
                {"date": "2026-10-25T10:00:00+00:00", "open": "100", "high": "108", "low": "96", "close": "104", "volume": "10"},
                {"date": "2026-10-26T10:00:00+00:00", "open": "104", "high": "112", "low": "99", "close": "106", "volume": "11"},
            ],
        }
        self.assertEqual(finance.trade_plan_draft(payload, now=now), finance.trade_plan_draft(payload, now=now))

    def test_trade_plan_risk_checklist_reports_observations_without_pass_block(self):
        plan = {
            "state": "incomplete", "ticker": "THYAO", "freshness": {"state": "stale"},
            "stop": None, "targets": [], "risk_reward": None,
            "missing_data": ["güncel fiyat tazeliği", "doğrulanmış kaynak kanıtı"],
        }
        checklist = finance.trade_plan_risk_checklist(plan)
        self.assertEqual(checklist["state"], "observed")
        self.assertEqual(checklist["ticker"], "THYAO")
        self.assertEqual([item["code"] for item in checklist["observations"]], [
            "STALE_DATA", "STOP_UNAVAILABLE", "TARGET_UNAVAILABLE", "RISK_REWARD_UNAVAILABLE",
            "MISSING_EVIDENCE",
        ])
        self.assertNotIn("pass", checklist)
        self.assertNotIn("block", checklist)
        self.assertTrue(checklist["assumptions"])

    def test_trade_plan_risk_checklist_is_deterministic_for_ready_plan(self):
        plan = {
            "state": "ready", "ticker": "THYAO", "freshness": {"state": "fresh"},
            "stop": Decimal("96"), "targets": [Decimal("112")], "risk_reward": Decimal("1.5"),
            "missing_data": [],
        }
        first = finance.trade_plan_risk_checklist(plan)
        self.assertEqual(first, finance.trade_plan_risk_checklist(plan))
        self.assertEqual(first["observations"], [])


if __name__ == "__main__":
    unittest.main()
