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


COINGECKO = {'bitcoin': 2449000.0, 'pax-gold': 109000.0}


def coingecko(url):
    ids = re.search(r'ids=([a-z0-9,-]+)', url).group(1).split(',')
    return json.dumps({i: {'try': COINGECKO[i], 'try_24h_change': 1.5, 'last_updated_at': 1792348920} for i in ids}).encode()


def btcturk(pair):
    last, daily = BTCTURK[pair]
    return json.dumps({'data': [{'pair': pair, 'pairNormalized': pair[:-3] + '_TRY', 'timestamp': 1792348920000,
                                 'last': last, 'high': last, 'low': last, 'dailyPercent': daily,
                                 'numeratorSymbol': pair[:-3], 'denominatorSymbol': 'TRY'}],
                       'success': True, 'message': None, 'code': 0}).encode()


class FinanceTest(unittest.TestCase):
    def setUp(self):
        finance._CACHE.clear()
        self.calls = []

    def fetch_ok(self, url, **_):
        self.calls.append(url)
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
                self.assertIn('BtcTurk BTC/TRY son işlem 18.10.2026', out)
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
            if 'btcturk.com' in url:raise OSError('yok')
            return self.fetch_ok(url)
        out = self.ask('bitcoin kaç lira', down)
        self.assertIn('Bitcoin 2.449.000,00 TL (günlük +%1,50)', out)
        self.assertIn('CoinGecko BTC/TRY 18.10.2026', out)
        gold = self.ask('gram altın ne kadar', down)
        self.assertIn('Gram altın 3.504,43 TL', gold);self.assertIn('CoinGecko PAXG/TRY', gold)
        def both(url, **_):
            if 'btcturk.com' in url or 'coingecko.com' in url:raise OSError('yok')
            return self.fetch_ok(url)
        finance._CACHE.clear()
        self.assertIn('Fiyat kaynağına (BtcTurk ve CoinGecko) şu an ulaşamadım', self.ask('bitcoin kaç lira', both))
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

    def test_market_cache_is_short(self):
        self.ask('bitcoin kaç lira');self.ask('btc ne kadar')
        self.assertEqual(sum('BTCTRY' in u for u in self.calls), 1)
        key = 'bt:BTCTRY'
        stamp, value = finance._CACHE[key]
        finance._CACHE[key] = (stamp - finance.MARKET_TTL - 1, value)
        self.ask('bitcoin kaç lira')
        self.assertEqual(sum('BTCTRY' in u for u in self.calls), 2)

    def test_live_source_script_reports_each_source(self):
        import contextlib, importlib.util, io
        path = Path(__file__).resolve().parents[1] / 'scripts' / 'finans_kaynak_testi.py'
        spec = importlib.util.spec_from_file_location('finans_kaynak_testi', path)
        script = importlib.util.module_from_spec(spec);spec.loader.exec_module(script)
        out = io.StringIO()
        with patch.object(public_sources, 'fetch', side_effect=self.fetch_ok), contextlib.redirect_stdout(out):
            self.assertEqual(script.main(), 0)
        self.assertEqual(out.getvalue().count('GEÇTİ'), 6)
        self.assertIn('Gram altın 3.512,47 TL', out.getvalue())
        def down(url, **_):raise OSError('yok')
        out = io.StringIO()
        with patch.object(public_sources, 'fetch', side_effect=down), patch('modules.ollama_hint.internet_up', return_value=False), \
             patch('modules.diagnostics.record_failure'), contextlib.redirect_stdout(out):
            self.assertEqual(script.main(), 1)
        self.assertEqual(out.getvalue().count('BAŞARISIZ'), 6)

    def test_engine_uses_intent_check_not_substring(self):
        source = Path(__file__).resolve().parents[1].joinpath('modules', 'engine_commands.py').read_text(encoding='utf-8')
        self.assertFalse('"dolar" in cmd_lower' in source or 'get_live_rate' in source)
        self.assertTrue('finance.answer(command)' in source)
        self.assertNotIn('open.er-api', Path(finance.__file__).read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
