"""Türkçe akademik kaynak: Crossref/DergiPark (kullanıcı isteği, 22 Kasım 2026).

Kullanıcı üç adres verdi: dergipark.org.tr, scholar.google.com, akademist.net. Ölçüm:
* DergiPark araması **bot doğrulamasına** düşüyor (arama doğrulama sayfası döndü),
* Google Akademik otomatik erişimi yasaklıyor (doğrulama sayfası),
* Akademist'in arama akışı yalnız statik sayfa döndürüyor.

DergiPark makalelerinin DOI'si Crossref'te olduğu için Türkçe kaynak **Crossref açık
API'sinden** gelir: anahtarsız, bot koruması yok, DOI bağlantısı doğrulanabilir.
Bot korumalı siteler kazınmaz; bu testler o sitelere istek atılmadığını da kilitler.
"""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import research_providers as rp

ROOT = Path(__file__).resolve().parents[1]

CROSSREF = {'status': 'ok', 'message': {'items': [
    {'title': ['Yapay Zeka Destekli Eğitim Araçları'],
     'DOI': '10.1234/dergipark.2026.1', 'language': 'tr',
     'abstract': '<jats:p>Bu çalışma yapay zeka araçlarının eğitimde kullanımını inceler.</jats:p>',
     'issued': {'date-parts': [[2026, 5, 3]]},
     'container-title': ['Eğitim Teknolojisi Dergisi']},
    {'title': ['Deep Learning for Weather'], 'DOI': '10.1234/en.2025.2', 'language': 'en',
     'abstract': 'A study about deep learning and weather forecasting.',
     'issued': {'date-parts': [[2025]]}, 'container-title': ['Journal of Weather']},
    {'title': ['Yapay Zeka ve Hukuk'], 'DOI': '10.1234/dergipark.2025.3',
     'abstract': 'Yapay zeka sistemlerinin hukuki sorumluluğu tartışılmaktadır.',
     'issued': {'date-parts': [[2025, 11]]},
     'container-title': ['Hukuk ve Teknoloji']},
]}}


def fetched(payload, url='https://api.crossref.org/works'):
    return {'body': json.dumps(payload).encode(), 'url': url}


class TurkishSearchTests(unittest.TestCase):
    def search(self, payload, query='yapay zeka', limit=5):
        with patch.object(rp.public_sources, 'fetch', return_value=fetched(payload)):
            return rp.search_turkish(query, limit=limit)

    def test_turkish_articles_come_back_with_doi_links(self):
        rows = self.search(CROSSREF)
        self.assertEqual(len(rows), 2)                       # İngilizce kayıt elendi
        self.assertEqual(rows[0]['title'], 'Yapay Zeka Destekli Eğitim Araçları')
        self.assertEqual(rows[0]['url'], 'https://doi.org/10.1234/dergipark.2026.1')
        self.assertEqual(rows[0]['provider'], 'crossref')
        self.assertEqual(rows[0]['published'], '2026-05-03')
        self.assertEqual(rows[0]['journal'], 'Eğitim Teknolojisi Dergisi')
        self.assertNotIn('<jats:p>', rows[0]['snippet'])      # HTML etiketi temizlenir
        self.assertEqual(rows[0]['language'], 'tr')

    def test_off_topic_records_are_dropped(self):
        payload = {'status': 'ok', 'message': {'items': [
            {'title': ['Tamamen Alakasız Bir Başlık'], 'DOI': '10.1234/x.1',
             'abstract': 'Konuyla ilgisi olmayan bir metin.'}]}}
        self.assertEqual(self.search(payload), [])

    def test_bad_answers_degrade_to_empty_list(self):
        for payload in ({'status': 'failed', 'message': []},
                        {'status': 'ok', 'message': {'items': 'bozuk'}},
                        {'status': 'ok'}):
            self.assertEqual(self.search(payload), [], payload)
        with patch.object(rp.public_sources, 'fetch', side_effect=ValueError('HTTP 429')):
            self.assertEqual(rp.search_turkish('yapay zeka'), [])
        with patch.object(rp.public_sources, 'fetch',
                          return_value={'body': b'<html>', 'url': 'https://api.crossref.org/works'}):
            self.assertEqual(rp.search_turkish('yapay zeka'), [])

    def test_invalid_doi_is_skipped(self):
        payload = {'status': 'ok', 'message': {'items': [
            {'title': ['Yapay Zeka Notları'], 'DOI': 'kötü-doi'}]}}
        self.assertEqual(self.search(payload), [])

    def test_bot_protected_sites_are_never_fetched(self):
        """DergiPark/Google Akademik kazınmaz; kaynak Crossref üzerinden gelir."""
        source = ROOT.joinpath('modules/research_providers.py').read_text(encoding='utf-8')
        for forbidden in ('dergipark.org.tr/tr/search', 'scholar.google', 'akademist.net'):
            self.assertNotIn(forbidden, source, forbidden)
        self.assertIn('api.crossref.org/works', source)


class MixedListingTests(unittest.TestCase):
    def test_turkish_rows_stay_turkish_and_arxiv_rows_are_translated(self):
        from modules.task_workers import academic_listing
        rows = [
            {'provider': 'crossref', 'title': 'Yapay Zeka ve Hukuk', 'url': 'https://doi.org/10.1/x',
             'published': '2025-11', 'snippet': 'Hukuki sorumluluk tartışılıyor.',
             'journal': 'Hukuk ve Teknoloji'},
            {'provider': 'arxiv', 'title': 'Attention Is All You Need',
             'url': 'https://arxiv.org/abs/1', 'published': '2017-06-12',
             'snippet': 'We propose the Transformer.'},
        ]
        answer = '{"items":[{"no":1,"baslik":"Dikkat Yeterli","ozet":"Transformer öneriliyor."}]}'
        with patch('modules.llm.ask', return_value=answer) as ask:
            out = academic_listing(rows, 'yapay zeka makaleleri', translate=True)
        self.assertEqual(ask.call_count, 1)                   # yalnız İngilizce kayıt çevrilir
        self.assertIn('Yapay Zeka ve Hukuk', out['text'])      # Türkçe kayıt aynen
        self.assertIn('Dergi: Hukuk ve Teknoloji', out['text'])
        self.assertIn('Dikkat Yeterli', out['text'])           # arXiv çevrildi
        self.assertIn('https://arxiv.org/abs/1', out['text'])  # bağlantı kayıttan
        self.assertIn('Crossref/DergiPark', out['text'])
        self.assertIn('arXiv', out['text'])

    def test_all_turkish_rows_need_no_model_call(self):
        from modules.task_workers import academic_listing
        rows = [{'provider': 'crossref', 'title': 'Yapay Zeka', 'url': 'https://doi.org/10.1/y',
                 'published': '2026', 'snippet': 'Özet metni burada.'}]
        with patch('modules.llm.ask', side_effect=AssertionError('model çağrılmamalı')):
            out = academic_listing(rows, 'yapay zeka makaleleri', translate=True)
        self.assertIn('Yapay Zeka', out['text'])
        self.assertNotIn('arXiv', out['text'])


if __name__ == '__main__':
    unittest.main()
