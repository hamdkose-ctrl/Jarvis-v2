"""Typed, read-only finance data access with source and date attribution."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, DecimalException, InvalidOperation, ROUND_HALF_UP

TCMB_URL = 'https://www.tcmb.gov.tr/kurlar/today.xml'
FRANKFURTER_URL = 'https://api.frankfurter.dev/v2/rate/{code}/try'
BTCTURK_URL = 'https://api.btcturk.com/api/v2/ticker?pairSymbol={pair}'
COINGECKO_URL = 'https://api.coingecko.com/api/v3/simple/price?ids={id}&vs_currencies=try&include_24hr_change=true&include_last_updated_at=true'
COINGECKO_IDS = {'BTC': 'bitcoin', 'ETH': 'ethereum', 'USDT': 'tether', 'XRP': 'ripple', 'SOL': 'solana',
                 'DOGE': 'dogecoin', 'AVAX': 'avalanche-2', 'ADA': 'cardano', 'PAXG': 'pax-gold'}
YAHOO_URL = 'https://query1.finance.yahoo.com/v8/finance/chart/{code}.IS?range=1d&interval=1d'
TTL = 600
MARKET_TTL = 60
TROY_OUNCE_GRAMS = Decimal('31.1034768')
_CACHE: dict = {}
TR = timezone(timedelta(hours=3))
_LOCK = threading.Lock()

CURRENCIES = (
    ('CAD', 'Kanada doları'),
    ('AUD', 'Avustralya doları'),
    ('GBP', 'sterlin'),
    ('JPY', 'yen'),
    ('AZN', 'manat'),
    ('USD', 'dolar'),
    ('EUR', 'euro'),
    ('CHF', 'frank'),
    ('SAR', 'riyal'),
    ('RUB', 'ruble'),
    ('CNY', 'yuan'),
    ('TRY', 'TL'),
)
CRYPTO = (
    ('BTC', 'bitcoin'),
    ('ETH', 'ethereum'),
    ('USDT', 'tether'),
    ('XRP', 'ripple'),
    ('SOL', 'solana'),
    ('DOGE', 'dogecoin'),
    ('AVAX', 'avalanche'),
    ('ADA', 'cardano'),
)
STOCKS = (
    ('THYAO', 'THY'),
    ('GARAN', 'Garanti'),
    ('AKBNK', 'Akbank'),
    ('ISCTR', 'İş Bankası'),
    ('YKBNK', 'Yapı Kredi'),
    ('HALKB', 'Halkbank'),
    ('VAKBN', 'VakıfBank'),
    ('ASELS', 'Aselsan'),
    ('TUPRS', 'Tüpraş'),
    ('EREGL', 'Ereğli'),
    ('BIMAS', 'BİM'),
    ('KCHOL', 'Koç Holding'),
    ('SAHOL', 'Sabancı Holding'),
    ('FROTO', 'Ford Otosan'),
    ('SISE', 'Şişecam'),
    ('TCELL', 'Turkcell'),
    ('PGSUS', 'Pegasus'),
    ('SASA', 'Sasa'),
    ('XU100', 'BIST 100'),
)


def _decimal(token: str):
    token = token.strip('.,')
    if not token:return None
    if ',' in token:token = token.replace('.', '').replace(',', '.')
    elif token.count('.') > 1 or re.fullmatch(r'\d{1,3}\.\d{3}', token):token = token.replace('.', '')
    try:
        value = Decimal(token)
    except InvalidOperation:
        return None
    return value if value > 0 else None


CURRENCY_CODES = frozenset(code for code, _name in CURRENCIES)
CRYPTO_CODES = frozenset(code for code, _name in CRYPTO)
STOCK_CODES = frozenset(code for code, _name in STOCKS)
GOLD_KINDS = frozenset({'gram', 'ons', 'ceyrek', 'yarim', 'tam', 'cumhuriyet', 'resat', 'ata'})
FINANCE_ASSETS = CRYPTO_CODES | frozenset({'GOLD'})


def _decimal(token: str):
    token = token.strip('.,')
    if not token:
        return None
    if ',' in token:
        token = token.replace('.', '').replace(',', '.')
    elif token.count('.') > 1 or re.fullmatch(r'\d{1,3}\.\d{3}', token):
        token = token.replace('.', '')
    try:
        value = Decimal(token)
    except InvalidOperation:
        return None
    return value if value > 0 else None


def _safe_xml(body: bytes):
    if re.search(br'<!\s*ENTITY\b', body, re.I):raise ValueError('XML varlık bildirimi kabul edilmez.')
    body = re.sub(br'<!DOCTYPE[^\[>]*(\[[^\]]*\])?\s*>', b'', body, count=1)
    return ET.fromstring(body)



def dated_rate(owner, base, quote, on_date=None, *, fetcher=None):
    """Read one dated public FX rate with Finance-owned source validation."""
    from urllib.parse import urlencode
    from modules import public_sources, service_store
    service_store.identity(owner)
    if any(not isinstance(value, str) or not re.fullmatch('[A-Za-z]{3}', value) for value in (base, quote)):
        raise ValueError('Üç harfli para birimi gerekli.')
    if on_date is not None:
        if not isinstance(on_date, str):
            raise ValueError('Tarih YYYY-MM-DD olmalı.')
        date.fromisoformat(on_date)
    url = 'https://api.frankfurter.dev/v2/rate/' + base.lower() + '/' + quote.lower()
    if on_date:
        url += '?' + urlencode({'date': on_date})
    response = (fetcher or public_sources.fetch)(url)
    data = json.loads(response['body'])
    if not isinstance(data, dict) or data.get('base') != base.upper() or data.get('quote') != quote.upper():
        raise ValueError('Kur yanıtı para birimleriyle eşleşmiyor.')
    rate = Decimal(str(data.get('rate', '')))
    if not rate.is_finite() or rate <= 0 or not isinstance(data.get('date'), str):
        raise ValueError('Kur/değer tarihi geçersiz.')
    date.fromisoformat(data['date'])
    if on_date and data['date'] > on_date:
        raise ValueError('Kaynak istenen tarihten sonraki kuru döndürdü.')
    return {'data': data, 'source': response['url'], 'fetched_at': time.time(),
            'sha256': hashlib.sha256(response['body']).hexdigest(),
            'scope': 'Günlük kaynak kuru; anlık banka alış/satış fiyatı değildir.'}

def _tcmb():
    from modules import public_sources
    root = _safe_xml(public_sources.fetch(TCMB_URL, max_bytes=200_000)['body'])
    day = root.get('Tarih', '')
    if not re.fullmatch(r'\d{2}\.\d{2}\.\d{4}', day):raise ValueError('TCMB bülten tarihi okunamadı.')
    rates = {}
    for node in root.iter('Currency'):
        code, unit, selling = node.get('CurrencyCode') or node.get('Kod'), node.findtext('Unit'), node.findtext('ForexSelling')
        try:
            value = Decimal((selling or '').strip()) / Decimal((unit or '1').strip())
        except (InvalidOperation, ZeroDivisionError):
            continue
        if code and re.fullmatch(r'[A-Z]{3}', code) and value > 0:rates[code] = value
    if 'USD' not in rates:raise ValueError('TCMB yanıtında kur yok.')
    return rates, 'TCMB döviz satış kuru, ' + day


def _frankfurter(code: str):
    from modules import public_sources
    data = json.loads(public_sources.fetch(FRANKFURTER_URL.format(code=code.lower()), max_bytes=20_000)['body'])
    if not isinstance(data, dict) or data.get('base') != code or data.get('quote') != 'TRY':
        raise ValueError('Kur yanıtı para birimiyle eşleşmiyor.')
    value = Decimal(str(data.get('rate', '')))
    day = date.fromisoformat(str(data.get('date', '')))
    if value <= 0:raise ValueError('Kur geçersiz.')
    return value, 'Frankfurter günlük kur, ' + day.strftime('%d.%m.%Y')


def _cached(key, loader, ttl=TTL):
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and time.monotonic() - hit[0] < ttl:return hit[1]
    value = loader()
    with _LOCK:_CACHE[key] = (time.monotonic(), value)
    return value


def rates(codes):
    """{kod: 1 birimin TL karşılığı}, kaynak etiketi. Her kod tek kaynaktan; TCMB önce."""
    from urllib3.exceptions import HTTPError
    from modules.diagnostics import record_failure
    wanted = [code for code in dict.fromkeys(codes) if code != 'TRY']
    result, labels = {'TRY': Decimal(1)}, []
    try:
        tcmb, label = _cached('tcmb', _tcmb)
        for code in wanted:
            if code in tcmb:result[code] = tcmb[code]
        if any(code in tcmb for code in wanted):labels.append(label)
    except PermissionError:
        raise
    except (ValueError, OSError, HTTPError, ET.ParseError):
        record_failure('modules/finance.py:tcmb')
    for code in wanted:
        if code in result:continue
        value, label = _cached('fx:' + code, lambda code=code: _frankfurter(code))
        result[code] = value
        if label not in labels:labels.append(label)
    return result, '; '.join(labels)


def _btcturk(pair: str):
    from modules import public_sources
    data = json.loads(public_sources.fetch(BTCTURK_URL.format(pair=pair), max_bytes=50_000)['body'])
    if not isinstance(data, dict) or data.get('success') is False:raise ValueError('BtcTurk yanıtı başarısız.')
    rows = data.get('data') if isinstance(data.get('data'), list) else [data.get('data')]
    row = next((r for r in rows if isinstance(r, dict) and r.get('pair') == pair), None)
    if row is None:raise ValueError('BtcTurk yanıtında çift yok.')
    last = Decimal(str(row.get('last')))
    if not last.is_finite() or last <= 0:raise ValueError('BtcTurk fiyatı geçersiz.')
    stamp = row.get('timestamp')
    when = datetime.fromtimestamp(stamp / 1000, TR) if isinstance(stamp, (int, float)) and stamp > 0 else None
    daily = row.get('dailyPercent')
    daily = Decimal(str(daily)) if isinstance(daily, (int, float)) else None
    return {'last': last, 'when': when, 'daily': daily, 'source': 'BtcTurk'}


def _coingecko(pair: str):
    from modules import public_sources
    coin = COINGECKO_IDS[pair[:-3]]
    data = json.loads(public_sources.fetch(COINGECKO_URL.format(id=coin), max_bytes=20_000)['body'])
    row = data.get(coin) if isinstance(data, dict) else None
    if not isinstance(row, dict):raise ValueError('CoinGecko yanıtında coin yok.')
    last = Decimal(str(row.get('try')))
    if not last.is_finite() or last <= 0:raise ValueError('CoinGecko fiyatı geçersiz.')
    stamp = row.get('last_updated_at')
    when = datetime.fromtimestamp(stamp, TR) if isinstance(stamp, (int, float)) and stamp > 0 else None
    daily = row.get('try_24h_change')
    daily = Decimal(str(round(daily, 2))) if isinstance(daily, (int, float)) else None
    return {'last': last, 'when': when, 'daily': daily, 'source': 'CoinGecko'}


def _market(pair: str):
    """CoinGecko önce (Hamdi'nin PC'sinde BtcTurk zaman aşımına düşüyor); olmazsa BtcTurk (aynı TL fiyatı)."""
    from urllib3.exceptions import HTTPError
    from modules.diagnostics import record_failure
    try:
        return _coingecko(pair)
    except PermissionError:
        raise
    except (ValueError, OSError, HTTPError, json.JSONDecodeError, InvalidOperation, KeyError):
        record_failure('modules/finance.py:coingecko')
    return _btcturk(pair)


def _yahoo(code: str):
    from modules import public_sources
    try:
        body = public_sources.fetch(YAHOO_URL.format(code=code), max_bytes=200_000)['body']
    except ValueError as exc:
        if str(exc) == 'Kaynak HTTP yanıtı başarılı değil: 404':
            raise LookupError(f'{code} borsa kodu bulunamadı.') from None
        raise
    data = json.loads(body)
    chart = data.get('chart') if isinstance(data, dict) else None
    rows = chart.get('result') if isinstance(chart, dict) else None
    meta = rows[0].get('meta') if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None
    if not isinstance(meta, dict) or meta.get('currency') != 'TRY':raise ValueError('Yahoo TRY fiyatı okunamadı.')
    last = Decimal(str(meta.get('regularMarketPrice')))
    stamp = meta.get('regularMarketTime')
    if not last.is_finite() or last <= 0:raise ValueError('Yahoo fiyatı geçersiz.')
    if type(stamp) not in (int, float) or stamp <= 0:raise ValueError('Yahoo fiyat zamanı okunamadı.')
    when = datetime.fromtimestamp(stamp, TR)
    previous = meta.get('chartPreviousClose')
    if previous is None:previous = meta.get('previousClose')
    daily = None
    try:
        previous = Decimal(str(previous))
        if previous.is_finite() and previous > 0:daily = (last / previous - 1) * 100
    except DecimalException:
        pass
    return {'last': last, 'when': when, 'daily': daily}


def quote(kind: str, symbol: str) -> float:
    """Read one TRY alarm price through Finance's existing source adapters."""
    if kind == 'doviz':
        table, _ = rates([symbol, 'TRY'])
        return float(table[symbol])
    if kind == 'hisse':
        return float(_yahoo(symbol)['last'])
    if kind in {'kripto', 'altin'}:
        row = _market('PAXGTRY' if kind == 'altin' else symbol + 'TRY')
        value = row['last']
        return float(value / TROY_OUNCE_GRAMS if kind == 'altin' else value)
    raise ValueError('Desteklenmeyen alarm fiyat türü.')


