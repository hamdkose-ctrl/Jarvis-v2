"""News evidence must be relevant to the user's requested topic, not merely fresh and dated."""
import unittest
from datetime import date
from unittest.mock import patch

from modules import news_pipeline


REQUEST = "Son 7 gündeki Türkiye yapay zekâ gelişmelerini araştır"


def _page(title, text, published="2026-10-27"):
    return {"title": title, "text": text, "published": published, "url": "https://example.com/haber"}


class NewsTopicRelevanceTests(unittest.TestCase):
    def _verify(self, article):
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
            return news_pipeline.verify(row, request=REQUEST, fetcher=lambda _url: b"page", today=date(2026, 10, 28), days=7)

    def test_fresh_but_unrelated_article_is_not_verified(self):
        result = self._verify(_page(
            "İsrail'de halk sandığa gitti, katılım oranı rekor kırdı",
            "İsrail genel seçimlerinde sandıklar kapandı ve parlamento sonuçları açıklandı.",
        ))
        self.assertNotEqual(result.get("verification"), "verified")
        self.assertIn("konu", result.get("reason", "").casefold())

    def test_relevant_turkey_ai_article_can_still_be_verified(self):
        result = self._verify(_page(
            "Türkiye'de yapay zekâ yatırımları için yeni program",
            "Türkiye yapay zekâ ekosistemi için yeni yatırım ve araştırma programını duyurdu.",
        ))
        self.assertEqual(result.get("verification"), "verified")


if __name__ == "__main__":
    unittest.main()
