"""Haber hattı doğrulama kusurları (#437/#439).

Canlı kusurlar (22 Kasım 2026):
* "seçim haberleri" isteğinde **kar yağışı** ve **tanker** haberi "doğrulanmış" sayıldı:
  konu, sayfanın ilerisindeki "Son seçim anketi yayınlandı!" bağlantısında geçiyordu.
* Katalog 19 kaynak, tur başına 8 taranıyor; sıranın sonundaki teknoloji indeksleri hiç
  taranmıyordu.
"""
from __future__ import annotations

import unittest

# Üretimdeki sıra: görev işçileri önce yüklenir (döngüsel içe aktarmayı kırar).
import modules.task_workers  # noqa: F401
from modules import model_free_news, news_pipeline


def article(title, body):
    return {'title': title, 'text': title + ' ' + body, 'url': 'https://ornek.com/h',
            'published': '2026-11-22'}


class CourtRelevanceTests(unittest.TestCase):
    def test_offtopic_article_is_rejected_even_when_a_sidebar_link_mentions_topic(self):
        page = article('Van kent merkezi, kar yağışı ile beyaza büründü',
                       'Vatandaşlar lapa lapa yağan kar altında yürüyüşe çıktı. '
                       'Yollar kapandı ve ekipler temizlik çalışması başlattı. '
                       '20 gözaltı Son seçim anketi yayınlandı!')
        with self.assertRaises(ValueError):
            model_free_news.quotes(page, 'seçim haberleri')

    def test_matching_article_is_accepted(self):
        page = article('Genar’ın kasım ayı seçim anketi yayınlandı',
                       'Ankete göre partilerin oy oranları açıklandı. '
                       'Seçim anketi 2 bin kişiyle yapıldı.')
        quotes = model_free_news.quotes(page, 'seçim haberleri')
        self.assertTrue(quotes)
        self.assertTrue(all('seçim' in quote.lower() for quote in quotes))

    def test_page_menu_sentence_is_never_evidence(self):
        page = article('Enflasyon verisi açıklandı',
                       'Güncel Politika Son Dakika Kategoriler Tümünü Gör İletişim Gizlilik. '
                       'Enflasyon kasım ayında yüzde 2 arttı ve beklentilerin altında kaldı.')
        quotes = model_free_news.quotes(page, 'enflasyon haberleri')
        self.assertEqual(len(quotes), 1)
        self.assertNotIn('Tümünü Gör', quotes[0])

    def test_title_match_is_enough_when_body_does_not_repeat_the_topic(self):
        """Başlık konuyu taşıyorsa haber konuyla ilgilidir; gövde cümlesi kanıt olarak kalır.

        Eskiden başlık eşleşmesi **her** cümleye puan ekliyordu; bu yüzden konuyla ilgisiz
        haber (kar yağışı) de "doğrulanmış" oluyordu. Artık başlık ya da giriş konuyu
        taşımak zorunda (bkz. test_offtopic_article_is_rejected...).
        """
        page = article('Seçim sonuçları açıklandı',
                       'Sandıklar kapandı ve sayım başladı. '
                       'İlçe bazında sonuçlar saat 22.00 itibarıyla netleşti.')
        quotes = model_free_news.quotes(page, 'seçim haberleri')
        self.assertEqual(len(quotes), 2)
        self.assertIn('Sandıklar kapandı', quotes[0])


class RotationTests(unittest.TestCase):
    ROWS = [{'url': f'https://kaynak{index}.com/', 'name': f'Kaynak {index}'}
            for index in range(12)]

    def test_core_sources_stay_and_tail_rotates_by_hour(self):
        ilk = news_pipeline._rotate(self.ROWS[4:], 4, now=1_796_083_200)
        sonra = news_pipeline._rotate(self.ROWS[4:], 4, now=1_796_083_200 + 3600)
        self.assertEqual(len(ilk), 4)
        self.assertNotEqual([row['url'] for row in ilk], [row['url'] for row in sonra])

    def test_every_source_is_scanned_within_a_day(self):
        gorulen = set()
        for saat in range(24):
            for row in news_pipeline._rotate(self.ROWS[4:], 4, now=1_796_083_200 + saat * 3600):
                gorulen.add(row['url'])
        self.assertEqual(gorulen, {row['url'] for row in self.ROWS[4:]})

    def test_small_catalog_is_not_rotated(self):
        self.assertEqual(news_pipeline._rotate(self.ROWS[4:6], 4), self.ROWS[4:6])
