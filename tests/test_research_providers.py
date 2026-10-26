import unittest
from modules.research_providers import (
    ResearchContext, compare_sources, extract_source, format_citation,
    rank_results, search_request, weekly_research_request,
)


class ResearchProviderTests(unittest.TestCase):
    def test_search_request_separates_search_from_extraction(self):
        request = search_request("yapay zeka", provider="searxng", limit=3)
        self.assertEqual(request["provider"], "searxng")
        self.assertEqual(request["method"], "GET")
        self.assertEqual(request["operation"], "search")
        self.assertNotIn("extract", request["operation"])

    def test_normalized_search_results_are_ranked_and_cited(self):
        results = rank_results([
            {"provider": "ddg", "title": "İkinci", "url": "https://b.test", "snippet": "B", "source_kind": "web"},
            {"provider": "arxiv", "title": "Birinci", "url": "https://a.test", "snippet": "A", "source_kind": "academic"},
        ], preferred_kinds=("academic", "web"))
        self.assertEqual(results[0]["title"], "Birinci")
        self.assertIn("[1] Birinci", format_citation(results[0], 1))

    def test_source_comparison_and_topic_context(self):
        comparison = compare_sources([
            {"url": "https://a.test", "claim": "A", "published": "2026-10-01"},
            {"url": "https://b.test", "claim": "B", "published": "2026-10-02"},
        ])
        self.assertEqual(comparison["status"], "conflict")
        context = ResearchContext(max_chars=80)
        context.add({"url": "https://a.test", "topic": "yapay zeka", "text": "a" * 100})
        self.assertLessEqual(context.characters, 80)
        self.assertEqual(context.sources(), ["https://a.test"])

    def test_extraction_is_separate_and_weekly_request_is_bounded(self):
        extracted = extract_source("https://example.com", fetcher=lambda url: {"url": url, "body": b"Merhaba"})
        self.assertEqual(extracted["text"], "Merhaba")
        request = weekly_research_request("Türkiye yapay zeka")
        self.assertEqual(request["window_days"], 7)
        self.assertEqual(request["cadence"], "weekly")

    def test_invalid_provider_and_source_are_rejected(self):
        with self.assertRaises(ValueError):
            search_request("x", provider="unknown")
        with self.assertRaises(ValueError):
            extract_source("http://example.com", fetcher=lambda url: {})


if __name__ == "__main__":
    unittest.main()
