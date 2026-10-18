"""Döviz kuru, kripto ve gram altın soruları ve çevirisi: modelsiz, kaynak ve tarih söyleyerek.

Yalnız açık kur soruları yakalanır ("dolar kaç lira", "100 dolar kaç TL", "euro kaç dolar"); geçmiş tarih,
yorum/tahmin, alarm/hatırlatma ve "euro 2024" gibi para birimi olmayan kullanımlar None döner ve diğer
yollara bırakılır. Birincil kaynak TCMB today.xml (resmî gösterge, döviz satış), TCMB'de olmayan para birimi
veya TCMB'ye ulaşılamazsa Frankfurter v2. Kripto ve gram altın BtcTurk genel API'sinden (altın PAXG/TRY'den
hesaplanır). Kaynak yanıtından yalnız sayı ve tarih okunur, metin modele gitmez.
"""
from __future__ import annotations

import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

TCMB_URL = 'https://www.tcmb.gov.tr/kurlar/today.xml'
FRANKFURTER_URL = 'https://api.frankfurter.dev/v2/rate/{code}/try'
BTCTURK_URL = 'https://api.btcturk.com/api/v2/ticker?pairSymbol={pair}'
COINGECKO_URL = 'https://api.coingecko.com/api/v3/simple/price?ids={id}&vs_currencies=try&include_24hr_change=true&include_last_updated_at=true'
COINGECKO_IDS = {'BTC': 'bitcoin', 'ETH': 'ethereum', 'USDT': 'tether', 'XRP': 'ripple', 'SOL': 'solana',
                 'DOGE': 'dogecoin', 'AVAX': 'avalanche-2', 'ADA': 'cardano', 'PAXG': 'pax-gold'}
TTL = 600
MARKET_TTL = 60
TROY_OUNCE_GRAMS = Decimal('31.1034768')
_CACHE: dict = {}
_BTCTURK_DOWN: dict = {}
BTCTURK_PAUSE = 300
TR = timezone(timedelta(hours=3))
_LOCK = threading.Lock()

# (kod, söylenen ad, katlanmış metinde aranan kökler, Türkçe ek alır mı). Çok sözcüklüler önce aranır.
CURRENCIES = (
    ('CAD', 'Kanada doları', ('kanada dolar',), True),
    ('AUD', 'Avustralya doları', ('avustralya dolar',), True),
    ('GBP', 'sterlin', ('ingiliz lira', 'sterlin', 'pound', 'gbp'), True),
    ('JPY', 'yen', ('japon yeni', 'japon yen', 'jpy', 'yen'), False),
    ('AZN', 'manat', ('manat', 'azn'), True),
    ('USD', 'dolar', ('amerikan dolar', 'dolar', 'usd'), True),
    ('EUR', 'euro', ('euro', 'avro', 'eur'), True),
    ('CHF', 'frank', ('isvicre frang', 'frank', 'frang', 'chf'), True),
    ('SAR', 'riyal', ('riyal',), True),
    ('RUB', 'ruble', ('ruble', 'rub'), True),
    ('CNY', 'yuan', ('yuan', 'cny'), True),
    ('TRY', 'TL', ('turk lira', 'lira', 'tl'), True),
)
# Kripto (BtcTurk TRY çifti) ve altın (BtcTurk PAXG/TRY: 1 PAXG = 1 ons altın). "sol" Türkçe sözcük olduğu için yok.
CRYPTO = (
    ('BTC', 'bitcoin', ('bitcoin', 'btc')),
    ('ETH', 'ethereum', ('ethereum', 'ether', 'eth')),
    ('USDT', 'tether', ('tether', 'usdt')),
    ('XRP', 'ripple', ('ripple', 'xrp')),
    ('SOL', 'solana', ('solana',)),
    ('DOGE', 'dogecoin', ('dogecoin', 'doge')),
    ('AVAX', 'avalanche', ('avalanche', 'avax')),
    ('ADA', 'cardano', ('cardano',)),
)
_GOLD_CUE = r'\b(?:fiyat\w*|ne kadar|kac (?:lira|tl|dolar|euro|para)|kur\w*|eder|kac$|kacta)\b|\b(?:gram|ons) altin'
_GOLD_OTHER = r'\baltin\w*\s+(?:madalya|top|oran|kural|cag|gun|vurus|saat|kelebek|portakal|kalp|kupa|yildiz|kitap|yumurta|sarisi)'
_SUFFIX = r"(?:'?(?:[iu]|y[iu]|[ae]|y[ae]|n[iu]n|[iu]n|l[ae]|yl[ae]|d[ae]n?|t[ae]n?|[iu]m|lar[iu]?|s[iu]))?"
_GOLD = r'\b(?:(?P<kind>gram|ons|ceyrek|yarim|tam|cumhuriyet|resat|ata)\s+)?altin' + _SUFFIX + r'\b'
_CUE = r'\b(?:kac\w*|ne kadar|kur\w*|fiyat\w*|eder|ediyor|ne oldu|cevir\w*|degeri\w*|olarak|cinsinden)\b'
# Geçmiş, tahmin/yorum, alarm ve takip istekleri bu kısa yolun işi değil.
_SKIP = (r'\b(?:hatirlat\w*|haber ver\w*|alarm\w*|takip\w*|bildir\w*|olunca|gecince|dusunce|neden|niye|nicin|'
         r'sence|tahmin\w*|yorum\w*|analiz\w*|grafik\w*|dun|gecen|onceki|hafta\w*|aylik|yillik|ay|yil|olur mu|olur|'
         r'olacak\w*|kadardi|kacti|ortalama\w*)\b')
