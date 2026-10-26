"""Finance alarm polling and durable recovery; folder watcher only schedules it."""
import json
import os
import re
import threading
import time
from pathlib import Path
from config import DATA_DIR
from modules.diagnostics import record_failure as _record_failure

# Finans alarmı: fiyat kontrolü yalnız bu döngüde, kullanıcı başına en sık 60 saniye.
_ROOT = DATA_DIR / 'finance_alert_ticks'
_LOCK = threading.RLock()


def _path(owner):
    if not isinstance(owner, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,99}', owner) or owner in {'con','prn','aux','nul'} or re.fullmatch(r'(com|lpt)[1-9]',owner):
        raise ValueError('Geçerli kullanıcı slug değeri gerekli.')
    path = _ROOT / (owner + '.json')
    for item in (path, _ROOT, *_ROOT.parents):
        if item.is_symlink() or (hasattr(item,'is_junction') and item.is_junction()):
            raise ValueError('Alarm tarama yolu sembolik bağ olamaz.')
    return path


def _save(path, state):
    import tempfile
    path.parent.mkdir(parents=True,exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as handle:
            name = handle.name
            json.dump(state,handle,ensure_ascii=False,allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name,path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def _price(kind, symbol):
    from modules import finance
    return finance.quote(kind, symbol)


def _recover(owner, path, state, current):
    """Yarım kalan salt fiyat değerlendirmesini kayıtlı girdilerden tamamla."""
    from modules import finance_alerts, finance_alert_store
    intents = state.get('inflight', [])
    if not isinstance(intents,list) or len(intents) > 20:
        raise ValueError('Geçersiz alarm kurtarma kaydı.')
    results = []
    for item in intents:
        rule, price, previous, moment = item['rule'], item['price'], item['previous'], item['at']
        if rule['id'] not in current:
            continue
        try:
            result = finance_alerts.evaluate(rule, price, previous, moment)
        except (ValueError, TypeError, OverflowError):
            _record_failure('modules/finance_alert_tick.py:finance_recover_rule')
            state['checked'][rule['id']] = {'checked_at':moment}
            continue
        if result['fire'] and rule['id'] not in state['pending']:
            state['pending'][rule['id']] = {'rule':rule,'price':price}
        results.append((rule['id'],previous,result['state']))
        state['checked'][rule['id']] = {'checked_at':moment}
    if not intents:
        return
    _save(path,state)  # pending diskte olmadan tetik durumunu tüketme
    for ident, previous, result in results:
        existing = finance_alert_store.get_state(owner,ident)
        if existing == previous or existing == result:
            finance_alert_store.set_state(owner,ident,result)
    state['inflight'] = []
    _save(path,state)


def tick(owner, emit, *, now=None, price_getter=None):
    """Kalıcı sessiz-saat kuyruğu; ağ/model testte enjekte edilir.

    run_once kural seçimi almadığından kontroller güvenli ortak turda yapılır:
    yeni eklenen kural eski kuralların 300 sn aralığını bekleyebilir.
    """
    from modules import finance_alert_store, finance_alert_runner, finance_alert_schedule
    import math
    moment = time.time() if now is None else now
    if type(moment) not in (float,int) or not math.isfinite(moment) or moment < 0:
        raise ValueError('Geçersiz alarm zamanı.')
    path = _path(owner)
    with _LOCK:
        try:
            try:
                if path.stat().st_size > 500_000:
                    raise ValueError('Alarm tarama dosyası çok büyük.')
                state = json.loads(path.read_text(encoding='utf-8'))
            except FileNotFoundError:
                state = {'last_turn':None,'checked':{},'pending':{}}
            if not isinstance(state,dict) or not isinstance(state.get('checked'),dict) or not isinstance(state.get('pending'),dict):
                raise ValueError('Geçersiz alarm tarama durumu.')
            rules = finance_alert_store.list_rules(owner)
            current = {r['id']:r for r in rules}
            state['pending'] = {key:row for key,row in state['pending'].items() if key in current}
            state['checked'] = {key:row for key,row in state['checked'].items() if key in current}
            _recover(owner,path,state,current)
            last = state.get('last_turn')
            if last is not None:
                if type(last) not in (int,float) or not math.isfinite(last) or last < 0:
                    raise ValueError('Geçersiz son kontrol zamanı.')
                if moment-last < 60:
                    return
            if not rules and not state['pending']:
                return
            state['last_turn'] = moment
            _save(path,state)  # başarısız kayıt fiyat/işlem başlatmaz
            notify_failed = set()
            if finance_alert_schedule.quiet_hours(moment) == 'send':
                for ident,row in list(state['pending'].items()):
                    try:
                        emit(finance_alert_schedule.notification_text(row['rule'],row['price']))
                    except Exception:
                        _record_failure('modules/finance_alert_tick.py:finance_notify')
                        notify_failed.add(ident)
                        continue
                    del state['pending'][ident]
                    _save(path,state)
            due = finance_alert_schedule.due_rules(rules,state['checked'],moment)
            if not due or len(due) != len(rules):
                return
            prices = {}
            getter = price_getter or _price
            def price(kind,symbol):
                key = (kind,symbol)
                if key not in prices:
                    try:
                        prices[key] = getter(kind,symbol)
                    except Exception:
                        _record_failure('modules/finance_alert_tick.py:finance_price')
                        prices[key] = None
                return prices[key]
            state['inflight'] = [{'rule':rule,'price':price(rule['kind'],rule['symbol']),
                                  'previous':finance_alert_store.get_state(owner,rule['id']),'at':moment} for rule in due]
            _save(path,state)  # sonuç tüketilmeden önce kurtarılabilir niyet
            fired = finance_alert_runner.run_once(owner,price,now=moment)
            for rule in due:
                state['checked'][rule['id']] = {'checked_at':moment}
            for row in fired:
                ident = row['id']
                observed = prices.get((row['kind'],row['symbol']))
                if observed is not None and ident not in state['pending']:
                    state['pending'][ident] = {'rule':row,'price':observed}
            _recover(owner,path,state,current)  # kesinti sonrası da aynı girdilerle tamamlanır
            if finance_alert_schedule.quiet_hours(moment) == 'send':
                for ident,row in list(state['pending'].items()):
                    if ident in notify_failed:
                        continue
                    try:
                        emit(finance_alert_schedule.notification_text(row['rule'],row['price']))
                    except Exception:
                        _record_failure('modules/finance_alert_tick.py:finance_notify')
                        continue
                    del state['pending'][ident]
                    _save(path,state)
        except Exception:
            _record_failure('modules/finance_alert_tick.py:finance_tick')

