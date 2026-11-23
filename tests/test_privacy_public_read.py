"""B — Yerel/gizli modda herkese açık kaynak okuma izni.

Kilitlenen davranış:
* Varsayılan KAPALI: yerel modda hiçbir adres okunamaz (eski davranış aynen korunur).
* Açıkken yalnız izin listesindeki herkese açık kaynaklar okunur (akademik + 19 haber sitesi).
* İzin listesi dışındaki adres (ve benzer görünen sahte alan adı) yine kapalıdır.
* Normal modda web zaten açık; bu anahtar hiçbir şeyi değiştirmez.
Ağ çağrısı yoktur.
"""
import unittest
from unittest.mock import patch

from modules import privacy, public_sources


class _Mode:
    """Gizlilik modunu ve ayar sözlüğünü sabit tutan yardımcı."""

    def __init__(self, mode, settings=None):
        self.settings = dict(settings or {})
        self.settings.setdefault("privacy_mode", mode)

    def __enter__(self):
        self._m = patch.object(privacy, "mode", return_value=self.settings["privacy_mode"])
        self._s = patch.object(privacy, "load_settings", return_value=self.settings)
        self._m.start()
        self._s.start()
        return self

    def __exit__(self, *exc):
        self._s.stop()
        self._m.stop()
        return False


ACADEMIC = ["https://export.arxiv.org/api/query?search_query=all:quantum",
            "https://api.crossref.org/works?query=deprem",
            "https://doi.org/10.1038/nature12373"]
NEWS = ["https://www.aa.com.tr/tr/gundem",
        "https://www.bbc.com/turkce",
        "https://www.kap.org.tr/tr/",
        "https://tr.euronews.com/",
        "https://www.trthaber.com/"]


class PublicReadSwitch(unittest.TestCase):
    def test_default_off(self):
        with _Mode("yerel"):
            self.assertFalse(privacy.public_read_enabled())
            for url in ACADEMIC + NEWS:
                self.assertFalse(privacy.public_read(url), url)

    def test_yerel_mode_opens_only_allowlisted(self):
        with _Mode("yerel", {"public_read": True}):
            self.assertTrue(privacy.public_read_enabled())
            for url in ACADEMIC + NEWS:
                self.assertTrue(privacy.public_read(url), url)
            for url in ("https://www.google.com/search?q=x",
                        "https://example.org/makale",
                        "https://arxiv.org.evil.com/api",
                        "https://www.aa.com.tr.evil.net/",
                        "http://localhost:8000/"):
                self.assertFalse(privacy.public_read(url), url)

    def test_gizli_mode_also_opens(self):
        with _Mode("gizli", {"public_read": True}):
            self.assertTrue(privacy.public_read("https://doi.org/10.1/x"))

    def test_allowlist_covers_all_19_news_sources(self):
        from modules import publisher_news
        self.assertEqual(len(publisher_news.GENERAL_SOURCES), 19)
        with _Mode("yerel", {"public_read": True}):
            for row in publisher_news.GENERAL_SOURCES:
                self.assertTrue(privacy.public_read(row["url"]), row["url"])

    def test_normal_mode_unaffected(self):
        with _Mode("normal", {"public_read": False}):
            self.assertIsNone(privacy.blocked("web"))
            self.assertFalse(privacy.public_read("https://export.arxiv.org/api/query"))
        with _Mode("normal", {"public_read": True}):
            self.assertIsNone(privacy.blocked("web"))

    def test_blocked_message_unchanged_when_off(self):
        with _Mode("yerel", {"public_read": False}):
            msg = privacy.blocked("web")
            self.assertIn("kapalı", msg)


class FetchGate(unittest.TestCase):
    """public_sources.fetch tek kapıdır: karar ağa çıkmadan verilir."""

    def test_off_blocks_even_allowlisted(self):
        with _Mode("yerel", {"public_read": False}):
            with self.assertRaises(PermissionError):
                public_sources.fetch("https://export.arxiv.org/api/query?search_query=all:x")

    def test_on_blocks_outside_allowlist(self):
        with _Mode("yerel", {"public_read": True}):
            with self.assertRaises(PermissionError):
                public_sources.fetch("https://example.org/makale")

    def test_on_lets_allowlisted_reach_network_step(self):
        """Ağa çıkılmaz; kapı geçilir, sıradaki adım (adres doğrulama) çalışır."""
        with _Mode("yerel", {"public_read": True}):
            with patch.object(public_sources, "address", side_effect=ValueError("test-adresi")):
                with self.assertRaises(ValueError):
                    public_sources.fetch("https://export.arxiv.org/api/query?search_query=all:x")

    def test_normal_mode_still_reads_any_public_host(self):
        with _Mode("normal", {"public_read": False}):
            with patch.object(public_sources, "address", side_effect=ValueError("test-adresi")):
                with self.assertRaises(ValueError):
                    public_sources.fetch("https://example.org/makale")


if __name__ == "__main__":
    unittest.main()
