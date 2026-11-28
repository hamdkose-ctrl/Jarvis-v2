"""Çok kaynaklı araştırmada numaralı kaynak gösterimi (R1)."""
import unittest

from modules import research_providers


class CitationListTests(unittest.TestCase):
    def test_iki_kaynak_numarali_listelenir(self):
        metin = research_providers.format_citations([
            {"title": "Birinci", "url": "https://a"},
            {"title": "İkinci", "url": "https://b"},
        ])
        self.assertEqual(metin, "[1] Birinci — https://a\n[2] İkinci — https://b")

    def test_basliksiz_kaynak_bos_gecmez(self):
        metin = research_providers.format_citations([{"url": "https://c"}])
        self.assertEqual(metin, "[1] Başlıksız — https://c")

    def test_limit_uygulanir(self):
        satirlar = [{"title": str(i), "url": "https://x/%d" % i} for i in range(9)]
        metin = research_providers.format_citations(satirlar, limit=3)
        self.assertEqual(len(metin.split("\n")), 3)
        self.assertTrue(metin.startswith("[1] 0"))

    def test_gecersiz_girdi_hata_verir(self):
        with self.assertRaises(ValueError):
            research_providers.format_citations("metin")
        with self.assertRaises(ValueError):
            research_providers.format_citations([{"url": "https://a"}], limit=0)


if __name__ == "__main__":
    unittest.main()
