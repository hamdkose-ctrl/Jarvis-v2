"""Kur cevabı: yalnız gerçek kur soruları tetiklenir, çeviri yapılır, kaynak/tarih söylenir, model çağrılmaz.

Kaynak yanıtları burada elle kurulmuş örneklerdir (TCMB today.xml ve Frankfurter v2 biçiminde); canlı kaynak denenmez.
"""
import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import finance, public_sources

TCMB_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<?xml-stylesheet type="text/xsl" href="isokur.xsl"?>
<!DOCTYPE Tarih_Date [
<!ELEMENT Tarih_Date (Currency)+>
<!ATTLIST Tarih_Date Tarih CDATA #REQUIRED Date CDATA #REQUIRED Bulten_No CDATA #REQUIRED>
]>
<Tarih_Date Tarih="17.10.2026" Date="10/17/2026" Bulten_No="2026/198">
<Currency CrossOrder="0" Kod="USD" CurrencyCode="USD"><Unit>1</Unit><Isim>ABD DOLARI</Isim><CurrencyName>US DOLLAR</CurrencyName>
<ForexBuying>41.8500</ForexBuying><ForexSelling>41.9254</ForexSelling><BanknoteBuying>41.82</BanknoteBuying><BanknoteSelling>41.99</BanknoteSelling></Currency>
<Currency CrossOrder="9" Kod="EUR" CurrencyCode="EUR"><Unit>1</Unit><Isim>EURO</Isim><CurrencyName>EURO</CurrencyName>
<ForexBuying>48.6000</ForexBuying><ForexSelling>48.6876</ForexSelling><BanknoteBuying></BanknoteBuying><BanknoteSelling></BanknoteSelling></Currency>
<Currency CrossOrder="11" Kod="GBP" CurrencyCode="GBP"><Unit>1</Unit><Isim>İNGİLİZ STERLİNİ</Isim><CurrencyName>POUND STERLING</CurrencyName>
<ForexBuying>55.9000</ForexBuying><ForexSelling>56.0000</ForexSelling></Currency>
<Currency CrossOrder="12" Kod="JPY" CurrencyCode="JPY"><Unit>100</Unit><Isim>JAPON YENİ</Isim><CurrencyName>JAPENESE YEN</CurrencyName>
<ForexBuying>27.9000</ForexBuying><ForexSelling>28.1000</ForexSelling></Currency>
</Tarih_Date>'''.encode()


def frankfurter(base, rate, day='2026-10-17'):
    return json.dumps({'base': base, 'quote': 'TRY', 'rate': rate, 'date': day}).encode()


BTCTURK = {'BTCTRY': (2450000.0, 1.25), 'ETHTRY': (150000.5, -0.8), 'PAXGTRY': (109250.0, 0.1)}


COINGECKO = {'bitcoin': (2450000.0, 1.25), 'ethereum': (150000.5, -0.8), 'pax-gold': (109250.0, 0.1)}


def coingecko(url):
    ids = re.search(r'ids=([a-z0-9,-]+)', url).group(1).split(',')
    return json.dumps({i: {'try': COINGECKO[i][0], 'try_24h_change': COINGECKO[i][1], 'last_updated_at': 1792348920} for i in ids}).encode()


def btcturk(pair):
    last, daily = BTCTURK[pair]
    return json.dumps({'data': [{'pair': pair, 'pairNormalized': pair[:-3] + '_TRY', 'timestamp': 1792348920000,
                                 'last': last, 'high': last, 'low': last, 'dailyPercent': daily,
                                 'numeratorSymbol': pair[:-3], 'denominatorSymbol': 'TRY'}],
                       'success': True, 'message': None, 'code': 0}).encode()


def yahoo(code='THYAO', **changes):
    meta = {'regularMarketPrice': 10250.75 if code == 'XU100' else 312.5,
            'chartPreviousClose': 10300 if code == 'XU100' else 308,
            'regularMarketTime': 1792346340, 'currency': 'TRY',
            'shortName': 'Bu kaynak metni cevapta veya modelde kullanılmaz.'}
    meta.update(changes)
    return json.dumps({'chart': {'result': [{'meta': meta}], 'error': None}}).encode()


class FinanceTest(unittest.TestCase):
    def setUp(self):
        finance._CACHE.clear()
        self.calls = []

    def fetch_ok(self, url, **_):
        self.calls.append(url)
        if 'query1.finance.yahoo.com' in url:
            code = url.split('/chart/')[1].split('.IS')[0]
            return {'url': url, 'body': yahoo(code), 'content_type': 'application/json'}
        if 'tcmb.gov.tr' in url:
            return {'url': url, 'body': TCMB_XML, 'content_type': 'text/xml'}
        if 'coingecko.com' in url:
            return {'url': url, 'body': coingecko(url), 'content_type': 'application/json'}
        if 'btcturk.com' in url:
            return {'url': url, 'body': btcturk(url.rsplit('=', 1)[1]), 'content_type': 'application/json'}
        code = re.search(r'/rate/([a-z]{3})/try', url).group(1).upper()
        return {'url': url, 'body': frankfurter(code, {'AZN': 24.6}.get(code, 1.0)), 'content_type': 'application/json'}

    def ask(self, text, fetch=None):
        with patch.object(public_sources, 'fetch', side_effect=fetch or self.fetch_ok), \
             patch('modules.ollama_hint.internet_up', return_value=True), \
             patch('modules.diagnostics.record_failure'):
            return finance.answer(text)

    def test_not_a_rate_question_is_left_to_other_handlers(self):
        for text in ('euro 2024 finalini kim kazandı', "euro 2024'te kaç gol atıldı", 'eurovision ne zaman',
                     'dolarla ödedim notlara ekle', 'dolar kuru yükselince bana hatırlat', 'dolar 45 olunca haber ver',
                     'dolar neden yükseldi', 'dün dolar kaçtı', 'geçen hafta euro ne kadardı', 'yeni dosya oluştur',
                     'sence dolar ne kadar olur', 'dolar nedir', 'lira ne kadar', 'bugün hava nasıl'):
            with self.subTest(text=text):
                self.assertIsNone(self.ask(text))
        self.assertEqual(self.calls, [])

    def test_rate_questions_with_variations(self):
        for text in ('dolar kaç lira', 'dolar kac lira', 'Dolar ne kadar?', 'dolar kuru', 'doların kuru ne',
                     'dolar kaç tl', 'güncel dolar kuru nedir', 'usd kaç', 'amerikan doları ne kadar', 'dolar ne oldu',
                     'jarvis dolar kaç', 'dolar kaçta'):
            with self.subTest(text=text):
                out = self.ask(text)
                self.assertIn('Dolar 41,93 TL', out)
                self.assertIn('TCMB döviz satış kuru, 17.10.2026', out)

    def test_other_currencies_and_lists(self):
        self.assertIn('Euro 48,69 TL', self.ask('euro kaç tl'))
        self.assertIn('Euro 48,69 TL', self.ask('avro ne kadar'))
        self.assertIn('Euro 48,69 TL', self.ask('euronun kuru ne kadar'))
        self.assertIn('Sterlin 56,00 TL', self.ask('ingiliz sterlini ne kadar'))
        self.assertIn('Sterlin 56,00 TL', self.ask('pound kaç lira'))
        self.assertIn('Yen 0,2810 TL', self.ask('japon yeni kaç lira'))
        both = self.ask('dolar ve euro ne kadar')
        self.assertIn('Dolar 41,93 TL', both);self.assertIn('euro 48,69 TL', both)

    def test_conversion(self):
        self.assertIn('100 dolar 4.192,54 TL eder', self.ask('100 dolar kaç TL'))
        self.assertIn('100 dolar 4.192,54 TL eder', self.ask('100 dolar kaç lira eder'))
        self.assertIn('1.500 dolar 62.888,10 TL eder', self.ask('1.500 dolar ne kadar'))
        self.assertIn('2,5 euro 121,72 TL eder', self.ask('2,5 euro kaç tl'))
        self.assertIn('10.000 dolar 419.254,00 TL eder', self.ask('10 bin dolar kaç lira'))
        self.assertIn('100 dolar 4.192,54 TL eder', self.ask('yüz dolar kaç lira'))
        self.assertIn('250 euro', self.ask('iki yüz elli euro ne kadar'))
        self.assertIn('2,5 euro 121,72 TL eder', self.ask('iki buçuk euro kaç tl'))
        self.assertIn('1.500 dolar', self.ask('bin beş yüz dolar kaç lira'))
        self.assertIn('100 dolar 4.192,54 TL eder', self.ask('100$ kaç TL'))
        self.assertIn('1.000 TL 23,85 dolar eder', self.ask('1000 lira kaç dolar'))
        self.assertIn('1 euro 1,16 dolar', self.ask('euro kaç dolar'))
        self.assertIn('50 euro 58,06 dolar eder', self.ask('50 euroyu dolara çevir'))

    def test_money_conversion_is_not_text_translation(self):
        from modules import chat_translation
        for text in ('50 euroyu dolara çevir', 'euroyu dolara çevir', '100 doları liraya çevir', '200 lirayı euroya çevir'):
            with self.subTest(text=text):
                self.assertTrue(finance.is_conversion(text))
                self.assertIsNone(chat_translation.resolve('alice', text, []))
        for text in ('bu metni euroya çevir', 'bunu ingilizceye çevir', 'merhaba dünya cümlesini almancaya çevir'):
            with self.subTest(text=text):
                self.assertFalse(finance.is_conversion(text))
        self.assertIsNotNone(chat_translation.resolve('alice', 'merhaba dünya cümlesini almancaya çevir', []))

    def test_single_request_and_cache(self):
        self.ask('dolar kaç lira');self.ask('euro kaç lira');self.ask('100 dolar kaç tl')
        self.assertEqual(len(self.calls), 1)

    def test_falls_back_to_frankfurter_and_says_so(self):
        def fetch(url, **_):
            if 'tcmb.gov.tr' in url:raise ValueError('Kaynak HTTP yanıtı başarılı değil: 503')
            self.calls.append(url)
            return {'url': url, 'body': frankfurter('USD', 41.9), 'content_type': 'application/json'}
        out = self.ask('dolar kaç lira', fetch)
        self.assertIn('Dolar 41,90 TL', out);self.assertIn('Frankfurter', out);self.assertIn('17.10.2026', out)
        self.assertTrue(all(u.startswith('https://api.frankfurter.dev/v2/rate/usd/try') for u in self.calls))

    def test_currency_missing_in_tcmb_uses_frankfurter(self):
        out = self.ask('azerbaycan manatı kaç lira')
        self.assertIn('Manat 24,60 TL', out);self.assertIn('Frankfurter', out)

    def test_offline_and_source_down_messages(self):
        def down(url, **_):raise OSError('ağ yok')
        with patch.object(public_sources, 'fetch', side_effect=down), patch('modules.ollama_hint.internet_up', return_value=False), \
             patch('modules.diagnostics.record_failure'):
            self.assertEqual(finance.answer('dolar kaç lira'), 'İnternet bağlantın yok, bağlanınca tekrar dene.')
        out = self.ask('dolar kaç lira', down)
        self.assertIn('ulaşamadım', out)
        def private(url, **_):raise PermissionError('Web işlemleri gizli modda kapalı.')
        self.assertIn('gizli modda kapalı', self.ask('dolar kaç lira', private))

    def test_malformed_or_entity_xml_is_rejected_then_falls_back(self):
        evil = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><Tarih_Date Tarih="17.10.2026">&a;</Tarih_Date>'
        def fetch(url, **_):
            if 'tcmb.gov.tr' in url:return {'url': url, 'body': evil, 'content_type': 'text/xml'}
            return {'url': url, 'body': frankfurter('USD', 41.9), 'content_type': 'application/json'}
        self.assertIn('Frankfurter', self.ask('dolar kaç lira', fetch))
        def wrong(url, **_):
            if 'tcmb.gov.tr' in url:return {'url': url, 'body': TCMB_XML, 'content_type': 'text/xml'}
            return {'url': url, 'body': frankfurter('EUR', 1.0), 'content_type': 'application/json'}
        finance._CACHE.clear()
        self.assertIn('ulaşamadım', self.ask('manat kaç lira', wrong))

    def test_crypto_prices_and_conversion(self):
        for text in ('bitcoin kaç lira', 'btc ne kadar', "bitcoin'in fiyatı", 'bitcoinin fiyatı ne', 'Bitcoin kaç TL?'):
            with self.subTest(text=text):
                out = self.ask(text)
                self.assertIn('Bitcoin 2.450.000,00 TL (günlük +%1,25)', out)
                self.assertIn('CoinGecko BTC/TRY 18.10.2026', out)
        self.assertIn('Ethereum 150.000,50 TL (günlük -%0,80)', self.ask('ethereum kaç tl'))
        self.assertIn('0,5 bitcoin 1.225.000,00 TL eder', self.ask('0,5 bitcoin kaç lira'))
        usd = self.ask('bitcoin kaç dolar')
        self.assertIn('Bitcoin 58.437,13 dolar', usd);self.assertIn('TCMB döviz satış kuru', usd)
        self.assertTrue(finance.is_conversion('0,5 bitcoini liraya çevir'))

    def test_gold_prices(self):
        for text in ('gram altın ne kadar', 'altın fiyatı', 'altın kaç lira', 'gram altin kac tl', 'altının fiyatı ne kadar'):
            with self.subTest(text=text):
                out = self.ask(text)
                self.assertIn('Gram altın 3.512,47 TL', out)
                self.assertIn('PAXG/TRY', out);self.assertIn('Kuyumcu ve banka fiyatı farklı olabilir', out)
        self.assertIn('10 gram altın 35.124,69 TL eder', self.ask('10 gram altın kaç lira'))
        self.assertIn('Ons altın 2.605,82 dolar', self.ask('ons altın kaç dolar'))
        quarter = self.ask('çeyrek altın ne kadar')
        self.assertIn('Çeyrek altın için güvenilir bir kaynak henüz yok', quarter)
        self.assertIn('Gram altın 3.512,47 TL', quarter)

    def test_asset_words_in_other_meanings_are_left_alone(self):
        for text in ('altın madalya kaç tane kazandık', 'altın oran nedir', 'altın kural ne', 'sol tarafı aç',
                     'bitcoin nedir', 'bitcoin neden düştü', 'bitcoin 3 milyon olunca haber ver', 'altın günü ne zaman',
                     'altın topu kim kazandı', 'bitcoin hakkında bilgi ver', 'dün bitcoin kaçtı'):
            with self.subTest(text=text):
                self.assertIsNone(self.ask(text))
        self.assertEqual(self.calls, [])

    def test_crypto_source_failures(self):
        def down(url, **_):
            if 'coingecko.com' in url:raise OSError('yok')
            return self.fetch_ok(url)
        out = self.ask('bitcoin kaç lira', down)
        self.assertIn('Bitcoin 2.450.000,00 TL (günlük +%1,25)', out)
        self.assertIn('BtcTurk BTC/TRY son işlem 18.10.2026', out)
        gold = self.ask('gram altın ne kadar', down)
        self.assertIn('Gram altın 3.512,47 TL', gold);self.assertIn('BtcTurk PAXG/TRY', gold)
        def both(url, **_):
            if 'btcturk.com' in url or 'coingecko.com' in url:raise OSError('yok')
            return self.fetch_ok(url)
        finance._CACHE.clear()
        self.assertIn('Fiyat kaynağına (CoinGecko ve BtcTurk) şu an ulaşamadım', self.ask('bitcoin kaç lira', both))
        def denied(url, **_):raise PermissionError('Gizlilik modu açık')
        finance._CACHE.clear()
        self.assertEqual('Gizlilik modu açık', self.ask('bitcoin kaç lira', denied))
        def failed(url, **_):
            return {'url': url, 'body': json.dumps({'success': False, 'data': None}).encode(), 'content_type': 'application/json'}
        finance._CACHE.clear()
        self.assertIn('ulaşamadım', self.ask('gram altın ne kadar', failed))
        def wrong_pair(url, **_):
            return {'url': url, 'body': btcturk('ETHTRY'), 'content_type': 'application/json'}
        finance._CACHE.clear()
        self.assertIn('ulaşamadım', self.ask('bitcoin kaç lira', wrong_pair))

    def test_coingecko_is_first_and_btcturk_is_not_called(self):
        self.assertIn('CoinGecko', self.ask('bitcoin kaç lira'))
        self.assertFalse(any('btcturk.com' in u for u in self.calls))

    def test_market_cache_is_short(self):
        self.ask('bitcoin kaç lira');self.ask('btc ne kadar')
        self.assertEqual(sum('coingecko.com' in u for u in self.calls), 1)
        key = 'bt:BTCTRY'
        stamp, value = finance._CACHE[key]
        finance._CACHE[key] = (stamp - finance.MARKET_TTL - 1, value)
        self.ask('bitcoin kaç lira')
        self.assertEqual(sum('coingecko.com' in u for u in self.calls), 2)

    def test_live_source_script_reports_each_source(self):
        import contextlib, importlib.util, io
        path = Path(__file__).resolve().parents[1] / 'scripts' / 'finans_kaynak_testi.py'
        spec = importlib.util.spec_from_file_location('finans_kaynak_testi', path)
        script = importlib.util.module_from_spec(spec);spec.loader.exec_module(script)
        out = io.StringIO()
        with patch.object(public_sources, 'fetch', side_effect=self.fetch_ok), contextlib.redirect_stdout(out):
            self.assertEqual(script.main(), 0)
        self.assertEqual(out.getvalue().count('GEÇTİ'), 8)
        self.assertIn('Gram altın 3.512,47 TL', out.getvalue())
        self.assertIn('THY (THYAO) 312,50 TL', out.getvalue())
        self.assertIn('BIST 100 10.250,75 puan', out.getvalue())
        def down(url, **_):raise OSError('yok')
        out = io.StringIO()
        with patch.object(public_sources, 'fetch', side_effect=down), patch('modules.ollama_hint.internet_up', return_value=False), \
             patch('modules.diagnostics.record_failure'), contextlib.redirect_stdout(out):
            self.assertEqual(script.main(), 1)
        self.assertEqual(out.getvalue().count('BAŞARISIZ'), 8)

    def test_bist_names_codes_ascii_and_suffixes(self):
        for text, code in [('thy hissesi kaç lira', 'THYAO'), ('THY HİSSESİ KAÇ LİRA', 'THYAO'),
                           ('turk hava yollari hissesi kac', 'THYAO'), ("thy'nin hissesi kaçta", 'THYAO'),
                           ('THYAO kaç', 'THYAO'), ('thyao hissesi kaç', 'THYAO'),
                           ("THYAO'NUN fiyatı", 'THYAO'), ('THYAOYU kaç', 'THYAO'),
                           ('garantiyi borsada kaç liradan alıyorlar', 'GARAN'),
                           ('garanti hissesi ne kadar', 'GARAN'), ('koç holding hissesi kaç', 'KCHOL'),
                           ('ereğli hissesi fiyatı', 'EREGL'), ('erdemir hissesi kaç', 'EREGL')]:
            with self.subTest(text=text):
                request = finance.parse(text)
                self.assertIsNotNone(request)
                self.assertEqual(request['stock'], code)
                out = self.ask(text)
                self.assertIn(f'({code}) 312,50 TL', out)
                self.assertIn('günlük +%1,46', out)
                self.assertIn('Kaynak: Yahoo Finance 18.10.2026', out)
                self.assertIn('yaklaşık 15 dk gecikmeli', out)
                self.assertIn('kapalıyken son kapanış', out)
                self.assertIn('yatırım tavsiyesi değildir', out)
                self.assertNotIn('Bu kaynak metni', out)

    def test_bist_all_requested_codes_and_index(self):
        codes = ('THYAO GARAN AKBNK ISCTR YKBNK HALKB VAKBN ASELS TUPRS EREGL BIMAS KCHOL '
                 'SAHOL FROTO SISE TCELL PGSUS SASA').split()
        self.assertEqual({row[0] for row in finance.STOCKS}, set(codes) | {'XU100'})
        for code in codes:
            with self.subTest(code=code):
                self.assertEqual(finance.parse(code + ' hissesi kaç')['stock'], code)
        for text in ('bist 100 kaç puan', 'bist100 kaç', 'BİST 100 ne kadar', 'borsa kaç puan',
                     'borsa ne durumda', 'bist kaç', '10 bist 100 kaç puan'):
            with self.subTest(text=text):
                self.assertEqual(finance.parse(text)['stock'], 'XU100')
                self.assertIsNone(finance.parse(text)['amount'])
                self.assertIn('BIST 100 10.250,75 puan (günlük -%0,48)', self.ask(text))

    def test_bist_non_price_and_ambiguous_words_do_not_fetch(self):
        for text in ('thy bileti kaç lira', 'garanti kredi faizi kaç', 'bim kaç kişi çalışıyor',
                     'koç üniversitesi kaç puan istiyor', 'şişe kaç lira', 'ev hissesi kaç', 'dün thy kaçtı',
                     'borsa nasıl çalışır', 'thy hissesi nedir', 'thy hissesi neden düştü',
                     'thy hissesi 400 olunca haber ver', 'thy hissesi için alarm kur', 'garanti kaç',
                     'sasa kaç', 'koç kaç', 'ATA hissesi kaç', 'thyao kaç', 'ABCD kaç'):
            with self.subTest(text=text):
                self.assertIsNone(self.ask(text))
        self.assertEqual(self.calls, [])

    def test_bist_amount_is_not_currency_conversion(self):
        self.assertIn('10 THY (THYAO) hissesi 3.125,00 TL eder', self.ask('10 thy hissesi kaç lira'))
        self.assertIn('10 Garanti (GARAN) hissesi 3.125,00 TL eder', self.ask('10 garanti hissesi kaç lira'))
        for text in ('thy hissesi kaç lira', '10 thy hissesi kaç lira', '10 garanti hissesi kaç', 'bist 100 kaç'):
            with self.subTest(text=text):
                self.assertFalse(finance.is_conversion(text))

    def test_bist_cache_uses_code_and_60_second_ttl(self):
        self.ask('thy hissesi kaç'); self.ask('THYAO kaç')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0], 'https://query1.finance.yahoo.com/v8/finance/chart/THYAO.IS?range=1d&interval=1d')
        key = 'bist:THYAO'
        stamp, value = finance._CACHE[key]
        finance._CACHE[key] = (stamp - 61, value)
        self.ask('THYAO kaç')
        self.assertEqual(len(self.calls), 2)

    def test_bist_404_is_not_found_and_other_http_errors_are_unavailable(self):
        for code in ('ABCD', 'ABCDE'):
            finance._CACHE.clear()
            def missing(url, **_):
                self.assertIn(f'/chart/{code}.IS?', url)
                raise ValueError('Kaynak HTTP yanıtı başarılı değil: 404')
            self.assertEqual(self.ask(code + ' hissesi kaç', missing), f'{code} borsa kodu bulunamadı.')
        self.assertIsNone(finance.parse('abcde hissesi kaç'))
        for status in (401, 429, 500):
            def failed(url, **_):raise ValueError(f'Kaynak HTTP yanıtı başarılı değil: {status}')
            self.assertIn('Yahoo Finance) şu an ulaşamadım', self.ask('THYAO kaç', failed))

    def test_bist_network_and_privacy_errors(self):
        def down(url, **_):raise OSError('ağ yok')
        self.assertEqual(self.ask('THYAO kaç', down),
                         'Fiyat kaynağına (Yahoo Finance) şu an ulaşamadım, biraz sonra tekrar dene.')
        with patch.object(public_sources, 'fetch', side_effect=down), patch('modules.ollama_hint.internet_up', return_value=False):
            from modules import ollama_hint
            self.assertEqual(finance.answer('THYAO kaç'), ollama_hint.NO_INTERNET)
        def private(url, **_):raise PermissionError('Web işlemleri gizli modda kapalı.')
        self.assertEqual(self.ask('THYAO kaç', private), 'Web işlemleri gizli modda kapalı.')

    def test_bist_malformed_missing_and_non_try_responses(self):
        bodies = [b'not json', b'null', b'[]', b'{}', b'{"chart":{"result":[]}}',
                  b'{"chart":{"result":[{"meta":null}]}}',
                  yahoo(currency='USD'), yahoo(currency=None), yahoo(regularMarketPrice=None),
                  yahoo(regularMarketPrice=-1), yahoo(regularMarketPrice='NaN'),
                  yahoo(regularMarketPrice='1e9999999'),
                  yahoo(regularMarketTime=None), yahoo(regularMarketTime=True), yahoo(regularMarketTime=1e100)]
        for body in bodies:
            with self.subTest(body=body):
                finance._CACHE.clear()
                calls = []
                def fetch(url, **kwargs):
                    calls.append((url, kwargs))
                    return {'body': body}
                self.assertIn('Yahoo Finance) şu an ulaşamadım', self.ask('THYAO kaç', fetch))
                self.assertEqual(len(calls), 1)
                self.assertLessEqual(calls[0][1]['max_bytes'], 200_000)

    def test_bist_previous_close_is_optional_with_fallback(self):
        def fetch(**changes):
            return lambda url, **_: {'body': yahoo(**changes)}
        self.assertNotIn('günlük', self.ask('THYAO kaç', fetch(chartPreviousClose=None)))
        finance._CACHE.clear()
        self.assertIn('günlük +%1,46', self.ask('THYAO kaç', fetch(chartPreviousClose=None, previousClose=308)))
        finance._CACHE.clear()
        self.assertNotIn('günlük', self.ask('THYAO kaç', fetch(chartPreviousClose=0)))
        finance._CACHE.clear()
        self.assertNotIn('günlük', self.ask('THYAO kaç', fetch(chartPreviousClose='1e-9999999')))

    def test_bist_does_not_call_a_model(self):
        with patch('modules.llm.ask', side_effect=AssertionError('Model çağrılmamalı')), \
             patch('modules.llm.chat', side_effect=AssertionError('Model çağrılmamalı')):
            self.assertIn('THY (THYAO) 312,50 TL', self.ask('thy hissesi kaç lira'))

    def test_engine_uses_intent_check_not_substring(self):
        source = Path(__file__).resolve().parents[1].joinpath('modules', 'engine_commands.py').read_text(encoding='utf-8')
        self.assertFalse('"dolar" in cmd_lower' in source or 'get_live_rate' in source)
        self.assertTrue('finance.answer(command)' in source)
        self.assertNotIn('open.er-api', Path(finance.__file__).read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
