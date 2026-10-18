"""Güncellik kuralı tek yerde (modules/freshness.py); router ve work_modes aynı kararı verir."""
import unittest

from modules import router, work_modes

FRESH = ["son haberler neler", "bugün dolar kaç", "dolar ne kadar", "altın fiyatı ne kadar", "güncel kur",
         "skor kaç", "euro ne kadar", "yeni haberler", "borsa son durum", "en son gelişmeler",
         "yapay zeka haberlerini anlat", "borsa durumu ne", "haberleri özetle", "altın durumu",
         "şimdi piyasa", "fiyat kaç"]
NOT_FRESH = ["dolar nedir", "haber tarihçesi", "kur nedir", "bugün ne var", "son dosyam", "Haberlere bak",
             "hava nasıl"]
WEATHER = ["bugün hava kaç derece", "hava şimdi"]


class FreshnessRuleTests(unittest.TestCase):
    def test_both_callers_agree_on_fresh_requests(self):
        for text in FRESH:
            with self.subTest(text=text):
                self.assertTrue(router._fresh_research_request(text))
                self.assertTrue(work_modes.fresh_external(text))

    def test_non_fresh_requests_stay_chat(self):
        for text in NOT_FRESH:
            with self.subTest(text=text):
                self.assertFalse(router._fresh_research_request(text))
                self.assertFalse(work_modes.fresh_external(text))

    def test_weather_is_work_mode_only(self):
        # Hava router'da kendi 'weather' niyetine gider; görev yürütücüsüne devredilmez.
        for text in WEATHER:
            with self.subTest(text=text):
                self.assertFalse(router._fresh_research_request(text))
                self.assertTrue(work_modes.fresh_external(text))


if __name__ == '__main__':
    unittest.main()
