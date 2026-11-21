"""Uzun cevap seslendirmesi: tam cümlede kesilir, kapanış cümlesi söylenir.

Kullanıcı isteği (21 Kasım): çok uzun cevapları baştan sona okumak dinlenemiyor
(300 karakter ≈ 28 sn, 600 karakter ≈ 60 sn konuşma), ama ses ASLA cümle
ortasında kesilmemeli ve kesildiği hissi verilmemeli.
"""
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.voice_core import (
    SPEECH_LONG_ANSWER_CHARS, SPEECH_REMAINDER_NOTE, SpeechRequest, VoiceCatalog,
    VoiceCoordinator, VoiceSpec, speech_chunks, speech_summary,
)

LONG = ("Bugün İstanbul'da hava parçalı bulutlu ve on sekiz derece civarında seyredecek. "
        "Öğleden sonra rüzgar biraz sertleşecek, akşam saatlerinde ise hafif yağmur bekleniyor. "
        "Şemsiyeni yanına alman iyi olur ama ciddi bir yağış değil. "
        "Yarın sabah sisli başlayacak, öğleden sonra açacak. "
        "Hafta sonu daha güneşli görünüyor ve sıcaklık iki derece artacak. "
        "Rüzgar için ince bir ceket iyi olur, akşam serin olabilir. "
        "Bir sorun olursa yine sorabilirsin.")
SHORT = "Kısa cevap burada. İkinci cümle de burada."


class SpeechSummaryTests(unittest.TestCase):
    def test_short_answer_is_never_trimmed(self):
        from modules.engine_voice import spoken_answer
        self.assertEqual(speech_summary(SHORT), ("", ""))
        self.assertEqual(spoken_answer(SHORT), (SHORT, ""))

    def test_long_answer_stops_at_a_complete_sentence(self):
        self.assertGreater(len(LONG), SPEECH_LONG_ANSWER_CHARS)
        spoken, remainder = speech_summary(LONG)
        self.assertTrue(spoken and remainder)
        self.assertTrue(spoken.endswith("."), spoken[-40:])
        # Seslendirilen kısım metnin tam başı; kalan kısım tam devamı.
        self.assertTrue(LONG.startswith(spoken))
        self.assertEqual(" ".join((spoken + " " + remainder).split()),
                         " ".join(LONG.split()))

    def test_voice_hook_appends_the_closing_sentence_at_a_sentence_end(self):
        from modules.engine_voice import spoken_answer
        spoken, remainder = spoken_answer(LONG)
        self.assertTrue(spoken.endswith(SPEECH_REMAINDER_NOTE))
        head = spoken[:-len(SPEECH_REMAINDER_NOTE)].strip()
        self.assertTrue(head.endswith("."), head[-40:])
        self.assertTrue(remainder.strip())
        # Yazı tarafı hiç değişmez: seslendirilen baş + kalan = cevabın kendisi.
        self.assertEqual(" ".join((head + " " + remainder).split()), " ".join(LONG.split()))

    def test_two_word_remainder_is_not_trimmed(self):
        text = "A" * 0 + ("Bu cümle uzun ve açıklamalı. " * 10) + "Tamam."
        spoken, remainder = speech_summary(text)
        self.assertEqual((spoken, remainder), ("", ""))


class RemainderHandoverTests(unittest.TestCase):
    def test_the_unspoken_part_is_handed_over_once(self):
        from modules.engine_voice import VoiceSession, spoken_answer
        class Fake(VoiceSession):
            def __init__(self):
                self.voice_remainder = ""
        session = Fake.__new__(Fake)
        session.voice_remainder = ""
        spoken, remainder = spoken_answer(LONG)
        session.voice_remainder = remainder
        self.assertTrue(spoken.strip())
        self.assertEqual(session.take_remainder(), remainder)
        self.assertEqual(session.take_remainder(), "")     # ikinci kez okunmaz


if __name__ == "__main__":
    unittest.main()