def _bist_answer(request) -> str:
    from urllib3.exceptions import HTTPError
    from modules import ollama_hint
    code, amount = request['stock'], request['amount']
    try:
        row = _cached('bist:' + code, lambda: _yahoo(code), MARKET_TTL)
        name = next((name for item, name in STOCKS if item == code), code)
        shown = name if code == 'XU100' or name == code else f'{name} ({code})'
        if amount is None:body = f'{shown} {_num(row["last"])} ' + ('puan' if code == 'XU100' else 'TL')
        else:body = f'{_amount_text(amount)} {shown} hissesi {_num(amount * row["last"])} TL eder'
        if row['daily'] is not None:
            sign = '+' if row['daily'] > 0 else '-' if row['daily'] < 0 else ''
            body += f' (günlük {sign}%{_num(abs(row["daily"]))})'
        return (f'{body}. Kaynak: Yahoo Finance {row["when"].strftime("%d.%m.%Y %H:%M")}; '
                'borsa verisi yaklaşık 15 dk gecikmeli, kapalıyken son kapanış. '
                'Bilgi amaçlıdır, yatırım tavsiyesi değildir.')
    except PermissionError as exc:
        return str(exc)
    except LookupError as exc:
        return str(exc)
    except (ValueError, OSError, HTTPError, DecimalException, OverflowError):
        if not ollama_hint.internet_up():return ollama_hint.NO_INTERNET
        return 'Fiyat kaynağına (Yahoo Finance) şu an ulaşamadım, biraz sonra tekrar dene.'


