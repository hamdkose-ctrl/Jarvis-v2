"""Güncellik kuralı tek yerde (modules/brain_understanding); Core plan aynı kararı yürütücüye devreder.

PR10c: eski `modules/router.py` + `modules/work_modes.py` + `modules/freshness.py` zinciri kaldırıldı.
Aynı tablo artık canonical sınırda doğrulanır: Understanding taze dış veriyi tanır,
`brain_core_map.core_plan` onu tek bir Core niyetine (task/research) çevirir.
"""
import unittest

from modules import brain_core_map, brain_understanding
from modules.brain_contracts import ActiveContext

FRESH = ["son haberler neler", "bugün dolar kaç", "dolar ne kadar", "altın fiyatı ne kadar", "güncel kur",
         "skor kaç", "euro ne kadar", "yeni haberler", "borsa son durum", "en son gelişmeler",
         "yapay zeka haberlerini anlat", "borsa durumu ne", "haberleri özetle", "altın durumu",
         "şimdi piyasa", "fiyat kaç"]
NOT_FRESH = ["dolar nedir", "haber tarihçesi", "kur nedir", "bugün ne var", "son dosyam", "Haberlere bak",
             "hava nasıl",
             # "kur" burada fiildir: hatırlatma/masaüstü kurma sahibine gitmeli, taze döviz verisi değil.
             "yarın için alarm kur", "saat kaç oldu acaba yarın için alarm kur", "masaüstünü düzenle"]
WEATHER = ["bugün hava kaç derece", "hava şimdi"]


def decide(text: str):
    semantic = brain_understanding.understand(
        owner="hamdi", request_id="rid-freshness", text=text,
        active_context=ActiveContext(owner="hamdi", request_id="rid-freshness"),
        candidates=(), references=())
    return semantic.capability_hint, brain_core_map.core_plan(semantic.capability_hint, semantic.arguments)


class FreshnessRuleTests(unittest.TestCase):
    def test_fresh_requests_are_one_canonical_research_plan(self):
        for text in FRESH:
            with self.subTest(text=text):
                hint, plan = decide(text)
                self.assertEqual(hint, "research.search")
                self.assertEqual(plan, ("task", {"query": text, "route": "PRIVATE"}))

    def test_non_fresh_requests_stay_chat(self):
        for text in NOT_FRESH:
            with self.subTest(text=text):
                hint, _plan = decide(text)
                self.assertNotEqual(hint, "research.search")

    def test_weather_is_its_own_capability_not_a_research_task(self):
        # Hava araştırma görevine devredilmez; canonical sınırda kendi yeteneğidir.
        for text in WEATHER:
            with self.subTest(text=text):
                hint, plan = decide(text)
                self.assertNotEqual(hint, "research.search")
                self.assertNotEqual((plan or ("", ""))[0], "task")

    def test_explicit_freshness_wins_over_definition_pattern(self):
        # Açık güncellik işareti "nedir" gibi tanım kalıbıyla iptal edilmemeli;
        # taze işaret olmayan sade tanım soruları ise statik kalmalı.
        static = ["dolar nedir", "kur nedir", "nvidia nedir", "altın nedir"]
        fresh = ["bugünkü dolar kuru nedir", "güncel altın fiyatı nedir",
                 "son nvidia haberi nedir", "mevcut altın fiyatı nedir", "şu an dolar kuru nedir"]
        for text in static:
            with self.subTest(static=text):
                self.assertNotEqual(decide(text)[0], "research.search")
        for text in fresh:
            with self.subTest(fresh=text):
                self.assertEqual(decide(text)[0], "research.search")

    def test_the_fresh_rule_has_one_owner(self):
        # Aynı cümle hem research hem başka bir capability olarak önerilemez: tanıyıcı tek yerde.
        from modules import brain_gates
        for text in FRESH:
            with self.subTest(text=text):
                self.assertFalse(brain_gates.deterministic_fast_gate(
                    owner="hamdi", request_id="rid-freshness", text=text,
                    active_context=ActiveContext(owner="hamdi", request_id="rid-freshness")).matched)


if __name__ == '__main__':
    unittest.main()
