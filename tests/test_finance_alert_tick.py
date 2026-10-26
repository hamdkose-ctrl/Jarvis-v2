"""Alarm turu gerçek ağa/saate/kullanıcı dizinine dokunmaz."""
from pathlib import Path
import tempfile
from datetime import datetime,timezone
import unittest
from unittest.mock import Mock,patch
from modules import watcher, finance_alert_tick as alert_tick, finance_alert_store as store, finance_alert_runner as runner

class FinanceAlarmTickTests(unittest.TestCase):
    def setUp(self):
        td=tempfile.TemporaryDirectory();self.addCleanup(td.cleanup)
        root=Path(td.name)
        self.enterContext(patch.object(store,'_ROOT',root/'rules'))
        self.enterContext(patch.object(alert_tick,'_ROOT',root/'ticks',create=True))
        self.emit=Mock();self.price=Mock(return_value=34)
        self.day=datetime(2026,1,19,12,tzinfo=timezone.utc).timestamp()  # 15:00 Istanbul
        self.rule=store.add_rule('alice',{'kind':'doviz','symbol':'USD','op':'above','value':33})
    def tick(self,now,owner='alice'):
        watcher.finance_tick(owner,self.emit,now=now,price_getter=self.price)
    def test_trigger_and_throttle_then_due_interval(self):
        self.tick(self.day)
        self.assertEqual(self.price.call_count,1)
        self.assertIn('USD',self.emit.call_args.args[0])
        self.tick(self.day+20);self.tick(self.day+60)
        self.assertEqual(self.price.call_count,1)
        self.tick(self.day+300)
        self.assertEqual(self.price.call_count,2)
        self.assertEqual(self.emit.call_count,1)
    def test_network_failure_silent_and_other_symbol_survives(self):
        store.add_rule('alice',{'kind':'kripto','symbol':'BTC','op':'above','value':30})
        self.price.side_effect=lambda kind,symbol:(_ for _ in ()).throw(OSError('network')) if symbol=='USD' else 40
        self.tick(self.day)
        self.assertEqual(self.emit.call_count,1)
        self.assertIn('BTC',self.emit.call_args.args[0])
    def test_quiet_alarm_survives_restart_and_emit_failure(self):
        night=self.day+9*3600  # 00:00 Istanbul
        self.tick(night)
        self.emit.assert_not_called()
        self.assertTrue(list(alert_tick._ROOT.glob('alice.json')))
        self.emit.side_effect=OSError('ui')
        self.tick(night+8*3600)
        self.emit.side_effect=None
        self.tick(night+8*3600+60)
        self.assertIn('USD',self.emit.call_args.args[0])
        count=self.emit.call_count
        self.tick(night+8*3600+120)
        self.assertEqual(self.emit.call_count,count)
    def test_pending_deleted_rule_not_sent_and_users_are_separate(self):
        night=self.day+9*3600;self.tick(night)
        store.remove_rule('alice',self.rule['id'])
        self.tick(night+8*3600)
        self.emit.assert_not_called()
        self.tick(self.day,'bob')
        self.emit.assert_not_called()
    def test_existing_runner_is_used_and_nondue_batch_not_evaluated(self):
        with patch.object(runner,'run_once',wraps=runner.run_once) as run:
            self.tick(self.day);self.tick(self.day+60)
            self.assertEqual(run.call_count,1)
    def test_real_price_adapter_uses_existing_numeric_sources(self):
        from decimal import Decimal
        from modules import finance
        with patch.object(finance,'rates',return_value=({'USD':Decimal('34')},'TCMB')),patch.object(finance,'_market',return_value={'last':Decimal('50')}) as market,patch.object(finance,'_yahoo',return_value={'last':Decimal('60')}):
            self.assertEqual(watcher._finance_price('doviz','USD'),34)
            self.assertEqual(watcher._finance_price('kripto','BTC'),50)
            market.assert_called_with('BTCTRY')
            watcher._finance_price('altin','GRAM')
            market.assert_called_with('PAXGTRY')
            self.assertEqual(watcher._finance_price('hisse','THYAO'),60)
    def test_tick_path_and_corrupt_state_fail_closed(self):
        alert_tick._ROOT.mkdir(parents=True)
        (alert_tick._ROOT/'alice.json').write_text('{broken')
        self.tick(self.day)
        self.price.assert_not_called()
        with self.assertRaises(ValueError):watcher.finance_tick('../bob',self.emit,now=self.day,price_getter=self.price)

    def test_loop_checks_finance_without_folder_rules_or_model(self):
        from types import SimpleNamespace
        owner=SimpleNamespace(slug='alice',data={})
        runtime=SimpleNamespace(stop_event=SimpleNamespace(wait=Mock(side_effect=[False,True])),
            pc_profile=Mock(return_value=owner),_llm=Mock(),_emit_for=Mock())
        with patch.object(watcher,'load',return_value=[]),patch.object(alert_tick,'_price',return_value=34),patch.object(watcher.time,'time',return_value=self.day):
            watcher.loop(runtime)
        runtime._emit_for.assert_called_once()
        self.assertIs(runtime._emit_for.call_args.args[0],owner)
        runtime._llm.set_user_context.assert_not_called()

    def test_pending_write_failure_recovers_consumed_trigger(self):
        original=alert_tick._save
        def fail_pending(path,state):
            if state.get('pending'):
                raise OSError('disk pending write')
            original(path,state)
        with patch.object(alert_tick,'_save',side_effect=fail_pending):
            self.tick(self.day)
        self.assertIsNotNone(store.get_state('alice',self.rule['id'])['fired_at'])
        self.emit.assert_not_called()
        self.tick(self.day+60)
        self.emit.assert_called_once()
        self.assertIn('USD',self.emit.call_args.args[0])
        self.assertEqual(self.price.call_count,1,'kurtarma ağı yeniden çağırmaz ve kontrol aralığını korur')

    def test_bad_percentage_previous_zero_does_not_block_other_rules(self):
        row=store.add_rule('alice',{'kind':'kripto','symbol':'BTC','op':'pct_up','value':5})
        store.set_state('alice',row['id'],{'price':0,'fired_at':None})
        self.tick(self.day)
        self.assertEqual(self.emit.call_count,1)
        self.assertIn('USD',self.emit.call_args.args[0])
        self.tick(self.day+300)
        self.assertGreaterEqual(self.price.call_count,4)

    def test_new_rule_waits_for_safe_common_batch(self):
        self.tick(self.day)
        store.add_rule('alice',{'kind':'doviz','symbol':'EUR','op':'above','value':33})
        self.tick(self.day+60)
        self.assertEqual(self.price.call_count,1)
        self.tick(self.day+300)
        self.assertEqual(self.price.call_count,3)
        self.assertIn('EUR',self.emit.call_args.args[0])