_DEFINITION = r'\b(?:nedir|ne demek)\b'
_NUMBER_WORDS = {'bir': 1, 'iki': 2, 'uc': 3, 'dort': 4, 'bes': 5, 'alti': 6, 'yedi': 7, 'sekiz': 8, 'dokuz': 9,
                 'on': 10, 'yirmi': 20, 'otuz': 30, 'kirk': 40, 'elli': 50, 'altmis': 60, 'yetmis': 70,
                 'seksen': 80, 'doksan': 90}


def _fold(text: str) -> str:
    text = str(text or '').replace('I', 'ı').replace('İ', 'i').lower()
    text = text.translate(str.maketrans('çğıöşüâî', 'cgiosuai')).replace('̇', '')
    text = text.replace('$', ' dolar ').replace('€', ' euro ').replace('£', ' sterlin ').replace('₺', ' tl ')
    return ' '.join(re.sub(r"[^\w.,' ]", ' ', text).split())


def _mentions(low: str):
    """Para birimi geçişleri, metindeki sırasıyla: (başlangıç, bitiş, kod)."""
    found, taken = [], []
    for code, _name, stems, inflects in CURRENCIES:
        for stem in stems:
            pattern = r'\b' + re.escape(stem) + (_SUFFIX if inflects else '') + r'\b'
            for match in re.finditer(pattern, low):
                if any(match.start() < end and start < match.end() for start, end in taken):continue
                if code == 'EUR' and re.match(r"\s*'?\d{4}\b", low[match.end():]):continue  # euro 2024
                taken.append(match.span());found.append((match.start(), match.end(), code))
    return sorted(found)


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


def _amount_before(low: str, start: int):
    """Para biriminden hemen önceki miktar: "100", "1.500", "2,5", "10 bin", "iki yüz elli", "iki buçuk"."""
    words, taken = low[:start].split(), []
    while words and (words[-1] in _NUMBER_WORDS or words[-1] in ('yuz', 'bin', 'milyon', 'bucuk') or re.fullmatch(r'\d[\d.,]*', words[-1])):
        taken.insert(0, words.pop())
        if re.fullmatch(r'\d[\d.,]*', taken[0]):break
    total = current = Decimal(0)
    for word in taken:
        if re.fullmatch(r'\d[\d.,]*', word):
            value = _decimal(word)
            if value is None:return None
            current += value
        elif word == 'yuz':current = (current or 1) * 100
        elif word == 'bucuk':current += Decimal('0.5')
        elif word in ('bin', 'milyon'):
            total += (current or 1) * (1000 if word == 'bin' else 1_000_000);current = Decimal(0)
        else:current += _NUMBER_WORDS[word]
    return (total + current) or None


def _asset(low: str):
    """Kripto ya da altın fiyat sorusu: {'asset','kind','amount','target'}; değilse None."""
    found = None
    for code, _name_, stems in CRYPTO:
        for stem in stems:
            match = re.search(r'\b' + re.escape(stem) + _SUFFIX + r'\b', low)
            if match and (found is None or match.start() < found[1]):found = (code, match.start(), match.end(), None)
    gold = re.search(_GOLD, low)
    if gold and re.search(_GOLD_CUE, low) and not re.search(_GOLD_OTHER, low) and (found is None or gold.start() < found[1]):
        found = ('GOLD', gold.start(), gold.end(), gold.group('kind') or 'gram')
    if found is None or (found[0] != 'GOLD' and not re.search(_CUE, low)):return None
    code, start, end, kind = found
    target = next((c for s_, _e, c in _mentions(low) if s_ >= end and c != 'TRY'), 'TRY')
    return {'asset': code, 'kind': kind, 'amount': _amount_before(low, start), 'target': target,
            'source': None, 'list': None}