def _num(value: Decimal, places: int = 2) -> str:
    quantum = Decimal(1).scaleb(-places)
    text = f'{value.quantize(quantum, rounding=ROUND_HALF_UP):,.{places}f}'
    return text.replace(',', '_').replace('.', ',').replace('_', '.')


def _amount_text(value: Decimal) -> str:
    return _num(value, 0) if value == value.to_integral() else _num(value).rstrip('0').rstrip(',')


def _rate_text(value: Decimal) -> str:
    return _num(value, 4 if value < 1 else 2)


def _name(code: str) -> str:
    return next(name for item_code, name in CURRENCIES if item_code == code)


def _asset_answer(request) -> str:
    from urllib3.exceptions import HTTPError
    from modules import ollama_hint
    code, kind, target, amount = request['asset'], request['kind'], request['target'], request['amount']
    note = ''
    if code == 'GOLD' and kind not in ('gram', 'ons'):
        shown = {'ceyrek': 'Çeyrek', 'yarim': 'Yarım', 'tam': 'Tam', 'cumhuriyet': 'Cumhuriyet', 'resat': 'Reşat', 'ata': 'Ata'}[kind]
        note = (f'{shown} altın için güvenilir bir kaynak henüz yok; kuyumcu fiyatı ayar ve işçiliğe göre '
                'değişir. ')
        kind, amount = 'gram', None
    pair = 'PAXGTRY' if code == 'GOLD' else code + 'TRY'
    try:
        row = _cached('bt:' + pair, lambda: _market(pair), MARKET_TTL)
        table, label = rates([target]) if target != 'TRY' else ({'TRY': Decimal(1)}, '')
    except PermissionError as exc:
        return str(exc)
    except (ValueError, OSError, HTTPError, json.JSONDecodeError, InvalidOperation):
        if not ollama_hint.internet_up():return ollama_hint.NO_INTERNET
        return 'Fiyat kaynağına (CoinGecko ve BtcTurk' + (', TCMB ve Frankfurter' if target != 'TRY' else '') + ') şu an ulaşamadım, biraz sonra tekrar dene.'
    price = row['last'] / (TROY_OUNCE_GRAMS if kind == 'gram' else 1) / table[target]
    name = (kind + ' altın') if code == 'GOLD' else next(n for c, n in CRYPTO if c == code)
    unit = _name(target)
    if amount is None:
        body = f'{name[0].upper()}{name[1:]} {_num(price)} {unit}'
    else:
        body = f'{_amount_text(amount)} {name} {_num(amount * price)} {unit} eder'
    if code != 'GOLD' and row['daily'] is not None:
        sign = '+' if row['daily'] > 0 else '-' if row['daily'] < 0 else ''
        body += f' (günlük {sign}%{_num(abs(row["daily"]))})'
    when = row['when'].strftime(' %d.%m.%Y %H:%M') if row['when'] else ''
    source = (f'{row["source"]} PAXG/TRY{when} fiyatından hesaplandı (PAXG 1 ons altına bağlı token, 1 ons = 31,1035 gram)'
              if code == 'GOLD' else f'{row["source"]} {code}/TRY' + (' son işlem' if row['source'] == 'BtcTurk' else '') + when)
    if label:source += '; ' + label
    tail = ' Kuyumcu ve banka fiyatı farklı olabilir.' if code == 'GOLD' else ''
    return f'{note}{body}. Kaynak: {source}.{tail}'


