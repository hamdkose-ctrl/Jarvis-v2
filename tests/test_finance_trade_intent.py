import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal


class FinanceTradeIntentTests(unittest.TestCase):
    def test_pass_intent_approval_is_exact_expiring_and_receipted(self):
        from modules import finance_trade_intent as trade
        now = datetime(2026, 10, 27, 10, tzinfo=timezone.utc)
        decision = {
            "decision": "PASS", "ticker": "THYAO",
            "plan": {"scenario": "gözlenen aralık içinde uzun senaryo", "used_price": Decimal("100"),
                     "stop": Decimal("90"), "targets": [Decimal("120")], "freshness": {"state": "fresh"},
                     "evidence": [{"source": "Yahoo Finance", "observed_at": "2026-10-27T10:00:00+00:00"}]},
            "position_size": Decimal("10"), "risk_amount": Decimal("100"),
            "risk_fraction": Decimal("0.01"), "reason_codes": [],
        }
        intent = trade.create(decision, owner="alice", intent_id="intent-1", created_at=now, ttl_seconds=300)
        approved = trade.approve(intent, owner="alice", receipt_id="approval-1", channel="chat",
                                 now=now + timedelta(seconds=1))
        self.assertTrue(trade.verify(approved, intent, owner="alice", now=now + timedelta(seconds=2)))


if __name__ == "__main__":
    unittest.main()
