"""Modelsiz finans alarm komutları; kullanıcı deposu geçici dizinde."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from modules import finance_alert_store as store
from modules import finance_alert_commands as commands

class FinanceAlarmCommandsTests(unittest.TestCase):
    def setUp(self):
        td=tempfile.TemporaryDirectory();self.addCleanup(td.cleanup)
        self.enterContext(patch.object(store,'_ROOT',Path(td.name)/'rules'))
    def typed(self, owner, payload):
        from types import SimpleNamespace
        from modules import brain_core_map, engine_intents
        plan = brain_core_map.core_plan("finance.alert.manage", payload)
        self.assertIsNotNone(plan)
        runtime = SimpleNamespace(profile=SimpleNamespace(slug=owner))
        with patch("modules.requests_state.check"):
            return engine_intents.dispatch(runtime, *plan, "typed alarm", "typed alarm")

    def test_add_list_delete_and_owner_separation(self):
        self.assertIn("Alarm", self.typed("alice", {
            "operation": "add", "asset": "USD", "value": "33",
            "direction": "above"}))
        self.assertEqual(store.list_rules("alice")[0]["op"], "above")
        self.assertEqual(store.list_rules("bob"), [])
        self.assertIn("USD", self.typed("alice", {"operation": "list"}))
        self.assertIn("silindi", self.typed("alice", {"operation": "delete", "index": 1}))
        self.assertEqual(store.list_rules("alice"), [])

    def test_variants_duplicate_and_invalid_threshold(self):
        for asset, kind, symbol in (
            ("dolar", "doviz", "USD"), ("BTC", "kripto", "BTC"),
            ("gram altın", "altin", "GRAM"),
            ("THYAO hissesi", "hisse", "THYAO")):
            with self.subTest(asset=asset):
                self.typed("alice", {"operation": "add", "asset": asset,
                                     "value": "33,50", "direction": "below"})
                rule = store.list_rules("alice")[-1]
                self.assertEqual((rule["kind"], rule["symbol"], rule["op"],
                                  rule["value"]), (kind, symbol, "below", 33.5))
        self.typed("alice", {"operation": "add", "asset": "dolar",
                             "value": "33,50", "direction": "below"})
        self.assertEqual(len(store.list_rules("alice")), 4)
        store.add_rule("alice", {"kind": "doviz", "symbol": "EUR",
                                 "op": "pct_up", "value": 5})
        listing = self.typed("alice", {"operation": "list"})
        self.assertNotIn("pct_up", listing)
        self.assertIn("%5", listing)
        self.assertIn("33,5 TL", listing)
        from modules import brain_core_map
        self.assertIsNone(brain_core_map.core_plan(
            "finance.alert.manage",
            {"operation": "add", "asset": "USD", "value": "0", "direction": "above"}))

    def test_retired_raw_alarm_parser_has_no_direct_caller(self):
        self.assertFalse(hasattr(commands, "handle"))
        self.assertFalse(hasattr(commands, "matches"))
        self.assertEqual(store.list_rules("alice"), [])

    def test_invalid_delete_and_path(self):
        self.assertIn("yok", self.typed("alice", {"operation": "delete", "index": 20}))
        with self.assertRaises(ValueError):
            self.typed("../bob", {"operation": "list"})

    def test_core_bound_alarm_add_list_delete_and_owner_separation(self):
        from types import SimpleNamespace
        from modules import brain_core_map, engine_intents
        runtime = SimpleNamespace(profile=SimpleNamespace(slug="alice"))
        def run(arguments, sentence):
            plan = brain_core_map.core_plan("finance.alert.manage", arguments)
            self.assertIsNotNone(plan)
            with patch("modules.requests_state.check"):
                return engine_intents.dispatch(runtime, *plan,
                                               sentence, sentence.casefold())
        self.assertIn("Alarm kaydedildi", run(
            {"operation": "add", "asset": "USD", "value": "33,50",
             "direction": "above"}, "USD 33,50 TL üstüne çıkarsa haber ver"))
        self.assertEqual(store.list_rules("alice")[0]["value"], 33.5)
        self.assertEqual(store.list_rules("bob"), [])
        self.assertIn("USD", run({"operation": "list"}, "alarmlarım"))
        self.assertIn("silindi", run({"operation": "delete", "index": 1},
                                     "alarmı sil 1"))
        self.assertEqual(store.list_rules("alice"), [])

    def test_core_rejects_guessed_or_invalid_finance_alarm_payload(self):
        from modules import brain_core_map
        for args in (
            {"operation": "add", "asset": "USD", "value": "0",
             "direction": "above"},
            {"operation": "add", "asset": "USD", "value": "12",
             "direction": "trade"},
            {"operation": "add", "asset": "USD", "value": "12",
             "direction": "below", "owner": "bob"},
            {"operation": "add", "asset": "AAPL", "value": "33",
             "direction": "above"},
            {"operation": "delete", "index": "1"},
            {"operation": "delete", "index": 0},
            {"operation": "delete", "rule_id": "fake"},
            {"operation": "list", "index": 1},
        ):
            with self.subTest(args=args):
                self.assertIsNone(brain_core_map.core_plan("finance.alert.manage", args))
        self.assertEqual(store.list_rules("alice"), [])


if __name__ == '__main__':
    unittest.main()
