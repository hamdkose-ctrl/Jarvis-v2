"""News evidence must be relevant to the user's requested topic, not merely fresh and dated."""
import unittest
from datetime import date
from unittest.mock import patch

from modules import news_pipeline, publisher_news


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
        with patch.object(news_pipeline, "article_reader", return_value=article):
            return news_pipeline.verify(row, request=request, fetcher=lambda _url: b"page",
                                        today=date(2026, 10, 28), days=7)

    def test_fresh_but_unrelated_article_is_not_verified(self):
        result = self._verify(_page(
            "İsrail'de halk sandığa gitti, katılım oranı rekor kırdı",
            "İsrail genel seçimlerinde sandıklar kapandı ve parlamento sonuçları açıklandı. "
            "Sonuçlar farklı kaynaklarda ve tarihsel bağlamda değerlendirildi.",
        ), request=LONG_REQUEST)
        self.assertNotEqual(result.get("verification"), "verified")
        self.assertIn("konu", result.get("reason", "").casefold())

    def test_relevant_turkey_ai_article_can_still_be_verified(self):
        result = self._verify(_page(
            "Türkiye'de yapay zekâ yatırımları için yeni program",
            "Türkiye yapay zekâ ekosistemi için yeni yatırım ve araştırma programını duyurdu. "
            "Program üniversiteler ve teknoloji şirketleri arasında ortak projeleri destekleyecek.",
        ))
        self.assertEqual(result.get("verification"), "verified")

    def test_ai_request_prioritizes_existing_topical_publishers_inside_read_budget(self):
        rows = publisher_news.sources_for(LONG_REQUEST)
        names = [row["name"] for row in rows[:news_pipeline.MAX_SOURCES]]
        self.assertIn("DonanımHaber", names)
        self.assertIn("Webtekno", names)
        self.assertIn("TÜBİTAK", names)
        self.assertGreaterEqual(len({publisher_news.publisher_key(row["url"]) for row in rows[:news_pipeline.MAX_SOURCES]}), 2)

    def test_completion_evidence_still_requires_two_distinct_publishers(self):
        one = [{"news_article": {"url": "https://www.aa.com.tr/tr/haber"}}]
        two = one + [{"news_article": {"url": "https://www.ntv.com.tr/haber"}}]
        self.assertFalse(news_pipeline.enough_evidence(one))
        self.assertTrue(news_pipeline.enough_evidence(two))


if __name__ == "__main__":
    unittest.main()
