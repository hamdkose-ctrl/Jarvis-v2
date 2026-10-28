"""News evidence must be relevant to the user's requested topic, not merely fresh and dated."""
import unittest
from datetime import date
from unittest.mock import patch

from modules import news_pipeline


REQUEST = "Son 7 gündeki Türkiye yapay zekâ gelişmelerini araştır"
LONG_REQUEST = (
    "Son 7 gündeki Türkiye yapay zekâ gelişmelerini araştır. Eski haberleri atla, "
    "erişilemeyen kaynağı geç, en az iki farklı yayıncıdan doğrulanmış haberleri "
    "kaynak, tarih ve bağlantıyla ver."
)


def _page(title, text, published="2026-10-27", url="https://example.com/haber"):
    return {"title": title, "text": text, "published": published, "url": url}


class NewsTopicRelevanceTests(unittest.TestCase):
    def _verify(self, article, request=REQUEST):
        row = {
            "url": article["url"],
            "title": article["title"],
            "summary": "",
            "source": "Test",
            "published_at": article["published"],
            "date_status": "present",
            "category": "teknoloji",
            "verification": "discovery_only",
        }
        with patch.object(news_pipeline, "article_reader", return_value=article), \
                patch("modules.model_free_news.quotes", return_value=[article["text"][:120]]):
            return news_pipeline.verify(row, request=request, fetcher=lambda _url: b"page",
                                        today=date(2026, 10, 28), days=7)

    def test_fresh_but_unrelated_article_is_not_verified(self):
        result = self._verify(_page(
            "İsrail'de halk sandığa gitti, katılım oranı rekor kırdı",
            "İsrail genel seçimlerinde sandıklar kapandı ve parlamento sonuçları açıklandı.",
        ))
        self.assertNotEqual(result.get("verification"), "verified")
        self.assertIn("konu", result.get("reason", "").casefold())

    def test_live_long_request_does_not_accept_instruction_word_overlap(self):
        result = self._verify(_page(
            "İsrail'de halk sandığa gitti, katılım oranı rekor kırdı",
            "İsrail seçimlerinde farklı kaynaklara göre sonuçların tarihi önemi değerlendirildi.",
        ), request=LONG_REQUEST)
        self.assertNotEqual(result.get("verification"), "verified")
        self.assertIn("konu", result.get("reason", "").casefold())

    def test_relevant_turkey_ai_article_can_still_be_verified(self):
        result = self._verify(_page(
            "Türkiye'de yapay zekâ yatırımları için yeni program",
            "Türkiye yapay zekâ ekosistemi için yeni yatırım ve araştırma programını duyurdu.",
        ))
        self.assertEqual(result.get("verification"), "verified")

    def test_one_verified_publisher_is_partial_even_when_all_sources_answer(self):
        verified = [{
            "news_article": {"url": "https://aa.com.tr/haber", "title": "Türkiye yapay zekâ", "published": "2026-10-27"}
        }]
        health = [
            {"source": "AA", "status": "ok", "item_count": 2, "reason": None},
            {"source": "NTV", "status": "ok", "item_count": 2, "reason": None},
        ]
        self.assertEqual(news_pipeline.status(health, verified=verified)["news_status"], "partial")

    def test_two_distinct_verified_publishers_can_complete(self):
        verified = [
            {"news_article": {"url": "https://aa.com.tr/haber", "title": "Türkiye yapay zekâ", "published": "2026-10-27"}},
            {"news_article": {"url": "https://ntv.com.tr/haber", "title": "Türkiye yapay zekâ", "published": "2026-10-27"}},
        ]
        health = [
            {"source": "AA", "status": "ok", "item_count": 2, "reason": None},
            {"source": "NTV", "status": "ok", "item_count": 2, "reason": None},
        ]
        self.assertEqual(news_pipeline.status(health, verified=verified)["news_status"], "complete")


if __name__ == "__main__":
    unittest.main()
