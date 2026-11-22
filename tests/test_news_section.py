"""Haber bölümü: "makaleleri **ve haberleri**" isteği tek turda karşılanır.

Kullanıcı (22 Kasım 2026): cümlesinde haber de var ama Jarvis yalnız makale
listesi veriyordu; haber kısmı sessizce atlanıyordu.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from modules import research_evidence, task_workers

TITLE = "Apple, Siri’yi Yapay Zekâ Ajanına Dönüştürmek İstiyor: Büyük Değişim 2027'de!"
NAV = ("| TCL’in Fabrikasında 3 Gün VLOG PAHALI VS UYGUN FİYATLI KULAKLIĞA KARŞI | Huawei "
       "Freebuds Neo VS AirPods Pro 3 Tümünü Gör Kategoriler Haberler")
BODY = ("Apple, Siri’yi cihazlarınızı sizin yerinize kullanabilecek otonom bir yapay zekâ "
        "ajanına dönüştürmek için çalışmalara başladı.")


def article_row():
    return {'provider': 'crossref', 'title': 'Ortodontide Yapay Zeka Kullanımı',
            'url': 'https://doi.org/10.70269/x', 'published': '2026-06',
            'snippet': 'Ortodontide yapay zeka uygulamaları.'}


class NewsExcerptTests(unittest.TestCase):
    def test_page_chrome_and_title_repeat_are_dropped(self):
        secim = task_workers._news_excerpt([NAV, TITLE, BODY], 'yapay zeka haberleri', TITLE)
        self.assertEqual(secim, BODY)

    def test_title_with_turkish_capital_is_still_recognised(self):
        """'İ'.lower() iki karaktere açılır; kısaltma eşit uzunluk varsaymamalı (canlı bug)."""
        secim = task_workers._news_excerpt([TITLE, BODY], 'yapay zeka haberleri', TITLE)
        self.assertEqual(secim, BODY)

    def test_date_is_shown_as_day(self):
        self.assertEqual(task_workers._news_date('2026-11-22T15:00:00+03:00'), '2026-11-22')
        self.assertEqual(task_workers._news_date('2026-11-20'), '2026-11-20')


class NewsSectionTests(unittest.TestCase):
    def test_listing_appends_numbered_news_section(self):
        rows = [article_row()]
        news = [{'provider': 'news', 'title': TITLE, 'url': 'https://ornek.com/h1',
                 'published': '2026-11-20', 'snippet': BODY}]
        out = task_workers.academic_listing(rows, 'yapay zeka makaleleri ve haberleri',
                                            news_rows=news)
        text = out['text']
        self.assertIn('Bulduğum akademik kaynaklar (1 kayıt', text)
        self.assertIn('Son günlerin haberleri (1):', text)
        self.assertIn('**1.** ' + TITLE, text)
        self.assertIn('Kanıt: ' + BODY, text)
        self.assertIn('Kaynak: https://ornek.com/h1', text)
        self.assertEqual(out['news_rows'], 1)

    def test_missing_news_is_stated_not_silent(self):
        out = task_workers.academic_listing([article_row()], 'yapay zeka makaleleri ve haberleri',
                                            news_rows=[])
        self.assertIn('Son günlerde doğrulanmış haber bulunamadı.', out['text'])
        self.assertNotIn('news_rows', out)

    def test_no_news_request_keeps_the_old_output(self):
        out = task_workers.academic_listing([article_row()], 'yapay zeka makaleleri')
        self.assertNotIn('Son günlerin haberleri', out['text'])

    def test_news_heading_never_becomes_a_markdown_list(self):
        news = [{'provider': 'news', 'title': TITLE, 'url': 'https://ornek.com/h1',
                 'published': '2026-11-20', 'snippet': BODY}]
        text = task_workers.academic_listing([article_row()], 'yapay zeka', news_rows=news)['text']
        self.assertIn('**1.**', text)

    def test_news_rows_come_from_the_model_free_pipeline(self):
        result = {'verified': [{'news_article': {'title': TITLE, 'url': 'https://ornek.com/h1',
                                                 'published': '2026-11-20'},
                                'source': 'Webtekno', 'quotes': [NAV, TITLE, BODY]}]}
        with patch('modules.news_pipeline.run', return_value=result) as run:
            rows, _ = task_workers.news_rows_for('yapay zeka haberleri', 'hamdi')
        run.assert_called_once()
        self.assertEqual(rows[0]['published'], '2026-11-20')   # saat değil gün
        self.assertEqual(rows[0]['snippet'], BODY)             # menü değil gövde
        self.assertEqual(rows[0]['url'], 'https://ornek.com/h1')

    def test_pipeline_failure_is_soft(self):
        with patch('modules.news_pipeline.run', side_effect=RuntimeError('kaynak yok')):
            rows, result = task_workers.news_rows_for('yapay zeka haberleri', 'hamdi')
        self.assertEqual(rows, [])
        self.assertIsNone(result)


class PreviewBudgetTests(unittest.TestCase):
    def test_combined_listing_is_not_cut_at_1200(self):
        news = [{'provider': 'news', 'title': TITLE, 'url': 'https://ornek.com/h1',
                 'published': '2026-11-20', 'snippet': BODY}]
        out = task_workers.academic_listing([article_row()], 'yapay zeka', news_rows=news)
        text = str(out['text']) + '\n' + 'dolgu ' * 400
        out['text'] = text
        preview = research_evidence.preview(out)
        self.assertGreater(len(preview), 1200)                 # haber bölümü kesilmiyor
        self.assertLessEqual(len(preview), 2400)


class WiringTests(unittest.TestCase):
    def test_research_worker_asks_for_news_when_requested(self):
        source = Path(__file__).resolve().parents[1].joinpath(
            'modules/task_workers.py').read_text(encoding='utf-8')
        self.assertIn('haber = news_rows_for(user_request, owner)[0] if news else None', source)
        self.assertIn('academic_listing(academic, user_request, translate=True, news_rows=haber)',
                      source)

    def test_model_outage_path_includes_news(self):
        source = Path(__file__).resolve().parents[1].joinpath(
            'modules/core_brain_adapter.py').read_text(encoding='utf-8')
        self.assertIn('haber_istendi = research_evidence.publication_news_requested(request)', source)
        self.assertIn('news_rows=haber', source)