def parse(text: str):
    """Kur sorusuysa {'amount','source','target','list'}, kripto/altın sorusuysa ek olarak 'asset' döner; değilse None."""
    low = _fold(text)
    if re.search(_SKIP, low):return None
    if re.search(_DEFINITION, low) and not re.search(r'\bkur\w*', low):return None
    asset = _asset(low)
    if asset:return asset
    if not re.search(_CUE, low):return None
    mentions = _mentions(low)
    if not mentions:return None
    codes = [code for _s, _e, code in mentions]
    amount = _amount_before(low, mentions[0][0])
    unique = list(dict.fromkeys(codes))
    if len(unique) == 1:
        if unique[0] == 'TRY':return None
        return {'amount': amount, 'source': unique[0], 'target': 'TRY', 'list': None}
    second_start = mentions[codes.index(unique[1])][0]
    between = low[mentions[0][1]:second_start]
    after = low[second_start:second_start + 30]
    is_target = (unique[1] == 'TRY' or amount is not None or re.search(r'\bkac\b|\bkac tane\b', between)
                 or re.search(r'\b(?:olarak|cinsinden|cevir\w*)\b', after) or re.search(r'cevir', low))
    if is_target and len(unique) == 2:
        return {'amount': amount, 'source': unique[0], 'target': unique[1], 'list': None}
    rest = [code for code in unique if code != 'TRY']
    return {'amount': None, 'source': None, 'target': 'TRY', 'list': rest} if rest else None


def is_conversion(text: str) -> bool:
    """"50 euroyu dolara çevir" para çevirisidir, metin çevirisi değil ("bu metni euroya çevir" değildir)."""
    request = parse(text)
    if request and request.get('asset'):
        return request['amount'] is not None or request['target'] != 'TRY'
    return bool(request and not request['list'] and (request['amount'] is not None or request['target'] != 'TRY'
                                                       or len(_mentions(_fold(text))) > 1))


def _safe_xml(body: bytes):
    if re.search(br'<!\s*ENTITY\b', body, re.I):raise ValueError('XML varlık bildirimi kabul edilmez.')
    body = re.sub(br'<!DOCTYPE[^\[>]*(\[[^\]]*\])?\s*>', b'', body, count=1)
    return ET.fromstring(body)


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
    """BtcTurk önce; ulaşılamazsa ya da yanıt bozuksa CoinGecko (aynı TL fiyatı, ücretsiz). BtcTurk bozulunca 5 dk atlanır."""
    from urllib3.exceptions import HTTPError
    from modules.diagnostics import record_failure
    if time.monotonic() >= _BTCTURK_DOWN.get('until', 0):
        try:
            return _btcturk(pair)
        except PermissionError:
            raise
        except (ValueError, OSError, HTTPError, json.JSONDecodeError, InvalidOperation):
            record_failure('modules/finance.py:btcturk')
            _BTCTURK_DOWN['until'] = time.monotonic() + BTCTURK_PAUSE  # her soruda 5 sn beklememek için
    return _coingecko(pair)


def _num(value: Decimal, places: int = 2) -> str:
    quantum = Decimal(1).scaleb(-places)
    text = f'{value.quantize(quantum, rounding=ROUND_HALF_UP):,.{places}f}'
    return text.replace(',', '_').replace('.', ',').replace('_', '.')


def _amount_text(value: Decimal) -> str:
    return _num(value, 0) if value == value.to_integral() else _num(value).rstrip('0').rstrip(',')


def _rate_text(value: Decimal) -> str:
    return _num(value, 4 if value < 1 else 2)


def _name(code: str) -> str:
    return next(name for item_code, name, _s, _i in CURRENCIES if item_code == code)


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
        return 'Fiyat kaynağına (BtcTurk ve CoinGecko' + (', TCMB ve Frankfurter' if target != 'TRY' else '') + ') şu an ulaşamadım, biraz sonra tekrar dene.'
    price = row['last'] / (TROY_OUNCE_GRAMS if kind == 'gram' else 1) / table[target]
    name = (kind + ' altın') if code == 'GOLD' else next(n for c, n, _s in CRYPTO if c == code)
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


def answer(text: str) -> str | None:
    """Kur, kripto ya da altın sorusunun cevabı; değilse None (komut diğer yollara devam eder)."""
    request = parse(text)
    if request is None:return None
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
