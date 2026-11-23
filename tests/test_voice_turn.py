"""Sıra alma kararı (A1): ölçülmüş bekleme kuralı.

Kilitlenen davranış:
* Cümle tamamsa 1,2 sn sessizlik yeter; yarım görünüyorsa 3,0 sn beklenir.
* "..." cümleyi kapatmaz (kullanıcı devam edecek).
* Bağlaç/edat/virgül ile biten yazı yarım sayılır — noktalama olsa bile.
* Yerel model "tamam" derse bekleme uzatılmaz; model "yarım" dese de yazı
  noktalamayla bitiyorsa 1,2 sn (model İngilizce eğitildi, kısa Türkçe cümleyi
  yarım sanıyor — Stonic'in ölçtüğü 14 cümlede 5 yanlış "yarım").
* Eski davranış (sabit 1 sn) bu modülün dışında kalır: tek anahtarla dönülür.
"""
import unittest

from modules import voice_turn as vt


class Sentinels(unittest.TestCase):
    def test_terminal(self):
        for text in ("Tamam.", "Ne zaman?", "Bunu yap!", 'Cevap "evet."', "Bitti?"):
            self.assertTrue(vt.terminal(text), text)
        for text in ("Tamam", "Bir de", "Yapıyorum...", "…", ""):
            self.assertFalse(vt.terminal(text), text)

    def test_ellipsis_is_not_an_end(self):
        self.assertTrue(vt.terminal("Bitti."))
        self.assertFalse(vt.terminal("Şey..."))
        self.assertFalse(vt.complete("Şey..."))

    def test_dangling(self):
        for text in ("gidip", "elma ve", "yarın ama", "çünkü", "bir", "Bu,", "yani,"):
            self.assertTrue(vt.dangling(text), text)
        for text in ("gittim", "elma.", "yarın gelirim", "Bitti!", "ona sahip"):
            self.assertFalse(vt.dangling(text), text)


class Completeness(unittest.TestCase):
    def test_complete_sentences(self):
        for text in ("Yarın saat üçte gelirim.", "Hava nasıl?", "Bunu yap!",
                     "Evet", "Tamam", "Teşekkürler"):
            self.assertTrue(vt.complete(text), text)

    def test_incomplete_sentences(self):
        for text in ("yarın saat üçte", "elma ve armut", "Bunu yapacağım ama",
                     "Yani,", "Bugün hava çok", ""):
            self.assertFalse(vt.complete(text), text)

    def test_punctuation_beats_dangling(self):
        """Virgülle biten cümle noktalama taşımıyor: yarım."""
        self.assertFalse(vt.complete("Dün geldim,"))
        self.assertTrue(vt.complete("Dün geldim."))


class WaitRule(unittest.TestCase):
    def test_finished_waits_short(self):
        self.assertEqual(vt.turn_wait("Yarın gelirim."), vt.FINISHED_WAIT_SECS)

    def test_unfinished_waits_long(self):
        self.assertEqual(vt.turn_wait("yarın gelirim ama"), vt.MAX_WAIT_SECS)

    def test_model_complete_shortens(self):
        self.assertEqual(vt.turn_wait("yarın geleceğim", model_complete=True),
                         vt.FINISHED_WAIT_SECS)

    def test_model_incomplete_does_not_override_punctuation(self):
        """Model 'yarım' dese de noktalama varsa 3 sn beklenmez."""
        self.assertEqual(vt.turn_wait("Yarın gelirim.", model_complete=False),
                         vt.FINISHED_WAIT_SECS)
        self.assertEqual(vt.turn_wait("yarın gelirim", model_complete=False),
                         vt.MAX_WAIT_SECS)

    def test_wait_is_bounded(self):
        self.assertLessEqual(vt.turn_wait("a" * 400), vt.MAX_WAIT_SECS)
        self.assertGreaterEqual(vt.FINISHED_WAIT_SECS, 1.0)


class DecisionLoop(unittest.TestCase):
    def test_cut_waits_for_silence_threshold(self):
        d = vt.TurnDecision()
        d.update("Yarın gelirim.")
        self.assertFalse(d.should_cut(0.0))
        self.assertFalse(d.should_cut(0.1))
        self.assertFalse(d.should_cut(1.1))
        self.assertTrue(d.should_cut(1.2))

    def test_unfinished_keeps_listening(self):
        d = vt.TurnDecision()
        d.update("elma ve")
        self.assertFalse(d.should_cut(1.3))
        self.assertFalse(d.should_cut(2.9))
        self.assertTrue(d.should_cut(3.0))

    def test_transcript_growth_flips_decision(self):
        d = vt.TurnDecision()
        d.update("yarın gelirim")
        self.assertFalse(d.should_cut(1.5))
        d.update("yarın gelirim.")
        self.assertTrue(d.should_cut(1.5))

    def test_model_failure_does_not_lock_turn(self):
        def broken(_text):
            raise RuntimeError("model yok")
        d = vt.TurnDecision(model=broken)
        self.assertEqual(d.update("Yarın gelirim."), vt.FINISHED_WAIT_SECS)
        self.assertTrue(d.should_cut(1.2))

    def test_model_verdict_used_when_available(self):
        d = vt.TurnDecision(model=lambda _t: True)
        self.assertEqual(d.update("yarın geleceğim"), vt.FINISHED_WAIT_SECS)
        d2 = vt.TurnDecision(model=lambda _t: "belirsiz")   # bool değil: yok sayılır
        self.assertEqual(d2.update("yarın geleceğim"), vt.MAX_WAIT_SECS)

    def test_resume_after_cut_is_counted(self):
        d = vt.TurnDecision()
        d.update("Yarın gelirim.", now=10.0)
        d.hear_speech(11.0)
        self.assertEqual(d.resumed_after_cut, 1)
        d.hear_speech(40.0)          # pencere dışı: sayılmaz
        self.assertEqual(d.resumed_after_cut, 1)

    def test_constants_match_measured_pattern(self):
        self.assertAlmostEqual(vt.VAD_STOP_SECS, 0.2)
        self.assertAlmostEqual(vt.FINISHED_WAIT_SECS, 1.2)
        self.assertAlmostEqual(vt.MAX_WAIT_SECS, 3.0)
        self.assertLess(vt.FINISHED_WAIT_SECS, vt.MAX_WAIT_SECS)


if __name__ == "__main__":
    unittest.main()
