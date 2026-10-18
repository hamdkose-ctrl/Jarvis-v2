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


class FinanceTest(unittest.TestCase):
    def setUp(self):
        finance._CACHE.clear()
        self.calls = []

    def fetch_ok(self, url, **_):
        self.calls.append(url)
        if 'tcmb.gov.tr' in url:
            return {'url': url, 'body': TCMB_XML, 'content_type': 'text/xml'}
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

    def test_engine_uses_intent_check_not_substring(self):
        source = Path(__file__).resolve().parents[1].joinpath('modules', 'engine_commands.py').read_text(encoding='utf-8')
        self.assertFalse('"dolar" in cmd_lower' in source or 'get_live_rate' in source)
        self.assertTrue('finance.answer(command)' in source)
        self.assertNotIn('open.er-api', Path(finance.__file__).read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
