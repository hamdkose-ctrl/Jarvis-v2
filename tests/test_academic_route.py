"""Akademik istek haber indeksine düşerse araştırma adımına çevrilir.

Canlı ölçüm (22 Kasım 2026): "Yapay zeka makaleleri araştır" isteği
`data.headlines` ile donanimhaber/webtekno başlıklarına gitti; arXiv hattı hiç
çalışmadı. Kaynak türü kararı planlayıcı istemine bırakılmıyor.
"""
import unittest

from modules import goal_executor, goal_tools, research_providers


class AcademicLanguageTests(unittest.TestCase):
    def test_academic_wording_is_detected_in_inflected_forms(self):
        for text in ("Yapay zeka makaleleri araştır", "yapay zeka makalesi bul",
                     "makaleleri özetle", "arxiv de transformer", "bilimsel çalışma",
                     "tezi özetle", "literatür taraması"):
            self.assertTrue(research_providers.academic_requested(text), text)

    def test_news_and_daily_requests_are_not_academic(self):
        for text in ("yapay zeka haberleri", "günlük haberler", "hava nasıl",
                     "sesi 20 yap", "ekran görüntüsü al"):
            self.assertFalse(research_providers.academic_requested(text), text)


class AcademicRouteTests(unittest.TestCase):
    def test_headlines_step_becomes_research_for_academic_request(self):
        kind, data = goal_executor._academic_route(
            {"request": "Yapay zeka makaleleri araştır"}, "data",
            {"operation": "headlines", "url": "https://www.donanimhaber.com/",
             "query": "yapay zeka"})
        self.assertEqual(kind, "research")
        self.assertEqual(data["query"], "yapay zeka")
        self.assertEqual(data["question"], "Yapay zeka makaleleri araştır")
        # Üretim doğrulaması: araştırma girdisi tam olarak bir url VEYA sorgu ister.
        goal_tools.validate("research", data)

    def test_news_request_keeps_the_headlines_step(self):
        payload = {"operation": "headlines", "url": "https://x.test/", "query": "yapay zeka"}
        kind, data = goal_executor._academic_route(
            {"request": "yapay zeka haberleri"}, "data", dict(payload))
        self.assertEqual(kind, "data")
        self.assertEqual(data, payload)

    def test_other_tools_and_operations_are_untouched(self):
        payload = {"operation": "sources"}
        self.assertEqual(
            goal_executor._academic_route({"request": "makale araştır"}, "data", dict(payload)),
            ("data", payload))
        self.assertEqual(
            goal_executor._academic_route({"request": "makale araştır"}, "research", {"query": "x"}),
            ("research", {"query": "x"}))

    def test_request_without_query_falls_back_to_the_request_text(self):
        kind, data = goal_executor._academic_route(
            {"request": "Büyük dil modelleri makaleleri"}, "data",
            {"operation": "headlines", "url": "https://x.test/"})
        self.assertEqual(kind, "research")
        self.assertEqual(data["query"], "Büyük dil modelleri makaleleri")


if __name__ == "__main__":
    unittest.main()
