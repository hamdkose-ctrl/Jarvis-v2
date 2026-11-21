"""Cümle tonu: düzlüğü kıran kural, sağlayıcıya gitmeden sınanır.

Ölçüm (21 Kasım): aynı cevabın perde hareketi 4.6 yarım ton; kullanıcı bunu
"ses robot gibi, duyguyu vermiyor" diye duyuyor. Edge'in duygu stili yok ve
Gemini'nin ücretsiz sesi günde 10 istek. Kalan tek ücretsiz yol, cümlenin
kendi noktalamasından gelen ölçülü bir ton: soru yukarı, ünlem parlak, uzun
cümle biraz yavaş.

Bu kural saftır (ağ yok, saat yok, rastgelelik yok): aynı metin her zaman aynı
(rate, pitch) çiftini verir, yoksa "ton" adı altında tahmin dağıtılmış olurdu.
"""
import unittest

from modules import voice_edge


class ProsodyTests(unittest.TestCase):
    def test_plain_statement_keeps_the_voice_untouched(self):
        self.assertEqual(voice_edge.prosody("Bugün hava açık."), (0, 0))

    def test_question_settles_slightly_without_touching_pitch(self):
        # Perde oynatmak erkek sesinde tınıyı bozuyor ("gay gibi"); canlılık tempodan.
        rate, pitch = voice_edge.prosody("Yarın yağmur var mı?")
        self.assertEqual(pitch, 0)
        self.assertEqual(rate, -2)

    def test_exclamation_is_faster_but_keeps_the_same_voice(self):
        rate, pitch = voice_edge.prosody("Harika haber!")
        self.assertEqual(pitch, 0, "tını değişmemeli")
        self.assertEqual(rate, 8)

    def test_long_sentence_slows_down_without_changing_pitch(self):
        rate, pitch = voice_edge.prosody("x" * 121 + ".")
        self.assertEqual(pitch, 0)
        self.assertEqual(rate, -3)

    def test_requested_rate_is_the_baseline_not_replaced(self):
        # Kullanıcının hız tercihi korunur; ton onun üzerine eklenir.
        self.assertEqual(voice_edge.prosody("Yağmur var mı?", speaking_rate=-10), (-12, 0))

    def test_rate_never_leaves_the_supported_range(self):
        rate, _ = voice_edge.prosody("Harika haber!", speaking_rate=40)
        self.assertEqual(rate, 40)
        rate, _ = voice_edge.prosody("Yağmur var mı?", speaking_rate=-40)
        self.assertEqual(rate, -40)

    def test_question_mark_inside_a_word_does_not_rise(self):
        # "?" cümlenin sonundaysa ton; ortada geçen işaret ton istemez.
        self.assertEqual(voice_edge.prosody("Bunu ? diye yazdı."), (0, 0))

    def test_empty_text_passes_through(self):
        self.assertEqual(voice_edge.prosody("   "), (0, 0))

    def test_ssml_parameters_are_what_edge_accepts(self):
        self.assertEqual(voice_edge.prosody_ssml(8, 0), ("+8%", "+0Hz"))
        self.assertEqual(voice_edge.prosody_ssml(0, 0), ("+0%", "+0Hz"))


if __name__ == "__main__":
    unittest.main()
