"""4A: arXiv anahtarsız akademik arama ve araştırma işçisine bağlanması."""
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import research_providers as rp

ATOM = (b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        b'<entry><id>https://arxiv.org/abs/2401.00001v1</id>'
        b'<title>Attention Is All You Need Again</title>'
        b'<summary>  We study attention\nmodels.  </summary>'
        b'<published>2024-01-02T00:00:00Z</published></entry>'
        b'<entry><id>https://arxiv.org/abs/2401.00002v1</id>'
        b'<title>Ikinci calisma</title><summary>Ozet</summary>'
        b'<published>2024-01-03T00:00:00Z</published></entry>'
        b'<entry><id>http://arxiv.org/abs/2401.00003v1</id><title>Http gelen kayit</title>'
        b'<summary>Y</summary><published>2024-01-04T00:00:00Z</published></entry>'
        b'<entry><id>ftp://arxiv.org/abs/2401.00004v1</id><title>Gecersiz sema</title>'
        b'<summary>X</summary></entry></feed>')


def _fetch(url, **_):
    return {"body": ATOM, "url": "https://export.arxiv.org/api/query",
            "content_type": "application/atom+xml"}


class AcademicRequestTests(unittest.TestCase):
    def test_academic_language_is_detected(self):
        for text in ("yapay zeka makalesi bul", "arxiv de transformer",
                     "bilimsel çalışma özetle", "literatur taramasi"):
            self.assertTrue(rp.academic_requested(text), text)
        for text in ("hava nasıl", "ekran görüntüsü al", "sesi 20 yap"):
            self.assertFalse(rp.academic_requested(text), text)

    def test_arxiv_results_are_normalized_and_limited(self):
        with patch("modules.research_providers.public_sources.fetch", side_effect=_fetch):
            rows = rp.search_academic("attention", limit=2)
        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual(first["provider"], "arxiv")
        self.assertEqual(first["source_kind"], "academic")
        self.assertEqual(first["url"], "https://arxiv.org/abs/2401.00001v1")
        self.assertEqual(first["snippet"], "We study attention models.")
        self.assertEqual(first["title"], "Attention Is All You Need Again")

    def test_http_ids_are_upgraded_and_invalid_schemes_dropped(self):
        with patch("modules.research_providers.public_sources.fetch", side_effect=_fetch):
            rows = rp.search_academic("attention", limit=5)
        urls = [row["url"] for row in rows]
        # arXiv <id> alanı http:// gelir; https'e yükseltilir (canlı doğrulandı).
        self.assertIn("https://arxiv.org/abs/2401.00003v1", urls)
        self.assertNotIn("ftp://arxiv.org/abs/2401.00004v1", urls)

    def test_transport_failure_returns_empty_list_instead_of_raising(self):
        with patch("modules.research_providers.public_sources.fetch",
                   side_effect=ValueError("blocked")):
            self.assertEqual(rp.search_academic("attention"), [])
        with patch("modules.research_providers.public_sources.fetch",
                   return_value={"body": b"<not-xml", "url": "https://export.arxiv.org"}):
            self.assertEqual(rp.search_academic("attention"), [])

    def test_academic_listing_cites_papers_without_claim_verification(self):
        from modules.task_workers import academic_listing
        rows = [
            {"provider": "arxiv", "title": "Dilated Neighborhood Attention",
             "url": "https://arxiv.org/abs/2209.15001v3", "published": "2022-09-29",
             "snippet": "We propose a hierarchical transformer."},
            {"provider": "arxiv", "title": "Ikinci makale",
             "url": "https://arxiv.org/abs/2105.02723v1", "published": "2021-05-06",
             "snippet": "Second abstract."},
        ]
        out = academic_listing(rows, "Yapay zeka makaleleri araştır")
        self.assertEqual(out["state"], "done")
        self.assertEqual(out["source"], "https://arxiv.org/abs/2209.15001v3")
        self.assertIn("1) Dilated Neighborhood Attention (2022-09-29)", out["text"])
        self.assertIn("https://arxiv.org/abs/2105.02723v1", out["text"])
        self.assertGreaterEqual(out["source_chars"], 80)
        self.assertTrue(out["academic_listing"])
        # Kaynak kanıtı sözleşmesi: task_results.check araştırma çıktısını kabul eder.
        from modules import task_results
        task_results.check("research", out)

    def test_research_worker_wires_academic_candidates_first(self):
        source = Path(__file__).resolve().parents[1].joinpath("modules/task_workers.py").read_text(
            encoding="utf-8")
        self.assertIn("research_providers.search_academic(data['query'])", source)
        self.assertIn("research_providers.academic_requested(user_request)", source)
        # Akademik sonuç varken DDG engeli turu düşürmez.
        self.assertIn("modules/task_workers.py:research_public_search", source)
        # Makale listesi isteği model doğrulamasına düşmez (canlı hata 15:01).
        self.assertIn("return academic_listing(academic, user_request)", source)


if __name__ == "__main__":
    unittest.main()
