"""Finans alarm kuralları için saf eşik değerlendirmesi; ağ, model ve dosya erişimi yok."""
import math
import time

_KINDS = {'doviz', 'kripto', 'altin', 'hisse'}
_OPS = {'above', 'below', 'pct_up', 'pct_down'}
_DEFAULT_COOLDOWN = 3600
_MIN_COOLDOWN = 60
_MAX_COOLDOWN = 7 * 24 * 60 * 60


def _number(value, *, label, positive=False, allow_zero=True):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'Geçersiz {label}.')
    try:
        value = float(value)
    except (OverflowError, TypeError, ValueError):
        raise ValueError(f'Geçersiz {label}.') from None
    if not math.isfinite(value):
        raise ValueError(f'Geçersiz {label}.')
    if positive and (value < 0 or (not allow_zero and value == 0)):
        raise ValueError(f'Geçersiz {label}.')
    return value


def _validate_rule(rule):
    if not isinstance(rule, dict):
        raise ValueError('Geçersiz alarm kuralı.')
    kind = rule.get('kind')
    symbol = rule.get('symbol')
    op = rule.get('op')
    if kind not in _KINDS or not isinstance(symbol, str) or not symbol.strip() or op not in _OPS:
        raise ValueError('Geçersiz alarm kuralı.')
    value = _number(rule.get('value'), label='alarm eşiği', positive=True, allow_zero=False)
    if op in {'pct_up', 'pct_down'} and value > 100:
        raise ValueError('Yüzde eşiği 0 ile 100 arasında olmalı.')
    cooldown = _number(rule.get('cooldown_s', _DEFAULT_COOLDOWN), label='bekleme süresi', positive=True)
    if cooldown < _MIN_COOLDOWN or cooldown > _MAX_COOLDOWN:
        raise ValueError('Bekleme süresi 60 saniye ile 7 gün arasında olmalı.')
    return symbol.strip(), op, value, cooldown


def _previous(previous):
    if previous is None:
        return None, None
    if not isinstance(previous, dict):
        raise ValueError('Geçersiz önceki alarm durumu.')
    old_price = previous.get('price')
    fired_at = previous.get('fired_at')
    if old_price is not None:
        old_price = _number(old_price, label='önceki fiyat', positive=True)
    if fired_at is not None:
        fired_at = _number(fired_at, label='son tetikleme zamanı', positive=True)
    return old_price, fired_at


def _invalid_price(price):
    return (price is None or isinstance(price, bool)
            or not isinstance(price, (int, float))
            or not math.isfinite(price) or price < 0)


def _state(price, fired_at):
    return {'price': price, 'fired_at': fired_at}


def evaluate(rule: dict, price: float | int | None, previous: dict | None = None,
             now: float | None = None) -> dict:
    """Bir fiyat gözlemini kurala göre değerlendirip yeni alarm durumunu döndürür."""
    symbol, op, value, cooldown = _validate_rule(rule)
    previous_invalid = False
    try:
        old_price, fired_at = _previous(previous)
    except (ValueError, OverflowError, TypeError):
        old_price, fired_at = None, None
        previous_invalid = True

    try:
        current = _number(price, label='fiyat', positive=True)
    except ValueError:
        return {
            'fire': False,
            'reason': f'Fiyat alınamadı; eşik {value:g}, önceki durum korundu.',
            'state': _state(old_price, fired_at),
        }

    moment = time.time() if now is None else _number(now, label='zaman')
    candidate = False
    threshold_text = f'{value:g}'

    if op == 'above':
        candidate = (not previous_invalid and current > value
                     and (old_price is None or old_price < value))
        reason = f'{symbol} fiyatı {current:g}; üst eşik {threshold_text}.'
    elif op == 'below':
        candidate = (not previous_invalid and current < value
                     and (old_price is None or old_price > value))
        reason = f'{symbol} fiyatı {current:g}; alt eşik {threshold_text}.'
    else:
        if previous_invalid or old_price is None:
            return {
                'fire': False,
                'reason': f'{symbol} fiyatı {current:g}; yüzde eşiği %{threshold_text}, önceki fiyat yok.',
                'state': _state(current, fired_at),
            }
        if old_price == 0:
            raise ValueError('Yüzde hesabında önceki fiyat sıfır olamaz.')
        change = ((current - old_price) / old_price) * 100.0
        if op == 'pct_up':
            candidate = change >= value
            reason = f'{symbol} fiyatı {current:g}; değişim %{change:g}, yükseliş eşiği %{threshold_text}.'
        else:
            candidate = change <= -value
            reason = f'{symbol} fiyatı {current:g}; değişim %{change:g}, düşüş eşiği %{threshold_text}.'

    if candidate and fired_at is not None and moment - fired_at < cooldown:
        return {
            'fire': False,
            'reason': f'{symbol} fiyatı {current:g}; eşik {threshold_text}, bekleme süresinde.',
            'state': _state(current, fired_at),
        }
    if candidate:
        return {'fire': True, 'reason': reason, 'state': _state(current, moment)}
    return {'fire': False, 'reason': reason, 'state': _state(current, fired_at)}
