"""Ses metni temizliği (S3): yazı ekranda kalır, ses temiz okur.

Kilitlenen davranış (ölçüm 23 Kasım: temizlik yokken 331 karakter 48,9 sn sürüyordu,
temizlikle 244 karakter 19,8 sn):
* Adres/DOI/e-posta okunmaz.
* Markdown işaretleri ve tablo çizgileri seslenmez.
* `2026-06` → "Haziran iki bin yirmi altı"; `12.03.2026` → "on iki Mart iki bin yirmi altı".
* `%12` → "yüzde on iki"; `%12,5` → "yüzde on iki virgül beş"; `1.250` → "bin iki yüz elli".
* Parantez içi yıl ve `[3]` atıfları seslenmez.
* Hiçbir cümle uydurulmaz: kelime sırası korunur, içerik eklenmez.
"""
import unittest

from modules import voice_core, voice_text


class Cleanup(unittest.TestCase):
    def test_url_and_doi_removed(self):
        out = voice_text.speakable("Kaynak: https://doi.org/10.70269/10.70269/9146441933")
        self.assertNotIn("http", out)
        self.assertNotIn("10.70269", out)
        self.assertNotIn("doi", out.lower())

    def test_markdown_marks_removed(self):
        out = voice_text.speakable("**1.** Başlık — 2026-06")
        self.assertNotIn("*", out)
        self.assertTrue(out.startswith("Başlık"))

    def test_table_and_code_removed(self):
        out = voice_text.speakable("| a | b |\n|---|---|\n```kod```\nsonuç `x=1` var.")
        self.assertNotIn("|", out)
        self.assertNotIn("```", out)
        self.assertNotIn("x=1", out)

    def test_dates_in_words(self):
        self.assertIn("Haziran iki bin yirmi altı", voice_text.speakable("2026-06"))
        self.assertIn("on iki Mart iki bin yirmi altı",
                      voice_text.speakable("12.03.2026"))

    def test_percent_and_numbers(self):
        self.assertIn("yüzde on iki", voice_text.speakable("%12 artış"))
        self.assertIn("yüzde on iki virgül beş", voice_text.speakable("%12,5 artış"))
        self.assertIn("bin iki yüz elli", voice_text.speakable("1.250 kişi"))

    def test_plain_numbers_and_clock_untouched(self):
        """Düz sayı ve saat bozulmaz: ses motoru onları zaten doğru okuyor."""
        self.assertEqual(voice_text.speakable("Toplantın 14:00"), "Toplantın 14:00")
        self.assertEqual(voice_text.speakable("5 kayıt buldum"), "5 kayıt buldum")

    def test_citations_removed(self):
        out = voice_text.speakable("[3] numaralı kaynak (2021) bunu doğruluyor.")
        self.assertNotIn("[3]", out)
        self.assertNotIn("2021", out)
        self.assertIn("doğruluyor", out)

    def test_links_keep_label(self):
        out = voice_text.speakable("Ayrıntı [için bakın](https://example.com/x) burada.")
        self.assertIn("için bakın", out)
        self.assertNotIn("example.com", out)

    def test_emoji_and_spacing(self):
        out = voice_text.speakable("Harika 🎉   bir   sonuç.")
        self.assertNotIn("🎉", out)
        self.assertNotIn("   ", out)

    def test_empty_and_non_string(self):
        self.assertEqual(voice_text.speakable(""), "")
        self.assertEqual(voice_text.speakable(None), "")

    def test_number_words(self):
        cases = {0: "sıfır", 7: "yedi", 12: "on iki", 100: "yüz",
                 250: "iki yüz elli", 1250: "bin iki yüz elli",
                 2026: "iki bin yirmi altı", 1_500_000: "bir milyon beş yüz bin"}
        for value, words in cases.items():
            self.assertEqual(voice_text.number_to_words(value), words)

    def test_no_content_invented(self):
        """Temizlik metne cümle eklemez; kelimeler korunur."""
        src = "Yarın toplantı var ve gündem yoğun."
        out = voice_text.speakable(src)
        for word in ("Yarın", "toplantı", "gündem", "yoğun"):
            self.assertIn(word, out)


class SpeechPathUsesCleanup(unittest.TestCase):
    def test_chunks_have_no_urls(self):
        chunks = voice_core.speech_chunks("**1.** Deneme — 2026-06. Kaynak: https://doi.org/10.1/x")
        joined = " ".join(chunks)
        self.assertNotIn("http", joined)
        self.assertNotIn("*", joined)
        self.assertIn("Haziran", joined)

    def test_chunks_never_empty_for_plain_text(self):
        chunks = voice_core.speech_chunks("Yarın saat üçte buluşalım. Sonra kahve içeriz.")
        self.assertTrue(chunks)
        self.assertTrue(all(c.strip() for c in chunks))

    def test_text_of_only_link_is_not_spoken(self):
        chunks = voice_core.speech_chunks("https://example.com/abc")
        self.assertEqual("".join(chunks).strip(), "")


if __name__ == "__main__":
    unittest.main()
