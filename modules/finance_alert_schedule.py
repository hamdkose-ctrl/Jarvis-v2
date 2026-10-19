"""Saf alarm zamanlama ve bildirim metni; ağ/model/döngü ve motor bağlantısı yok.

due_rules state biçimi: {kural_id: {'checked_at': epoch_saniye, ...}}.
Bu takvim durumu, price/fired_at içeren finance_alert_store durumundan AYRIDIR;
fired_at son kontrol zamanı sayılmaz. Bağlayan çağırıcı checked_at'ı yönetir.
quiet_hours yalnız send/defer kararı verir; çağırıcı defer sonucunda bekleyen
tetik kaydını saklamalı ve sonradan göndermelidir. Bu modül tetik tüketmez/silmez.
"""
import copy
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import math
import re
from zoneinfo import ZoneInfo

from modules import finance_alerts

_ISTANBUL = ZoneInfo('Europe/Istanbul')


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Geçersiz alarm zamanı veya fiyatı.')
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise ValueError('Geçersiz alarm zamanı veya fiyatı.') from None
    if not math.isfinite(result) or result < 0:
        raise ValueError('Geçersiz alarm zamanı veya fiyatı.')
    return result


def _rule(rule):
    try:
        return finance_alerts._validate_rule(rule)
    except (TypeError, OverflowError):
        raise ValueError('Geçersiz alarm kuralı.') from None


def due_rules(rules, state, now, min_interval=300):
    """İlk kontrolü veya aralığı dolmuş kuralları sırayla, kopya olarak döndürür.

    Bozuk kural veya bozuk checked_at atlanır; gelecekteki kontrol yeniden
    çalıştırılmaz. Eksik checked_at ilk kontrol sayılır. Girdiler değişmez.
    """
    moment, interval = _number(now), _number(min_interval)
    if not isinstance(rules, (list, tuple)) or not isinstance(state, dict):
        return []
    result, seen = [], set()
    for rule in rules:
        try:
            _rule(rule)
            ident = rule.get('id')
            if not isinstance(ident, str) or not ident.strip() or len(ident) > 100 or ident in seen:
                continue
            saved = state.get(ident, {})
            if not isinstance(saved, dict):
                continue
            checked = saved.get('checked_at')
            if checked is not None and moment - _number(checked) < interval:
                continue
            seen.add(ident)
            result.append(copy.deepcopy(rule))
        except (ValueError, TypeError, OverflowError, RecursionError):
            continue
    return result


def _amount(value):
    with localcontext() as context:
        context.prec = 400
        value = Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return format(value, ',.2f').translate(str.maketrans({',': '.', '.': ','}))


def notification_text(rule, price, currency='TRY'):
    """Eşik ve gözlenen fiyatı tek Türkçe cümlede verir; işlem/alıp satma önermez."""
    symbol, op, threshold, _ = _rule(rule)
    observed = _number(price)
    if not re.fullmatch(r'[\w./:-]{1,32}', symbol):
        raise ValueError('Bildirim sembolü geçersiz.')
    if not isinstance(currency, str) or currency.strip().upper() not in {'TRY', 'TL', 'USD', 'EUR', 'GBP'}:
        raise ValueError('Bildirim para birimi geçersiz.')
    unit = currency.strip().upper()
    if unit == 'TRY':
        unit = 'TL'
    try:
        value, current = _amount(threshold), _amount(observed)
    except InvalidOperation:
        raise ValueError('Bildirim fiyatı biçimlendirilemedi.') from None
    if op in {'above', 'below'}:
        direction = 'üstüne çıktı' if op == 'above' else 'altına indi'
        return f"{symbol} {value} {unit}'nin {direction}; güncel fiyat {current} {unit}."
    direction = 'yükseliş' if op == 'pct_up' else 'düşüş'
    return f'{symbol} için %{value} {direction} alarmı; güncel fiyat {current} {unit}.'


def quiet_hours(now, start=23, end=7):
    """İstanbul saatinde [start,end) sessiz aralığı: defer; dışında send.

    now aware/naive datetime veya epoch saniyedir. Naive datetime İstanbul
    yerel saati kabul edilir; start==end boş aralıktır. Gerçek saat okunmaz.
    """
    if any(type(hour) is not int or not 0 <= hour <= 23 for hour in (start, end)):
        raise ValueError('Sessiz saat 0–23 arasında tam sayı olmalı.')
    try:
        if isinstance(now, datetime):
            moment = now.replace(tzinfo=_ISTANBUL) if now.tzinfo is None else now.astimezone(_ISTANBUL)
        else:
            moment = datetime.fromtimestamp(_number(now), _ISTANBUL)
    except (OverflowError, OSError):
        raise ValueError('Geçersiz alarm zamanı.') from None
    hour = moment.hour
    quiet = (start <= hour < end) if start < end else (hour >= start or hour < end) if start > end else False
    return 'defer' if quiet else 'send'
