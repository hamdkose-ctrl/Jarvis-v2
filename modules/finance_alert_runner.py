"""Enjekte edilen fiyatlarla tek turluk alarm değerlendirmesi; ağ/zamanlayıcı yok."""
import time

from modules import finance_alerts, finance_alert_store
from modules.diagnostics import record_failure as _record_failure


def run_once(owner, price_getter, now=None) -> list[dict]:
    """Kullanıcının kurallarını değerlendirir, durumları saklar; yalnız tetikleri döndürür."""
    rules = finance_alert_store.list_rules(owner)
    moment = time.time() if now is None else now
    failed = object()
    prices = {}
    fired = []
    for rule in rules:
        try:
            key = (rule['kind'], rule['symbol'])
            if key not in prices:
                # Hata da önbellekte tutulur: aynı sembol bu turda yeniden istenmez.
                prices[key] = failed
                try:
                    prices[key] = price_getter(*key)
                except Exception:
                    _record_failure('modules/finance_alert_runner.py:price')
            price = prices[key]
        except (KeyError, TypeError):
            _record_failure('modules/finance_alert_runner.py:evaluate')
            continue
        if price is failed:
            continue
        try:
            previous = finance_alert_store.get_state(owner, rule['id'])
            result = finance_alerts.evaluate(rule, price, previous, moment)
        except (KeyError, TypeError, ValueError, OverflowError):
            _record_failure('modules/finance_alert_runner.py:evaluate')
            continue
        try:
            finance_alert_store.set_state(owner, rule['id'], result['state'])
        except ValueError:                      # kural bu arada silindi: tetik de geçersiz
            _record_failure('modules/finance_alert_runner.py:state')
            continue
        except OSError:                         # durum yazılamadı: tetik yine bildirilir, tur kesilmez
            _record_failure('modules/finance_alert_runner.py:state')
        if result['fire']:
            fired.append({**{key: rule[key] for key in ('id', 'kind', 'symbol', 'op', 'value')},
                          'reason': result['reason']})
    return fired
