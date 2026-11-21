"""Akış yolu: ilk parça ses inerken çalınır, kalanı eski yoldan gider.

Ölçüm (21 Kasım): tam dosyayı beklemek uzun cevapta ilk sesi 2,5-2,9 sn'ye
çıkarıyordu; sıcak bağlantıyla akış 730 ms'de başlıyor ve çalma penceresi tam
ses uzunluğunda (takılma yok). Bu testler sözleşmeyi kilitler: akış yalnız ilk
parçada, akış başarısızsa ses yine de çalar.
"""
import threading
import unittest

from modules.voice_core import (
    SpeechRequest, VoiceCatalog, VoiceCoordinator, VoiceSpec,
)


def catalog():
    return VoiceCatalog((VoiceSpec("tr_erkek", "Erkek", "edge", "tr-TR-AhmetNeural"),))


class _Receipts:
    def __init__(self):
        self.items = []
        self.condition = threading.Condition()

    def __call__(self, receipt):
        with self.condition:
            self.items.append(receipt)
            self.condition.notify_all()

    def wait(self, timeout=4.0):
        with self.condition:
            self.condition.wait_for(lambda: bool(self.items), timeout=timeout)
        return self.items


class StreamFirstChunkTests(unittest.TestCase):
    def setUp(self):
        self.receipts = _Receipts()
        self.coordinator = None
        self.synthesized = []
        self.played = []
        self.streamed = []

    def tearDown(self):
        if self.coordinator is not None:
            self.coordinator.close()

    def _adapter(self, stream_result=9600):
        class Adapter:
            def __call__(inner, spec, text, cancel):        # noqa: N805 - taklit adaptör
                self.synthesized.append(text)
                return b"mp3"

            def stream_play(inner, spec, text, cancel, on_start=None):   # noqa: N805
                self.streamed.append(text)
                if on_start is not None:
                    on_start()
                return stream_result

        return Adapter()

    def _play(self, audio, cancel, on_start=None):
        self.played.append(len(audio) if isinstance(audio, bytes) else audio)
        if on_start is not None:
            on_start()

    def _run(self, text, adapter):
        self.coordinator = VoiceCoordinator(catalog(), adapter, self._play, self.receipts,
                                            play_stream=adapter.stream_play)
        self.coordinator.submit(SpeechRequest("alice", "r1", "tr_erkek", text))
        return self.receipts.wait()

    def test_only_the_first_chunk_is_streamed(self):
        text = ("Birinci cümle burada ve biraz uzun tutuyorum ki tek parça olmasın. "
                "İkinci cümle de burada, o da yeterince uzun olsun diye uzatıyorum. "
                "Üçüncü cümle de burada ve sonuncusu olduğunu söylüyorum.")
        receipts = self._run(text, self._adapter())
        self.assertEqual(len(self.streamed), 1, receipts)
        self.assertTrue(self.streamed[0].startswith("Birinci cümle"))
        # Kalan cümleler eski yoldan (ön hazırlık + oynatma) gider.
        self.assertTrue(self.synthesized, receipts)
        self.assertTrue(all("Birinci cümle" not in chunk for chunk in self.synthesized))

    def test_a_failed_stream_still_plays_the_answer(self):
        receipts = self._run("Merhaba, kısa bir deneme cümlesi.",
                             self._adapter(stream_result=0))
        self.assertEqual(len(self.streamed), 1, receipts)
        self.assertTrue(self.synthesized, receipts)      # akış olmadı: normal yol
        self.assertTrue(self.played, receipts)           # ses yine de çalar

    def test_a_streamed_chunk_is_not_synthesized_again(self):
        self._run("Tek cümle.", self._adapter())
        self.assertEqual(self.synthesized, [])


if __name__ == "__main__":
    unittest.main()