def answer_request(request) -> str:
    """Doğrulanmış isteği yanıtlar: yalnız veri çeker ve biçimlendirir; ham metin ayrıştırmaz."""
    if request.get('stock'):return _bist_answer(request)
    if request.get('asset'):return _asset_answer(request)
    from urllib3.exceptions import HTTPError
    from modules import ollama_hint
    codes = request['list'] or [request['source'], request['target']]
    try:
        table, label = rates(codes)
    except PermissionError as exc:
        return str(exc)
    except (ValueError, OSError, HTTPError, json.JSONDecodeError, InvalidOperation):
        if not ollama_hint.internet_up():return ollama_hint.NO_INTERNET
        return 'Kur kaynaklarına (TCMB ve Frankfurter) şu an ulaşamadım, biraz sonra tekrar dene.'
    if request['list']:
        parts = [f'{_name(code)} {_rate_text(table[code])} TL' for code in request['list']]
        body = ', '.join(parts)
        body = body[0].upper() + body[1:]
    else:
        source, target, amount = request['source'], request['target'], request['amount']
        cross = table[source] / table[target]
        if amount is None and target == 'TRY':
            body = f'{_name(source)[0].upper()}{_name(source)[1:]} {_rate_text(cross)} TL'
        elif amount is None:
            body = f'1 {_name(source)} {_rate_text(cross)} {_name(target)}'
        else:
            body = f'{_amount_text(amount)} {_name(source)} {_num(amount * cross)} {_name(target)} eder'
    return f'{body}. Kaynak: {label}. Banka ve döviz bürosu fiyatı farklı olabilir.'


def request_from_slots(arguments) -> dict:
    """Core'un doğruladığı tipli slotları domain isteğine çevirir (ham metin yoktur)."""
    kind = arguments.get('kind')
    amount = arguments.get('amount')
    amount = None if amount is None else _decimal(str(amount))
    if kind == 'stock':
        return {'stock': str(arguments['stock']), 'amount': amount, 'target': 'TRY',
                'source': None, 'list': None}
    if kind == 'asset':
        return {'asset': str(arguments['asset']), 'kind': arguments.get('gold_kind'), 'amount': amount,
                'target': str(arguments.get('target') or 'TRY'), 'source': None, 'list': None}
    codes = list(arguments.get('codes') or [])
    if codes:
        return {'amount': None, 'source': None, 'target': 'TRY', 'list': codes}
    return {'amount': amount, 'source': str(arguments['source']), 'target': str(arguments['target']),
            'list': None}
