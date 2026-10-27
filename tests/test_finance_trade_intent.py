import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
from unittest.mock import patch


class FinanceTradeIntentTests(unittest.TestCase):
    def decision(self):
        return {
            "decision": "PASS", "ticker": "THYAO",
            "plan": {"scenario": "gözlenen aralık içinde uzun senaryo", "used_price": Decimal("100"), "stop": Decimal("90"),
                     "targets": [Decimal("120")], "freshness": {"state": "fresh"},
                     "evidence": [{"source": "Yahoo Finance", "observed_at": "2026-10-27T10:00:00+00:00"}]},
            "position_size": Decimal("10"), "risk_amount": Decimal("100"),
            "risk_fraction": Decimal("0.01"), "reason_codes": [],
        }

    def test_pass_intent_approval_is_exact_expiring_and_receipted(self):
        from modules import finance_trade_intent as trade
        now = datetime(2026, 10, 27, 10, tzinfo=timezone.utc)
        intent = trade.create(self.decision(), owner="alice", intent_id="intent-1",
                              created_at=now, ttl_seconds=300)
        self.assertEqual(intent["state"], "pending_approval")
        self.assertEqual(intent["ticker"], "THYAO")
        self.assertEqual(intent["position_size"], "10")
        approved = trade.approve(intent, owner="alice", receipt_id="approval-1",
                                 channel="chat", now=now + timedelta(seconds=1))
        self.assertEqual(approved["state"], "approved")
        self.assertEqual(approved["receipt"]["intent_fingerprint"], intent["fingerprint"])
        self.assertTrue(trade.verify(approved, intent, owner="alice", now=now + timedelta(seconds=2)))

    def test_block_decision_never_creates_an_intent(self):
        from modules import finance_trade_intent as trade
        with self.assertRaises(trade.TradeIntentError):
            trade.create({**self.decision(), "decision": "BLOCK"}, owner="alice", intent_id="intent-1",
                         created_at=datetime(2026, 10, 27, tzinfo=timezone.utc), ttl_seconds=300)

    def test_expiry_revoke_owner_mismatch_and_replay_fail_closed(self):
        from modules import finance_trade_intent as trade
        now = datetime(2026, 10, 27, 10, tzinfo=timezone.utc)
        intent = trade.create(self.decision(), owner="alice", intent_id="intent-1", created_at=now, ttl_seconds=10)
        approved = trade.approve(intent, owner="alice", receipt_id="approval-1", channel="web", now=now)
        self.assertFalse(trade.verify(approved, intent, owner="bob", now=now))
        self.assertFalse(trade.verify(approved, intent, owner="alice", now=now + timedelta(seconds=10)))
        revoked = trade.revoke(approved, owner="alice", now=now + timedelta(seconds=1))
        self.assertFalse(trade.verify(revoked, intent, owner="alice", now=now + timedelta(seconds=2)))
        consumed = trade.consume(approved, intent, owner="alice", now=now + timedelta(seconds=2))
        self.assertFalse(trade.verify(consumed, intent, owner="alice", now=now + timedelta(seconds=3)))
        with self.assertRaises(trade.TradeIntentError):
            trade.consume(consumed, intent, owner="alice", now=now + timedelta(seconds=3))

    def test_any_bound_plan_change_invalidates_approval_without_execution_fields(self):
        from modules import finance_trade_intent as trade
        now = datetime(2026, 10, 27, 10, tzinfo=timezone.utc)
        intent = trade.create(self.decision(), owner="alice", intent_id="intent-1", created_at=now, ttl_seconds=300)
        approved = trade.approve(intent, owner="alice", receipt_id="approval-1", channel="chat", now=now)
        for key, replacement in (("entry", "101"), ("stop", "89"), ("targets", ["121"]),
                                 ("position_size", "11"), ("plan_fingerprint", "0" * 64)):
            changed = dict(intent)
            changed[key] = replacement
            self.assertFalse(trade.verify(approved, changed, owner="alice", now=now), key)
        self.assertNotIn("execution", approved)
        self.assertNotIn("permission", approved)
        self.assertNotIn("order", approved)
        self.assertNotIn("broker", approved)

    def test_receipt_journal_is_owner_scoped_and_persists_revoke(self):
        from modules import finance_trade_intent as trade, service_store, llm
        now = datetime(2026, 10, 27, 10, tzinfo=timezone.utc)
        intent = trade.create(self.decision(), owner="alice", intent_id="intent-1", created_at=now, ttl_seconds=300)
        token = llm._key_context.set("alice")
        try:
            with tempfile.TemporaryDirectory() as td, patch.object(service_store, "ROOT", Path(td)):
                journal = trade.ApprovalJournal()
                recorded = journal.record(intent, owner="alice", receipt_id="approval-1", channel="web", now=now)
                self.assertEqual(journal.get("alice", "approval-1"), recorded)
                revoked = journal.revoke("alice", "approval-1", now=now + timedelta(seconds=1))
                self.assertEqual(revoked["receipt"]["state"], "revoked")
                with self.assertRaises(trade.TradeIntentError):
                    journal.get("bob", "approval-1")
        finally:
            llm._key_context.reset(token)


if __name__ == "__main__":
    unittest.main()
